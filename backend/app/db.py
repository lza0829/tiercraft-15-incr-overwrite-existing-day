from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
FIXTURES_DIR = Path(
    os.environ.get("FIXTURES_DIR", Path(__file__).resolve().parents[2] / "fixtures")
)


def _db_path() -> Path:
    # 连接时再读环境变量，便于测试把库指到临时目录；默认值与历史行为一致。
    data_dir = Path(os.environ.get("DATA_DIR", DATA_DIR))
    return data_dir / "app.db"


def connect() -> sqlite3.Connection:
    Path(os.environ.get("DATA_DIR", DATA_DIR)).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]
