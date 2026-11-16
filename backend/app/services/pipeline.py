from __future__ import annotations

import json
from pathlib import Path

from app.db import FIXTURES_DIR, connect, rows_to_dicts


STEP_LABEL = {
    "paste_load": "贴源装载",
    "paste_to_detail": "贴源到明细",
    "detail_to_summary": "明细到汇总",
}

LOAD_MODE_LABEL = {
    "incremental": "增量",
    "full": "全量",
}

# 下游可观察态：
#   未构建 —— 还没有明细数据
#   待重跑 —— 贴源已变化（全量重载 / 增量写入新业务日），明细与汇总需要重跑
#   已对齐 —— 明细与汇总已按当前贴源重建
DOWNSTREAM_NOT_BUILT = "未构建"
DOWNSTREAM_PENDING = "待重跑"
DOWNSTREAM_ALIGNED = "已对齐"

VALID_LOAD_MODES = ("incremental", "full")


def _job_view(row) -> dict:
    d = dict(row)
    d["step_label"] = STEP_LABEL.get(d["step"], d["step"])
    d["mode_label"] = LOAD_MODE_LABEL.get(d.get("mode") or "", "—")
    for key in ("written_days", "skipped_days"):
        raw = d.get(key) or "[]"
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            parsed = []
        d[key] = parsed if isinstance(parsed, list) else []
    d["written_day_count"] = len(d["written_days"])
    d["skipped_day_count"] = len(d["skipped_days"])
    d["fail_reason"] = d.get("fail_reason") or ""
    return d


def _load_json_list(raw) -> list:
    try:
        parsed = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _paste_day_counts(conn, domain_id: int) -> dict[str, int]:
    """贴源按业务日计数，与 /layers/paste/day-counts 同源（同一张表、同一种 GROUP BY）。"""
    rows = conn.execute(
        """
        SELECT biz_day, COUNT(*) AS c
          FROM layer_paste
         WHERE domain_id=?
         GROUP BY biz_day
        """,
        (domain_id,),
    ).fetchall()
    return {str(r["biz_day"]): int(r["c"]) for r in rows}


def _verdict_view(row, conn=None) -> dict:
    """装载裁决证明视图；按日计数读取时从贴源表现算，保证与贴源按日计数同源。"""
    d = dict(row)
    written_days = _load_json_list(d.get("written_days"))
    skipped_days = _load_json_list(d.get("skipped_days"))
    own_conn = conn is None
    if own_conn:
        conn = connect()
    try:
        counts = _paste_day_counts(conn, d["domain_id"])
    finally:
        if own_conn:
            conn.close()
    return {
        "id": d["id"],
        "job_id": d["job_id"],
        "domain_id": d["domain_id"],
        "load_mode": d["load_mode"],
        "load_mode_label": LOAD_MODE_LABEL.get(d["load_mode"], "—"),
        "written_days": written_days,
        "skipped_days": skipped_days,
        "written_day_count": len(written_days),
        "skipped_day_count": len(skipped_days),
        "downstream_pending": bool(d["downstream_pending"]),
        "downstream_status_label": DOWNSTREAM_PENDING if d["downstream_pending"] else "非待重跑",
        "day_row_counts": [
            {"biz_day": day, "rows": counts.get(day, 0)}
            for day in (written_days + skipped_days)
        ],
        "created_at": d["created_at"],
    }


def _attach_verdicts(conn, jobs: list[dict]) -> None:
    """给任务视图挂上装载裁决证明（仅贴源装载任务有）。"""
    rows = conn.execute("SELECT * FROM load_verdicts ORDER BY id").fetchall()
    by_job = {r["job_id"]: _verdict_view(r, conn) for r in rows}
    for job in jobs:
        job["load_verdict"] = by_job.get(job["id"])


def _domain_view(row) -> dict:
    d = dict(row)
    d["load_mode_label"] = LOAD_MODE_LABEL.get(d.get("load_mode") or "", "—")
    d["downstream_status"] = d.get("downstream_status") or DOWNSTREAM_NOT_BUILT
    return d


def list_domains() -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute("SELECT * FROM domains ORDER BY id").fetchall()
        return [_domain_view(r) for r in rows]
    finally:
        conn.close()


