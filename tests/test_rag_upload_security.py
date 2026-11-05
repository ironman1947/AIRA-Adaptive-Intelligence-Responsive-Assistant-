from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import src.main as main
from src.config import CORS_ORIGINS, HOST


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "AIRA_STORAGE_DIR", str(tmp_path))
    return TestClient(main.app)


@pytest.mark.parametrize(
    "filename",
    [
        "../outside.txt",
        "/tmp/outside.txt",
        r"..\outside.txt",
        ".env",
        "",
    ],
)
def test_upload_never_writes_outside_upload_directory(
    client, tmp_path, monkeypatch, filename
):
    indexed_paths = []

    def fake_index_document(**kwargs):
        indexed_paths.append(Path(kwargs["file_path"]))
        return {"status": "indexed"}

    monkeypatch.setattr(
        main.rag_store,
        "index_document",
        fake_index_document,
    )
    response = client.post(
        "/api/rag/upload",
        files={"file": (filename, b"test content")},
    )
    if filename == ".env" or filename == "":
        assert response.status_code == 400
        return
    assert response.status_code == 200
    assert len(indexed_paths) == 1
    upload_dir = (tmp_path / "uploads").resolve()
    saved_path = indexed_paths[0].resolve()
    assert saved_path.parent == upload_dir
    assert saved_path.is_file()


def test_upload_rejects_control_characters(client):
    response = client.post(
        "/api/rag/upload",
        files={"file": ("bad\x00file.txt", b"test content")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid filename"


def test_upload_rejects_excessive_file_size(client, monkeypatch):
    monkeypatch.setattr(
        main.rag_store,
        "index_document",
        lambda **kwargs: {"status": "indexed"},
    )
    oversized = b"a" * (51 * 1024 * 1024)
    response = client.post(
        "/api/rag/upload",
        files={"file": ("large_doc.txt", oversized)},
    )
    assert response.status_code == 413
    assert "exceeds" in response.json()["detail"]


def test_config_security_defaults():
    assert HOST == "127.0.0.1"
    assert "http://localhost:8501" in CORS_ORIGINS
    assert "http://127.0.0.1:8501" in CORS_ORIGINS
