import pytest
import database as db
from starlette.testclient import TestClient
from app import app


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """TestClient backed by an isolated temporary SQLite database."""
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    db.init_db()  # explicit initialisation (idempotent if TestClient also triggers startup)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