def get_domain(domain_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM domains WHERE id=?", (domain_id,)).fetchone()
        return _domain_view(row) if row else None
    finally:
        conn.close()


def set_load_mode(domain_id: int, mode: str) -> dict:
    if mode not in VALID_LOAD_MODES:
        raise ValueError("装载模式只能是增量或全量")
    conn = connect()
    try:
        row = conn.execute("SELECT id FROM domains WHERE id=?", (domain_id,)).fetchone()
        if not row:
            raise ValueError("主题域不存在")
        conn.execute("UPDATE domains SET load_mode=? WHERE id=?", (mode, domain_id))
        conn.commit()
        return _domain_view(
            conn.execute("SELECT * FROM domains WHERE id=?", (domain_id,)).fetchone()
        )
    finally:
        conn.close()


def _fixture_path(domain: dict) -> Path:
    name = domain["fixture_file"]
    path = FIXTURES_DIR / name
    if path.exists():
        return path
    return Path(__file__).resolve().parents[3] / "fixtures" / name


def _read_fixture_days(domain: dict) -> list[dict]:
    """按夹具顺序读出数据，并按业务日整日分组。任何解析问题都视为装载失败。"""
    path = _fixture_path(domain)
    if not path.exists():
        raise ValueError(f"夹具文件不存在：{domain['fixture_file']}")
    days: list[dict] = []
    index: dict[str, dict] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"夹具文件读取失败：{exc}") from exc
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"夹具第 {lineno} 行不是合法 JSON：{exc.msg}") from exc
        day = str(obj.get("业务日") or "").strip()
        if not day:
            raise ValueError(f"夹具第 {lineno} 行业务日为空")
        try:
            amount = float(obj.get("金额") or 0)
            qty = int(obj.get("件数") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"夹具第 {lineno} 行金额或件数不是数字") from exc
        record = {
            "biz_day": day,
            "store_code": str(obj.get("门店编码") or ""),
            "store_name": str(obj.get("门店名称") or ""),
            "category": str(obj.get("品类") or ""),
            "amount": amount,
            "qty": qty,
            "raw_json": json.dumps(obj, ensure_ascii=False),
        }
        bucket = index.get(day)
        if bucket is None:
            bucket = {"biz_day": day, "rows": []}
            index[day] = bucket
            days.append(bucket)
        bucket["rows"].append(record)
    return days


def _insert_paste(conn, domain_id: int, record: dict) -> None:
    conn.execute(
        """
        INSERT INTO layer_paste(
          domain_id, biz_day, store_code, store_name, category, amount, qty, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            domain_id,
            record["biz_day"],
            record["store_code"],
            record["store_name"],
            record["category"],
            record["amount"],
            record["qty"],
            record["raw_json"],
        ),
    )


def _record_load_job(
    conn,
    domain_id: int,
    mode: str,
    status: str,
    message: str,
    in_count: int,
    out_count: int,
    written_days: list[str],
    skipped_days: list[str],
    fail_reason: str = "",
) -> dict:
    cur = conn.execute(
        """
        INSERT INTO layer_jobs(
          domain_id, step, status, message, in_count, out_count, drop_count,
          mode, written_days, skipped_days, fail_reason
        ) VALUES (?, 'paste_load', ?, ?, ?, ?, 0, ?, ?, ?, ?)
        """,
        (
            domain_id,
            status,
            message,
            in_count,
            out_count,
            mode,
            json.dumps(written_days, ensure_ascii=False),
            json.dumps(skipped_days, ensure_ascii=False),
            fail_reason,
        ),
    )
    job_id = int(cur.lastrowid)
    # 装载裁决证明与任务同事务落库，只追加、不可变；
    # 下游是否待重跑以 domains 持久状态为准，界面刷新后仍可观察。
    pending_row = conn.execute(
        "SELECT downstream_status FROM domains WHERE id=?", (domain_id,)
    ).fetchone()
    downstream_pending = (
        pending_row is not None
        and pending_row["downstream_status"] == DOWNSTREAM_PENDING
    )
    conn.execute(
        """
        INSERT INTO load_verdicts(
          job_id, domain_id, load_mode, written_days, skipped_days, downstream_pending
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            domain_id,
            mode,
            json.dumps(written_days, ensure_ascii=False),
            json.dumps(skipped_days, ensure_ascii=False),
            1 if downstream_pending else 0,
        ),
    )
    return _job_view(
        conn.execute("SELECT * FROM layer_jobs WHERE id=?", (job_id,)).fetchone()
    )


