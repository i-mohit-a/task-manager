import pytest
import storage as db
from starlette.testclient import TestClient
from app import app


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """TestClient backed by an isolated temporary text file storage."""
    tasks_file = tmp_path / "tasks.txt"
    tasks_file.write_text("")
    monkeypatch.setattr(db, "TASKS_FILE", tasks_file)
    monkeypatch.setattr(db, "ARCHIVE_FILE", tmp_path / "tasks.archive.txt")
    db.init_storage()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
