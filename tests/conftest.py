import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.database as database


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "aggregator.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.init_db()
    return database
