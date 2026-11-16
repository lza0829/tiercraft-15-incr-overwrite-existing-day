from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """每个测试一个全新的本地 SQLite 库，夹具目录指向仓库内置贴源夹具。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("FIXTURES_DIR", str(REPO_ROOT / "fixtures"))

    from app import seed
    from app.services import pipeline

    seed.init_db()
    return {
        "seed": seed,
        "pipeline": pipeline,
        "data_dir": data_dir,
        "db_path": data_dir / "app.db",
    }


@pytest.fixture()
def client(temp_db):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)