def load_paste(domain_id: int) -> dict:
    """按主题域持久化的装载模式装载贴源夹具。

    增量：只追加贴源中尚不存在的业务日整日切片；已存在的业务日整日跳过，
          绝不覆盖或删除已有行。
    全量：清空该主题域贴源后按夹具重载，并清空明细/汇总，置为待重跑。
    """
    domain = get_domain(domain_id)
    if not domain:
        raise ValueError("主题域不存在")
    mode = domain["load_mode"] if domain["load_mode"] in VALID_LOAD_MODES else "incremental"

    conn = connect()
    written_days: list[str] = []
    skipped_days: list[str] = []
    try:
        days = _read_fixture_days(domain)
        total_rows = sum(len(d["rows"]) for d in days)
        if mode == "incremental":
            existing = {
                str(r["biz_day"])
                for r in conn.execute(
                    "SELECT DISTINCT biz_day FROM layer_paste WHERE domain_id=?", (domain_id,)
                ).fetchall()
            }
            for day in days:
                if day["biz_day"] in existing:
                    # 已存在业务日必须整日跳过：禁止覆盖、禁止删除任何已有日行，
                    # 只把该日落入跳过清单（任务快照列 + 装载裁决证明）。
                    skipped_days.append(day["biz_day"])
                    continue
                for record in day["rows"]:
                    _insert_paste(conn, domain_id, record)
                written_days.append(day["biz_day"])
            wrote_rows = sum(
                len(d["rows"]) for d in days if d["biz_day"] in written_days
            )
            if written_days:
                # 新业务日尚未进入下游；保留已有明细/汇总，只标记待重跑。
                # 全部跳过时贴源未变化，下游状态保持原样。
                conn.execute(
                    """
                    UPDATE domains SET downstream_status=?
                     WHERE id=? AND downstream_status<>?
                    """,
                    (DOWNSTREAM_PENDING, domain_id, DOWNSTREAM_NOT_BUILT),
                )
                conn.execute(
                    "UPDATE reconcile_reports SET stale=1 WHERE domain_id=?", (domain_id,)
                )
            message = (
                f"增量装载：写入 {len(written_days)} 个业务日 / {wrote_rows} 行；"
                f"跳过 {len(skipped_days)} 个已存在业务日（整日原样保留，未覆盖未删除）"
            )
        else:
            # 全量：先清空贴源与下游明细/汇总再按夹具重载。
            # 解析在上一步已完成，解析失败会直接抛错，不会动到旧数据。
            conn.execute("DELETE FROM layer_paste WHERE domain_id=?", (domain_id,))
            conn.execute("DELETE FROM layer_detail WHERE domain_id=?", (domain_id,))
            conn.execute("DELETE FROM layer_summary WHERE domain_id=?", (domain_id,))
            for day in days:
                for record in day["rows"]:
                    _insert_paste(conn, domain_id, record)
                written_days.append(day["biz_day"])
            wrote_rows = total_rows
            # 下游必须进入可观察的待重跑态：旧明细/旧汇总已清空，
            # 禁止全量后仍把旧下游当已对齐。
            conn.execute(
                "UPDATE domains SET downstream_status=? WHERE id=?",
                (DOWNSTREAM_PENDING, domain_id),
            )
            conn.execute(
                "UPDATE reconcile_reports SET stale=1 WHERE domain_id=?", (domain_id,)
            )
            message = (
                f"全量重载：清空贴源后按夹具重载 {len(written_days)} 个业务日 / {wrote_rows} 行；"
                "明细与汇总已清空，下游置为待重跑"
            )

        job = _record_load_job(
            conn,
            domain_id,
            mode,
            "成功",
            message,
            total_rows,
            wrote_rows,
            written_days,
            skipped_days,
        )
        verdict_row = conn.execute(
            "SELECT * FROM load_verdicts WHERE job_id=?", (job["id"],)
        ).fetchone()
        if verdict_row:
            job["load_verdict"] = _verdict_view(verdict_row, conn)
        conn.commit()
        return job
    except ValueError as exc:
        conn.rollback()
        fail_reason = str(exc)
        job = _record_load_job(
            conn,
            domain_id,
            mode,
            "失败",
            f"贴源{LOAD_MODE_LABEL[mode]}装载失败",
            0,
            0,
            [],
            skipped_days,
            fail_reason,
        )
        verdict_row = conn.execute(
            "SELECT * FROM load_verdicts WHERE job_id=?", (job["id"],)
        ).fetchone()
        if verdict_row:
            job["load_verdict"] = _verdict_view(verdict_row, conn)
        conn.commit()
        return job
    except Exception as exc:  # noqa: BLE001 - 任务失败要落记录而不是吞掉
        conn.rollback()
        fail_reason = str(exc) or "装载失败"
        job = _record_load_job(
            conn,
            domain_id,
            mode,
            "失败",
            f"贴源{LOAD_MODE_LABEL[mode]}装载失败",
            0,
            0,
            [],
            skipped_days,
            fail_reason,
        )
        verdict_row = conn.execute(
            "SELECT * FROM load_verdicts WHERE job_id=?", (job["id"],)
        ).fetchone()
        if verdict_row:
            job["load_verdict"] = _verdict_view(verdict_row, conn)
        conn.commit()
        return job
    finally:
        conn.close()


