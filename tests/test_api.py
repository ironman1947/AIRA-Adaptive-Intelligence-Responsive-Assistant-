"""Tests for AIRA FastAPI Endpoints."""

import pytest
from starlette.testclient import TestClient
from src.main import app

@pytest.fixture
def client():
    return TestClient(app)

def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["assistant"] == "AIRA"
    assert "version" in data

def test_runtime_state_endpoint(client):
    response = client.get("/api/runtime-state")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "AIRA"
    assert "active_engine" in data
    assert "enabled_tools" in data

def test_constitution_endpoint(client):
    response = client.get("/api/constitution")
    assert response.status_code == 200
    data = response.json()
    assert len(data["principles"]) == 7
    assert data["version"] == "1.0.0"

def test_projects_endpoint(client):
    response = client.get("/api/projects")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["id"] == "aira-core"

def test_feedback_endpoint(client):
    payload = {
        "request_id": "test_req_api",
        "helpful": True,
        "rating": 5,
        "category": "helpful",
        "user_explanation": "Very clear explanation"
    }
    response = client.post("/api/feedback", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "recorded"

def test_memory_endpoint(client):
    response = client.get("/api/memory?category=export")
    assert response.status_code == 200
    data = response.json()
    assert "user_profile" in data
    assert "episodic_memory" in data

def test_rag_search_endpoint(client):
    payload = {
        "query": "FastAPI",
        "top_k": 2
    }
    response = client.post("/api/rag/search", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "results" in data

def test_evaluation_run_endpoint(client):
    response = client.post("/api/evaluation/run")
    assert response.status_code == 200
    data = response.json()
    assert "accuracy_pct" in data
    assert data["total_cases"] >= 5

def test_voice_stop_endpoint(client):
    response = client.post("/api/voice/stop")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "stopped"
    assert data["interrupted"] is True

def test_desktop_status_endpoint(client):
    response = client.get("/api/desktop/status")
    assert response.status_code == 200
    data = response.json()
    assert "authorized_roots" in data
    assert "approved_applications" in data
    assert "Safari" in data["approved_applications"]
    assert "diagnostics" in data

def test_desktop_approve_reject_endpoint(client):
    # Reject non-existent plan returns clean error or reject status
    response = client.post("/api/desktop/approve", json={"approval_id": "nonexistent_plan", "approved": False})
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
