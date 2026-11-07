"""Tests for AIRA 2.0 Task and Approval REST API Endpoints."""

import pytest
from fastapi.testclient import TestClient

import src.main as main
import src.config
from src.tasks.models import TaskStatus, ApprovalStatus


VALID_TEST_TOKEN = "valid-test-token-aira-secret-key-12345"


@pytest.fixture(autouse=True)
def setup_api_env(monkeypatch):
    """Configures valid token for API test client."""
    monkeypatch.setenv("AIRA_API_TOKEN", VALID_TEST_TOKEN)
    monkeypatch.setattr(main, "AIRA_API_TOKEN", VALID_TEST_TOKEN)
    monkeypatch.setattr(src.config, "AIRA_API_TOKEN", VALID_TEST_TOKEN)


@pytest.fixture
def api_client():
    """Returns an authenticated TestClient."""
    return TestClient(main.app, headers={"Authorization": f"Bearer {VALID_TEST_TOKEN}"})


def test_task_endpoints_require_authentication():
    """Unauthenticated access to /api/tasks must return HTTP 401."""
    client = TestClient(main.app, no_default_auth=True)
    # GET tasks
    res = client.get("/api/tasks")
    assert res.status_code == 401

    # POST tasks
    res = client.post("/api/tasks", json={"title": "Test Task"})
    assert res.status_code == 401

    # GET approvals
    res = client.get("/api/approvals")
    assert res.status_code == 401


def test_task_lifecycle_api_crud_and_events(api_client):
    """Tests creating, retrieving, listing, and inspecting events of a task via API."""
    # 1. POST /api/tasks
    payload = {
        "title": "API Test Task",
        "objective": "Verify API lifecycle",
        "task_type": "standard",
        "priority": 8,
        "privacy_mode": "standard",
        "input_data": {"test_key": "val_123"},
    }
    create_res = api_client.post("/api/tasks", json=payload)
    assert create_res.status_code == 201
    created_task = create_res.json()
    task_id = created_task["id"]
    assert task_id.startswith("task_")
    assert created_task["title"] == "API Test Task"
    assert created_task["status"] == "QUEUED"
    assert created_task["priority"] == 8

    # 2. GET /api/tasks/{task_id}
    get_res = api_client.get(f"/api/tasks/{task_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == task_id

    # 3. GET /api/tasks (list)
    list_res = api_client.get("/api/tasks", params={"status": "QUEUED", "limit": 10})
    assert list_res.status_code == 200
    tasks = list_res.json()
    assert any(t["id"] == task_id for t in tasks)

    # 4. GET /api/tasks/{task_id}/events
    events_res = api_client.get(f"/api/tasks/{task_id}/events")
    assert events_res.status_code == 200
    events = events_res.json()
    assert len(events) >= 1
    assert events[0]["event_type"] == "TASK_CREATED"

    # 5. POST /api/tasks/{task_id}/cancel
    cancel_res = api_client.post(
        f"/api/tasks/{task_id}/cancel",
        json={"reason": "Testing cancellation"}
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"

    # 6. Verify 404 for non-existent task
    not_found = api_client.get("/api/tasks/task_nonexistent_xyz")
    assert not_found.status_code == 404


def test_approval_lifecycle_api(api_client):
    """Tests persistent approval listing, details, and decision resolution via API."""
    from src.agent.core import get_shared_task_repository
    from src.tasks.models import ApprovalRequest, utc_now_iso

    task_repo = get_shared_task_repository()
    approval_id = f"app_test_api_{utc_now_iso()[:19].replace(':', '')}"

    # Seed an approval request directly into the repository
    task_repo.create_approval_request(
        ApprovalRequest(
            id=approval_id,
            tool_name="apply_code_edit",
            action_type="WRITE",
            target_resource="src/test_api_file.py",
            parameters={"file_path": "src/test_api_file.py", "new_content": "print(1)"},
            canonical_param_hash="sample_api_hash_123",
            risk_level="HIGH",
            policy_reason="Code modification requires user authorization.",
            status=ApprovalStatus.PENDING,
        )
    )

    # 1. GET /api/approvals (list pending)
    list_res = api_client.get("/api/approvals", params={"status": "pending"})
    assert list_res.status_code == 200
    approvals = list_res.json()
    assert any(a["id"] == approval_id for a in approvals)

    # 2. GET /api/approvals/{approval_id}
    detail_res = api_client.get(f"/api/approvals/{approval_id}")
    assert detail_res.status_code == 200
    assert detail_res.json()["id"] == approval_id
    assert detail_res.json()["tool_name"] == "apply_code_edit"

    # 3. POST /api/approvals/{approval_id}/decision (Approve)
    decision_res = api_client.post(
        f"/api/approvals/{approval_id}/decision",
        json={
            "decision": "approved",
            "decision_maker": "test_engineer",
            "reason": "Authorized for unit testing"
        }
    )
    assert decision_res.status_code == 200
    resolved = decision_res.json()
    assert resolved["status"] == "approved"
    assert resolved["decision_maker"] == "test_engineer"

    # 4. Verify 404 for non-existent approval
    not_found = api_client.get("/api/approvals/app_nonexistent_999")
    assert not_found.status_code == 404


def test_legacy_approval_resolve_endpoint(api_client):
    """Verifies that existing /api/approvals/resolve route continues functioning."""
    import uuid
    from src.agent.core import get_shared_task_repository
    from src.tasks.models import ApprovalRequest

    task_repo = get_shared_task_repository()
    approval_id = f"app_legacy_{uuid.uuid4().hex[:8]}"

    task_repo.create_approval_request(
        ApprovalRequest(
            id=approval_id,
            tool_name="run_project_tests",
            action_type="EXECUTE",
            parameters={},
            canonical_param_hash="compat_hash_456",
            risk_level="HIGH",
            status=ApprovalStatus.PENDING,
        )
    )

    # Legacy payload: {"approval_id": ..., "approved": True}
    res = api_client.post("/api/approvals/resolve", json={"approval_id": approval_id, "approved": True})
    assert res.status_code == 200
    assert res.json()["status"] == "approved"
