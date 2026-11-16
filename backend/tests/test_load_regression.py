"""窄回归：增量跳过不得覆盖；全量后下游必须可观察地待重跑；装载裁决证明落库可查。"""
from __future__ import annotations

import os
from pathlib import Path

from app.db import connect

REPO_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"


def _domain_id(pipeline) -> int:
    domains = pipeline.list_domains()
    assert domains
    return domains[0]["id"]


def _paste_rows(domain_id: int) -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM layer_paste WHERE domain_id=? ORDER BY id", (domain_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _day_count_rows(domain_id: int) -> dict[str, int]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT biz_day, COUNT(*) AS c FROM layer_paste WHERE domain_id=? GROUP BY biz_day",
            (domain_id,),
        ).fetchall()
        return {str(r["biz_day"]): int(r["c"]) for r in rows}
    finally:
        conn.close()


def test_incremental_skips_existing_days_without_overwrite_or_delete(temp_db):
    pipeline = temp_db["pipeline"]
    domain_id = _domain_id(pipeline)
    pipeline.set_load_mode(domain_id, "incremental")

    # 建库初始化已按增量装载过一次；再装一次，夹具里的业务日都已存在，必须整日跳过。
    second = pipeline.load_paste(domain_id)
    assert second["status"] == "成功"
    assert second["written_days"] == []
    assert second["skipped_days"] == ["2026-11-10", "2026-11-11"]
    assert second["out_count"] == 0

    before = _paste_rows(domain_id)
    before_ids = [r["id"] for r in before]
    before_raw = {r["id"]: r["raw_json"] for r in before}
    before_counts = _day_count_rows(domain_id)

    # 第三次增量同样全部跳过：禁止删除、禁止覆盖。
    third = pipeline.load_paste(domain_id)
    assert third["written_days"] == []
    assert third["skipped_days"] == ["2026-11-10", "2026-11-11"]

    after = _paste_rows(domain_id)
    after_ids = [r["id"] for r in after]
    # 禁止删除：行集合不变；禁止覆盖：行 id 与原始 JSON 全部原样保留。
    assert after_ids == before_ids
    assert {r["id"]: r["raw_json"] for r in after} == before_raw
    assert _day_count_rows(domain_id) == before_counts

    # 全部跳过时贴源未变化，下游状态不应被改写。
    assert pipeline.get_domain(domain_id)["downstream_status"] == "未构建"

    # 跳过清单落在任务不可变快照列上。
    jobs = pipeline.list_jobs(domain_id)
    third_job = next(j for j in jobs if j["id"] == third["id"])
    assert third_job["skipped_days"] == ["2026-11-10", "2026-11-11"]


def test_incremental_skip_proof_immutable_and_matches_day_counts(temp_db):
    pipeline = temp_db["pipeline"]
    domain_id = _domain_id(pipeline)
    pipeline.set_load_mode(domain_id, "incremental")

    second = pipeline.load_paste(domain_id)
    verdict = pipeline.get_verdict_by_job(second["id"])

    assert verdict is not None
    assert verdict["job_id"] == second["id"]
    assert verdict["load_mode"] == "incremental"
    assert verdict["written_days"] == []
    assert verdict["skipped_days"] == ["2026-11-10", "2026-11-11"]
    assert verdict["downstream_pending"] is False

    # 证明中的按日行数与贴源按日计数接口同源一致。
    api_counts = {d["biz_day"]: d["rows"] for d in pipeline.paste_day_counts(domain_id)}
    for item in verdict["day_row_counts"]:
        assert item["rows"] == api_counts[item["biz_day"]]
        assert item["rows"] > 0

    # 证明只追加、不可变：再装一次后旧证明内容不变。
    pipeline.load_paste(domain_id)
    again = pipeline.get_verdict_by_job(second["id"])
    assert again["skipped_days"] == verdict["skipped_days"]
    assert again["written_days"] == verdict["written_days"]
    assert again["load_mode"] == verdict["load_mode"]

    conn = connect()
    try:
        # 每个贴源装载任务恰好一条证明。
        n_jobs = conn.execute(
            "SELECT COUNT(*) AS c FROM layer_jobs WHERE step='paste_load'"
        ).fetchone()["c"]
        n_verdicts = conn.execute("SELECT COUNT(*) AS c FROM load_verdicts").fetchone()["c"]
        assert n_jobs == n_verdicts
    finally:
        conn.close()


