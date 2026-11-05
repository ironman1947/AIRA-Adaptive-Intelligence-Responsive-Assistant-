"""Automated tests for Project AIRA local API token authentication."""

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import src.main as main
from src.config import CORS_ORIGINS


VALID_TEST_TOKEN = "valid-test-token-aira-secret-key-12345"


@pytest.fixture(autouse=True)
def configure_test_token(monkeypatch):
    """Ensures server has a known valid token configured for authentication tests."""
    monkeypatch.setenv("AIRA_API_TOKEN", VALID_TEST_TOKEN)
    monkeypatch.setattr(main, "AIRA_API_TOKEN", VALID_TEST_TOKEN)
    import src.config
    monkeypatch.setattr(src.config, "AIRA_API_TOKEN", VALID_TEST_TOKEN)


def test_api_request_without_token_returns_401():
    """Unauthenticated request to protected /api/ endpoint must return HTTP 401."""
    client = TestClient(main.app, no_default_auth=True)
    response = client.get("/api/runtime-state")
    assert response.status_code == 401
    assert "Unauthorized" in response.json().get("detail", "")
    assert response.headers.get("WWW-Authenticate") == "Bearer"


def test_api_request_with_invalid_token_returns_401():
    """Request with incorrect or forged Bearer token must return HTTP 401."""
    client = TestClient(main.app, headers={"Authorization": "Bearer forged-invalid-token"})
    response = client.get("/api/runtime-state")
    assert response.status_code == 401
    assert "Unauthorized" in response.json().get("detail", "")


def test_api_request_with_malformed_auth_header_returns_401():
    """Request with missing 'Bearer' scheme must return HTTP 401."""
    client = TestClient(main.app, headers={"Authorization": f"Basic {VALID_TEST_TOKEN}"})
    response = client.get("/api/runtime-state")
    assert response.status_code == 401
    assert "Invalid Authorization header format" in response.json().get("detail", "")


def test_api_request_with_correct_token_returns_200():
    """Request with correct Bearer token proceeds to endpoint handler."""
    client = TestClient(main.app, headers={"Authorization": f"Bearer {VALID_TEST_TOKEN}"})
    response = client.get("/api/runtime-state")
    assert response.status_code == 200
    assert "assistant_name" in response.json()


def test_health_endpoint_remains_unauthenticated():
    """Health check endpoint /health remains open without requiring an API token."""
    client = TestClient(main.app, no_default_auth=True)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json().get("status") == "healthy"


def test_rag_upload_without_token_returns_401(tmp_path, monkeypatch):
    """RAG document upload without Bearer token must return HTTP 401."""
    monkeypatch.setattr(main, "AIRA_STORAGE_DIR", str(tmp_path))
    client = TestClient(main.app, no_default_auth=True)
    response = client.post(
        "/api/rag/upload",
        files={"file": ("document.txt", b"Sensitive document content")},
    )
    assert response.status_code == 401
    assert "Unauthorized" in response.json().get("detail", "")


def test_rag_upload_with_valid_token_succeeds(tmp_path, monkeypatch):
    """RAG document upload with valid Bearer token indexes document successfully."""
    monkeypatch.setattr(main, "AIRA_STORAGE_DIR", str(tmp_path))
    indexed_paths = []

    def fake_index_document(**kwargs):
        indexed_paths.append(Path(kwargs["file_path"]))
        return {"status": "indexed", "chunk_count": 1}

    monkeypatch.setattr(main.rag_store, "index_document", fake_index_document)

    client = TestClient(main.app, headers={"Authorization": f"Bearer {VALID_TEST_TOKEN}"})
    response = client.post(
        "/api/rag/upload",
        files={"file": ("document.txt", b"Sensitive document content")},
    )
    assert response.status_code == 200
    assert response.json().get("status") == "indexed"
    assert len(indexed_paths) == 1
    assert indexed_paths[0].is_file()


def test_cors_preflight_without_token_succeeds():
    """CORS preflight (OPTIONS) request succeeds without requiring Authorization token."""
    client = TestClient(main.app, no_default_auth=True)
    trusted_origin = CORS_ORIGINS[0] if CORS_ORIGINS else "http://localhost:8501"
    response = client.options(
        "/api/chat",
        headers={
            "Origin": trusted_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == trusted_origin
    assert "access-control-allow-methods" in response.headers


def test_trusted_frontend_origin_allowed():
    """Trusted frontend origin in CORS_ORIGINS is permitted in CORS headers."""
    client = TestClient(main.app, headers={"Authorization": f"Bearer {VALID_TEST_TOKEN}"})
    trusted_origin = "http://localhost:8501"
    response = client.get(
        "/api/runtime-state",
        headers={"Origin": trusted_origin},
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == trusted_origin


def test_untrusted_origin_disallowed():
    """Untrusted origin not in CORS_ORIGINS is rejected or disallowed."""
    client = TestClient(main.app, headers={"Authorization": f"Bearer {VALID_TEST_TOKEN}"})
    untrusted_origin = "http://malicious-external-site.com"
    response = client.get(
        "/api/runtime-state",
        headers={"Origin": untrusted_origin},
    )
    # Untrusted origin must not be reflected in access-control-allow-origin
    assert response.headers.get("access-control-allow-origin") != untrusted_origin


def test_missing_server_token_fails_closed(monkeypatch):
    """When AIRA_API_TOKEN is not configured on server, requests fail closed (401)."""
    monkeypatch.setenv("AIRA_API_TOKEN", "")
    monkeypatch.setattr(main, "AIRA_API_TOKEN", "")
    import src.config
    monkeypatch.setattr(src.config, "AIRA_API_TOKEN", "")

    client = TestClient(main.app, headers={"Authorization": "Bearer some-token"})
    response = client.get("/api/runtime-state")
    assert response.status_code == 401
    assert "not configured" in response.json().get("detail", "")