def paste_day_counts(domain_id: int) -> list[dict]:
    """贴源按业务日计数，供装载报告/界面核对。"""
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT biz_day, COUNT(*) AS rows, COUNT(DISTINCT store_code) AS stores
              FROM layer_paste
             WHERE domain_id=?
             GROUP BY biz_day
             ORDER BY biz_day
            """,
            (domain_id,),
        ).fetchall()
        return [
            {"biz_day": str(r["biz_day"]), "rows": int(r["rows"]), "stores": int(r["stores"])}
            for r in rows
        ]
    finally:
        conn.close()


def layer_rows(table: str, domain_id: int | None = None) -> list[dict]:
    allowed = {
        "paste": "layer_paste",
        "detail": "layer_detail",
        "summary": "layer_summary",
    }
    if table not in allowed:
        raise ValueError("未知分层")
    sql = f"SELECT * FROM {allowed[table]}"
    args: tuple = ()
    if domain_id is not None:
        sql += " WHERE domain_id=?"
        args = (domain_id,)
    sql += " ORDER BY id"
    conn = connect()
    try:
        return rows_to_dicts(conn.execute(sql, args).fetchall())
    finally:
        conn.close()


def layer_counts(domain_id: int | None = None) -> dict:
    conn = connect()
    try:
        where = " WHERE domain_id=?" if domain_id is not None else ""
        args = (domain_id,) if domain_id is not None else ()
        paste = conn.execute(f"SELECT COUNT(*) AS c FROM layer_paste{where}", args).fetchone()["c"]
        detail = conn.execute(f"SELECT COUNT(*) AS c FROM layer_detail{where}", args).fetchone()["c"]
        summary = conn.execute(f"SELECT COUNT(*) AS c FROM layer_summary{where}", args).fetchone()["c"]
        return {
            "贴源层": int(paste),
            "明细层": int(detail),
            "汇总层": int(summary),
        }
    finally:
        conn.close()


def list_jobs(domain_id: int | None = None) -> list[dict]:
    conn = connect()
    try:
        if domain_id is None:
            rows = conn.execute("SELECT * FROM layer_jobs ORDER BY id DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM layer_jobs WHERE domain_id=? ORDER BY id DESC", (domain_id,)
            ).fetchall()
        jobs = [_job_view(r) for r in rows]
        _attach_verdicts(conn, jobs)
        return jobs
    finally:
        conn.close()


def get_verdict_by_job(job_id: int) -> dict | None:
    """按任务 id 的只读装载裁决证明查询。"""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM load_verdicts WHERE job_id=?", (job_id,)
        ).fetchone()
        return _verdict_view(row) if row else None
    finally:
        conn.close()


def list_verdicts(domain_id: int | None = None) -> list[dict]:
    conn = connect()
    try:
        if domain_id is None:
            rows = conn.execute("SELECT * FROM load_verdicts ORDER BY id DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM load_verdicts WHERE domain_id=? ORDER BY id DESC",
                (domain_id,),
            ).fetchall()
        return [_verdict_view(r) for r in rows]
    finally:
        conn.close()


def run_paste_to_detail(domain_id: int) -> dict:
    domain = get_domain(domain_id)
    if not domain:
        raise ValueError("主题域不存在")
    conn = connect()
    try:
        conn.execute("DELETE FROM layer_detail WHERE domain_id=?", (domain_id,))
        paste = conn.execute(
            "SELECT * FROM layer_paste WHERE domain_id=? ORDER BY id", (domain_id,)
        ).fetchall()
        out = drop = 0
        for row in paste:
            store_name = (row["store_name"] or "").strip()
            amount = float(row["amount"])
            if not store_name or amount < 0:
                drop += 1
                continue
            conn.execute(
                """
                INSERT INTO layer_detail(
                  domain_id, biz_day, store_code, store_name, category, amount, qty, clean_flag
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    domain_id,
                    row["biz_day"],
                    row["store_code"],
                    store_name,
                    row["category"],
                    amount,
                    int(row["qty"]),
                    "已清洗",
                ),
            )
            out += 1
        # 明细已按当前贴源重建，但汇总尚未跟上。
        conn.execute(
            "UPDATE domains SET downstream_status=? WHERE id=?",
            (DOWNSTREAM_PENDING, domain_id),
        )
        cur = conn.execute(
            """
            INSERT INTO layer_jobs(domain_id, step, status, message, in_count, out_count, drop_count)
            VALUES (?, 'paste_to_detail', '成功', ?, ?, ?, ?)
            """,
            (domain_id, f"清洗完成，剔除门店名为空或金额为负的行", len(paste), out, drop),
        )
        conn.commit()
        job_id = int(cur.lastrowid)
        return _job_view(conn.execute("SELECT * FROM layer_jobs WHERE id=?", (job_id,)).fetchone())
    finally:
        conn.close()