def test_full_load_clears_downstream_and_marks_pending(temp_db):
    pipeline = temp_db["pipeline"]
    domain_id = _domain_id(pipeline)
    pipeline.set_load_mode(domain_id, "incremental")

    # 先把下游建到「已对齐」。
    pipeline.run_paste_to_detail(domain_id)
    pipeline.run_detail_to_summary(domain_id)
    assert pipeline.get_domain(domain_id)["downstream_status"] == "已对齐"
    assert pipeline.layer_counts(domain_id)["明细层"] > 0
    assert pipeline.layer_counts(domain_id)["汇总层"] > 0

    # 切全量并重载。
    pipeline.set_load_mode(domain_id, "full")
    job = pipeline.load_paste(domain_id)
    assert job["status"] == "成功"
    assert job["written_days"] == ["2026-11-10", "2026-11-11"]

    # 下游明细/汇总必须被清空，且状态进入可观察的待重跑态（刷新后仍在）。
    counts = pipeline.layer_counts(domain_id)
    assert counts["贴源层"] > 0
    assert counts["明细层"] == 0
    assert counts["汇总层"] == 0
    assert pipeline.get_domain(domain_id)["downstream_status"] == "待重跑"

    verdict = pipeline.get_verdict_by_job(job["id"])
    assert verdict["load_mode"] == "full"
    assert verdict["downstream_pending"] is True

    # 旧对账报告须失效，不能继续展示为已对齐。
    reports = pipeline.list_reconcile(domain_id)
    assert all(r["stale"] for r in reports)


def test_reconcile_does_not_realign_empty_downstream_after_full_load(temp_db):
    pipeline = temp_db["pipeline"]
    domain_id = _domain_id(pipeline)
    pipeline.set_load_mode(domain_id, "incremental")
    pipeline.run_paste_to_detail(domain_id)
    pipeline.run_detail_to_summary(domain_id)
    assert pipeline.get_domain(domain_id)["downstream_status"] == "已对齐"

    pipeline.set_load_mode(domain_id, "full")
    pipeline.load_paste(domain_id)

    # 即便对账数值上空表“一致”，也禁止把空下游重新标成已对齐。
    report = pipeline.run_reconcile(domain_id)
    assert report["detail_count"] == 0
    assert pipeline.get_domain(domain_id)["downstream_status"] == "待重跑"

    # 重跑下游恢复后才允许回到已对齐。
    pipeline.run_paste_to_detail(domain_id)
    pipeline.run_detail_to_summary(domain_id)
    assert pipeline.get_domain(domain_id)["downstream_status"] == "已对齐"


def test_verdict_api_read_only_and_404_for_unknown_job(client):
    # 启动初始化已做过一次增量装载，任务与证明应可经只读接口查到。
    jobs_resp = client.get("/api/jobs")
    assert jobs_resp.status_code == 200
    load_jobs = [j for j in jobs_resp.json() if j["step"] == "paste_load"]
    assert load_jobs
    job_id = load_jobs[0]["id"]
    assert load_jobs[0]["load_verdict"] is not None

    resp = client.get(f"/api/load-verdicts/by-job/{job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == job_id
    assert set(
        ["load_mode", "written_days", "skipped_days", "downstream_pending"]
    ).issubset(body.keys())

    missing = client.get("/api/load-verdicts/by-job/999999")
    assert missing.status_code == 404

    listing = client.get("/api/load-verdicts")
    assert listing.status_code == 200
    assert any(v["job_id"] == job_id for v in listing.json())


def test_failed_load_records_verdict_without_touching_existing_data(temp_db, tmp_path):
    pipeline = temp_db["pipeline"]
    domain_id = _domain_id(pipeline)
    pipeline.set_load_mode(domain_id, "incremental")
    before = _paste_rows(domain_id)
    assert before  # 建库初始化已装入贴源

    # 换一份含坏行的夹具：装载失败，旧贴源必须原样保留。
    bad_fixture = tmp_path / "bad.jsonl"
    bad_fixture.write_text(
        '{"业务日":"2026-11-12","门店编码":"S09","门店名称":"新店","品类":"饮料","金额":"不是数字","件数":1}\n',
        encoding="utf-8",
    )
    conn = connect()
    try:
        conn.execute(
            "UPDATE domains SET fixture_file=? WHERE id=?", (bad_fixture.name, domain_id)
        )
        conn.commit()
    finally:
        conn.close()

    os.environ["FIXTURES_DIR"] = str(tmp_path)
    try:
        job = pipeline.load_paste(domain_id)
    finally:
        os.environ["FIXTURES_DIR"] = str(REPO_FIXTURES_DIR)

    assert job["status"] == "失败"
    assert job["fail_reason"]
    assert _paste_rows(domain_id) == before

    # 失败任务同样挂证明，可按任务 id 只读查询。
    verdict = pipeline.get_verdict_by_job(job["id"])
    assert verdict is not None
    assert verdict["written_days"] == []
    assert verdict["skipped_days"] == []
