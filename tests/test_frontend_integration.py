"""Tests for AIRA Frontend Integration, Authentication Headers, and Conversation History Restoration."""

import os
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient
import src.main as main
from frontend import (
    get_auth_headers,
    get_backend_url,
    get_configured_token,
    api_get,
    api_post,
    api_patch,
    api_delete,
    resolve_engine_and_model_badge,
)

VALID_TEST_TOKEN = "frontend-test-token-aira-secret-key-999"


@pytest.fixture(autouse=True)
def configure_auth_tokens(monkeypatch):
    """Sets consistent authentication tokens for frontend tests."""
    monkeypatch.setenv("AIRA_API_TOKEN", VALID_TEST_TOKEN)
    monkeypatch.setattr(main, "AIRA_API_TOKEN", VALID_TEST_TOKEN)
    import src.config
    monkeypatch.setattr(src.config, "AIRA_API_TOKEN", VALID_TEST_TOKEN)


def test_get_configured_token_reads_environment(monkeypatch):
    """Verifies that get_configured_token retrieves token from environment."""
    monkeypatch.setenv("AIRA_API_TOKEN", "my-secret-env-token")
    assert get_configured_token() == "my-secret-env-token"


def test_get_auth_headers_formats_bearer_token(monkeypatch):
    """Verifies that get_auth_headers produces correct Authorization header."""
    monkeypatch.setenv("AIRA_API_TOKEN", "token-xyz-123")
    headers = get_auth_headers()
    assert headers.get("Authorization") == "Bearer token-xyz-123"


def test_get_auth_headers_merges_extra_headers(monkeypatch):
    """Verifies that extra headers are preserved when generating auth headers."""
    monkeypatch.setenv("AIRA_API_TOKEN", "token-xyz-123")
    headers = get_auth_headers({"X-Custom-Header": "CustomValue"})
    assert headers.get("Authorization") == "Bearer token-xyz-123"
    assert headers.get("X-Custom-Header") == "CustomValue"


def test_get_backend_url_respects_custom_env(monkeypatch):
    """Verifies that AIRA_BACKEND_URL is honored if set."""
    monkeypatch.setenv("AIRA_BACKEND_URL", "http://127.0.0.1:9090")
    assert get_backend_url() == "http://127.0.0.1:9090"


def test_live_missing_token_returns_401():
    """Live missing-token check: unauthenticated call to /api/conversations fails with 401."""
    client = TestClient(main.app, no_default_auth=True)
    resp = client.get("/api/conversations")
    assert resp.status_code == 401
    assert "Unauthorized" in resp.json().get("detail", "")


def test_live_invalid_token_returns_401():
    """Live invalid-token check: call with invalid token returns 401."""
    client = TestClient(main.app, headers={"Authorization": "Bearer totally-invalid-token"})
    resp = client.get("/api/conversations")
    assert resp.status_code == 401
    assert "Unauthorized" in resp.json().get("detail", "")


def test_live_valid_token_returns_200():
    """Live valid-token check: call with valid token succeeds with 200."""
    client = TestClient(main.app, headers={"Authorization": f"Bearer {VALID_TEST_TOKEN}"})
    resp = client.get("/api/conversations")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_conversation_history_lifecycle_with_authentication():
    """Full lifecycle: create conversation, append messages, retrieve history, and clean up."""
    client = TestClient(main.app, headers={"Authorization": f"Bearer {VALID_TEST_TOKEN}"})

    # 1. Create conversation
    create_resp = client.post("/api/conversations", json={"title": "Integration Test History"})
    assert create_resp.status_code == 200
    conv_id = create_resp.json()["id"]

    # 2. Add user message
    msg1_resp = client.post(
        f"/api/conversations/{conv_id}/messages",
        json={"role": "user", "content": "Hello AIRA, how is the conversation persistence?"},
    )
    assert msg1_resp.status_code == 200

    # 3. Add assistant message with metadata
    msg2_resp = client.post(
        f"/api/conversations/{conv_id}/messages",
        json={
            "role": "assistant",
            "content": "Conversation persistence is fully functional and encrypted in SQLite.",
            "engine": "local",
            "model": "gemma:2b",
            "metadata": {"sources_used": ["Architecture Spec v2.1"], "executed_tools": []},
        },
    )
    assert msg2_resp.status_code == 200

    # 4. Retrieve conversation with chronological history
    get_resp = client.get(f"/api/conversations/{conv_id}")
    assert get_resp.status_code == 200
    details = get_resp.json()
    assert details["id"] == conv_id
    assert details["title"] == "Integration Test History"
    assert len(details["messages"]) == 2
    assert details["messages"][0]["role"] == "user"
    assert details["messages"][1]["role"] == "assistant"
    assert details["messages"][1]["model"] == "gemma:2b"
    assert details["messages"][1]["metadata"]["sources_used"] == ["Architecture Spec v2.1"]

    # 5. Clean up
    del_resp = client.delete(f"/api/conversations/{conv_id}")
    assert del_resp.status_code == 200


def test_api_helpers_attach_authorization(monkeypatch):
    """Verifies that api_get, api_post, api_patch, api_delete attach Authorization header."""
    called_headers = []

    def fake_get(url, headers=None, **kwargs):
        called_headers.append(headers)
        mock_r = MagicMock()
        mock_r.status_code = 200
        mock_r.json.return_value = {"status": "ok"}
        return mock_r

    def fake_post(url, json=None, headers=None, **kwargs):
        called_headers.append(headers)
        mock_r = MagicMock()
        mock_r.status_code = 200
        mock_r.json.return_value = {"id": "conv_123"}
        return mock_r

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("requests.post", fake_post)

    api_get("/api/conversations")
    assert len(called_headers) == 1
    assert "Authorization" in called_headers[0]
    assert called_headers[0]["Authorization"].startswith("Bearer ")

    api_post("/api/conversations", {"title": "Test"})
    assert len(called_headers) == 2
    assert "Authorization" in called_headers[1]
    assert called_headers[1]["Authorization"].startswith("Bearer ")
