from __future__ import annotations

from app.db import connect


SCHEMA = """
CREATE TABLE IF NOT EXISTS domains (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  biz_key TEXT NOT NULL,
  fixture_file TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  load_mode TEXT NOT NULL DEFAULT 'incremental',
  downstream_status TEXT NOT NULL DEFAULT '未构建'
);

CREATE TABLE IF NOT EXISTS layer_paste (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain_id INTEGER NOT NULL,
  biz_day TEXT NOT NULL,
  store_code TEXT NOT NULL,
  store_name TEXT NOT NULL,
  category TEXT NOT NULL,
  amount REAL NOT NULL,
  qty INTEGER NOT NULL,
  raw_json TEXT NOT NULL,
  FOREIGN KEY(domain_id) REFERENCES domains(id)
);

CREATE TABLE IF NOT EXISTS layer_detail (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain_id INTEGER NOT NULL,
  biz_day TEXT NOT NULL,
  store_code TEXT NOT NULL,
  store_name TEXT NOT NULL,
  category TEXT NOT NULL,
  amount REAL NOT NULL,
  qty INTEGER NOT NULL,
  clean_flag TEXT NOT NULL,
  FOREIGN KEY(domain_id) REFERENCES domains(id)
);

CREATE TABLE IF NOT EXISTS layer_summary (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain_id INTEGER NOT NULL,
  biz_day TEXT NOT NULL,
  store_code TEXT NOT NULL,
  amount_sum REAL NOT NULL,
  qty_sum INTEGER NOT NULL,
  line_count INTEGER NOT NULL,
  UNIQUE(domain_id, biz_day, store_code),
  FOREIGN KEY(domain_id) REFERENCES domains(id)
);

CREATE TABLE IF NOT EXISTS layer_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain_id INTEGER NOT NULL,
  step TEXT NOT NULL,
  status TEXT NOT NULL,
  message TEXT NOT NULL DEFAULT '',
  in_count INTEGER NOT NULL DEFAULT 0,
  out_count INTEGER NOT NULL DEFAULT 0,
  drop_count INTEGER NOT NULL DEFAULT 0,
  mode TEXT NOT NULL DEFAULT '',
  written_days TEXT NOT NULL DEFAULT '[]',
  skipped_days TEXT NOT NULL DEFAULT '[]',
  fail_reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(domain_id) REFERENCES domains(id)
);

CREATE TABLE IF NOT EXISTS reconcile_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain_id INTEGER NOT NULL,
  paste_count INTEGER NOT NULL,
  detail_count INTEGER NOT NULL,
  summary_line_sum INTEGER NOT NULL,
  key_mismatch INTEGER NOT NULL,
  amount_drift REAL NOT NULL,
  status TEXT NOT NULL,
  detail_json TEXT NOT NULL,
  stale INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(domain_id) REFERENCES domains(id)
);
"""


def _columns(conn, table: str) -> set[str]:
    return {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate(conn) -> None:
    """给旧库补列，保留已有贴源/明细/汇总数据。"""
    added_downstream = False

    domain_cols = _columns(conn, "domains")
    if "load_mode" not in domain_cols:
        conn.execute(
            "ALTER TABLE domains ADD COLUMN load_mode TEXT NOT NULL DEFAULT 'incremental'"
        )
    if "downstream_status" not in domain_cols:
        conn.execute(
            "ALTER TABLE domains ADD COLUMN downstream_status TEXT NOT NULL DEFAULT '未构建'"
        )
        added_downstream = True

    job_cols = _columns(conn, "layer_jobs")
    if "mode" not in job_cols:
        conn.execute("ALTER TABLE layer_jobs ADD COLUMN mode TEXT NOT NULL DEFAULT ''")
    if "written_days" not in job_cols:
        conn.execute(
            "ALTER TABLE layer_jobs ADD COLUMN written_days TEXT NOT NULL DEFAULT '[]'"
        )
    if "skipped_days" not in job_cols:
        conn.execute(
            "ALTER TABLE layer_jobs ADD COLUMN skipped_days TEXT NOT NULL DEFAULT '[]'"
        )
    if "fail_reason" not in job_cols:
        conn.execute("ALTER TABLE layer_jobs ADD COLUMN fail_reason TEXT NOT NULL DEFAULT ''")

    report_cols = _columns(conn, "reconcile_reports")
    if "stale" not in report_cols:
        conn.execute("ALTER TABLE reconcile_reports ADD COLUMN stale INTEGER NOT NULL DEFAULT 0")

    if added_downstream:
        # 旧库没有状态列：已有下游数据的保守视为待重跑，等重跑/对账后再确认对齐。
        conn.execute(
            """
            UPDATE domains
               SET downstream_status = CASE
                     WHEN EXISTS (SELECT 1 FROM layer_detail d WHERE d.domain_id = domains.id)
                       THEN '待重跑'
                     ELSE '未构建'
                   END
             WHERE downstream_status = '未构建'
            """
        )


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        row = conn.execute("SELECT COUNT(*) AS c FROM domains").fetchone()
        seeded_id = None
        if int(row["c"]) == 0:
            seeded_id = _seed_domain(conn)
        conn.commit()
    finally:
        conn.close()

    if seeded_id is not None:
        # 首次建库按主题域默认模式装载一次，装载过程与手工装载走同一条路径并落任务记录。
        from app.services import pipeline

        pipeline.load_paste(seeded_id)


def _seed_domain(conn) -> int:
    """只登记主题域；贴源数据交由装载流程按装载模式写入。"""
    cur = conn.execute(
        """
        INSERT INTO domains(name, biz_key, fixture_file, description, load_mode, downstream_status)
        VALUES (?, ?, ?, ?, 'incremental', '未构建')
        """,
        (
            "门店日销售",
            "业务日+门店编码",
            "门店日销售-贴源.jsonl",
            "演示贴源装载、明细清洗与按门店日汇总",
        ),
    )
    return int(cur.lastrowid)