def run_detail_to_summary(domain_id: int) -> dict:
    domain = get_domain(domain_id)
    if not domain:
        raise ValueError("主题域不存在")
    conn = connect()
    try:
        conn.execute("DELETE FROM layer_summary WHERE domain_id=?", (domain_id,))
        detail = conn.execute(
            "SELECT * FROM layer_detail WHERE domain_id=? ORDER BY id", (domain_id,)
        ).fetchall()
        buckets: dict[tuple, dict] = {}
        for row in detail:
            key = (row["biz_day"], row["store_code"])
            b = buckets.setdefault(
                key,
                {"biz_day": row["biz_day"], "store_code": row["store_code"], "amount": 0.0, "qty": 0, "n": 0},
            )
            b["amount"] += float(row["amount"])
            b["qty"] += int(row["qty"])
            b["n"] += 1
        for b in buckets.values():
            conn.execute(
                """
                INSERT INTO layer_summary(
                  domain_id, biz_day, store_code, amount_sum, qty_sum, line_count
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (domain_id, b["biz_day"], b["store_code"], b["amount"], b["qty"], b["n"]),
            )
        conn.execute(
            "UPDATE domains SET downstream_status=? WHERE id=?",
            (DOWNSTREAM_ALIGNED, domain_id),
        )
        cur = conn.execute(
            """
            INSERT INTO layer_jobs(domain_id, step, status, message, in_count, out_count, drop_count)
            VALUES (?, 'detail_to_summary', '成功', ?, ?, ?, 0)
            """,
            (domain_id, "按业务日+门店编码汇总", len(detail), len(buckets)),
        )
        conn.commit()
        job_id = int(cur.lastrowid)
        return _job_view(conn.execute("SELECT * FROM layer_jobs WHERE id=?", (job_id,)).fetchone())
    finally:
        conn.close()


def run_reconcile(domain_id: int) -> dict:
    domain = get_domain(domain_id)
    if not domain:
        raise ValueError("主题域不存在")
    conn = connect()
    try:
        paste_count = int(
            conn.execute("SELECT COUNT(*) AS c FROM layer_paste WHERE domain_id=?", (domain_id,)).fetchone()[
                "c"
            ]
        )
        detail_count = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM layer_detail WHERE domain_id=?", (domain_id,)
            ).fetchone()["c"]
        )
        summary = conn.execute(
            "SELECT COALESCE(SUM(line_count),0) AS s, COALESCE(SUM(amount_sum),0) AS a FROM layer_summary WHERE domain_id=?",
            (domain_id,),
        ).fetchone()
        summary_line_sum = int(summary["s"])
        summary_amount = float(summary["a"])
        detail_amount = float(
            conn.execute(
                "SELECT COALESCE(SUM(amount),0) AS a FROM layer_detail WHERE domain_id=?",
                (domain_id,),
            ).fetchone()["a"]
        )
        key_mismatch = 1 if summary_line_sum != detail_count else 0
        amount_drift = round(summary_amount - detail_amount, 4)
        aligned = key_mismatch == 0 and abs(amount_drift) < 0.0001
        if aligned:
            status = "一致"
        else:
            status = "存在差异"
        # 只有下游确实有数据且与贴源一致时才允许回到「已对齐」；
        # 全量重载清空下游后这里不得把空下游重新标成已对齐。
        if aligned and detail_count > 0:
            conn.execute(
                "UPDATE domains SET downstream_status=? WHERE id=?",
                (DOWNSTREAM_ALIGNED, domain_id),
            )
        elif detail_count == 0:
            conn.execute(
                "UPDATE domains SET downstream_status=? WHERE id=? AND downstream_status<>?",
                (DOWNSTREAM_PENDING, domain_id, DOWNSTREAM_NOT_BUILT),
            )
        detail = {
            "贴源行数": paste_count,
            "明细行数": detail_count,
            "汇总行数合计": summary_line_sum,
            "明细金额合计": detail_amount,
            "汇总金额合计": summary_amount,
            "键对齐": key_mismatch == 0,
            "金额漂移": amount_drift,
        }
        cur = conn.execute(
            """
            INSERT INTO reconcile_reports(
              domain_id, paste_count, detail_count, summary_line_sum, key_mismatch, amount_drift, status, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                domain_id,
                paste_count,
                detail_count,
                summary_line_sum,
                key_mismatch,
                amount_drift,
                status,
                json.dumps(detail, ensure_ascii=False),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM reconcile_reports WHERE id=?", (int(cur.lastrowid),)).fetchone()
        d = dict(row)
        d["detail"] = json.loads(d.pop("detail_json"))
        d["stale"] = bool(d.get("stale"))
        return d
    finally:
        conn.close()


def _report_view(row) -> dict:
    d = dict(row)
    d["detail"] = json.loads(d.pop("detail_json"))
    d["stale"] = bool(d.get("stale"))
    return d


def list_reconcile(domain_id: int | None = None) -> list[dict]:
    conn = connect()
    try:
        if domain_id is None:
            rows = conn.execute("SELECT * FROM reconcile_reports ORDER BY id DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM reconcile_reports WHERE domain_id=? ORDER BY id DESC",
                (domain_id,),
            ).fetchall()
        return [_report_view(r) for r in rows]
    finally:
        conn.close()


def dashboard() -> dict:
    domains = list_domains()
    counts = layer_counts()
    jobs = list_jobs()[:5]
    reports = list_reconcile()[:5]
    return {
        "主题域数": len(domains),
        "分层计数": counts,
        "最近任务": [
            {
                "编号": j["id"],
                "步骤": j["step_label"],
                "模式": j["mode_label"],
                "状态": j["status"],
                "写入": j["out_count"],
                "剔除": j["drop_count"],
                "写入日": j["written_days"],
                "跳过日": j["skipped_days"],
                "失败原因": j["fail_reason"],
                "装载裁决": (
                    {
                        "模式": j["load_verdict"]["load_mode_label"],
                        "写入日": j["load_verdict"]["written_days"],
                        "跳过日": j["load_verdict"]["skipped_days"],
                        "下游待重跑": j["load_verdict"]["downstream_pending"],
                    }
                    if j.get("load_verdict")
                    else None
                ),
            }
            for j in jobs
        ],
        "最近对账": [
            {
                "编号": r["id"],
                "状态": "已失效" if r["stale"] else r["status"],
                "明细行数": r["detail_count"],
                "汇总行数合计": r["summary_line_sum"],
            }
            for r in reports
        ],
        "主题域": [
            {
                "编号": d["id"],
                "名称": d["name"],
                "业务键": d["biz_key"],
                "装载模式": d["load_mode_label"],
                "下游状态": d["downstream_status"],
            }
            for d in domains
        ],
    }
