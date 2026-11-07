"""Tests for AIRA 2.0 Governance, Policy Decisions, and Persistent Approvals."""

import pytest
from datetime import datetime, timezone, timedelta

from src.memory.database import DatabaseManager
from src.tasks.repository import TaskRepository
from src.security.audit import AuditService
from src.security.policy import (
    PolicyDecisionEngine,
    compute_canonical_parameter_hash,
)
from src.tasks.models import ApprovalRequest, ApprovalStatus


@pytest.fixture
def governance_setup(tmp_path):
    db_file = str(tmp_path / "gov_test.db")
    db_mgr = DatabaseManager(db_file)
    task_repo = TaskRepository(db_mgr)
    from src.memory.repository import MemoryRepository
    mem_repo = MemoryRepository(db_mgr)
    audit = AuditService(mem_repo)
    engine = PolicyDecisionEngine(audit, task_repo=task_repo)
    return engine, task_repo, tmp_path


def test_canonical_parameter_hash_deterministic():
    p1 = {"b": 2, "a": 1, "nested": {"y": 20, "x": 10}}
    p2 = {"nested": {"x": 10, "y": 20}, "a": 1, "b": 2}
    # Different key ordering must produce exact same hash
    assert compute_canonical_parameter_hash(p1) == compute_canonical_parameter_hash(p2)

    # Different value must produce different hash
    p3 = {"a": 1, "b": 3}
    assert compute_canonical_parameter_hash(p1) != compute_canonical_parameter_hash(p3)


def test_safe_operation_allowed(governance_setup):
    engine, _, _ = governance_setup
    dec, risk, reason = engine.evaluate_action(
        action_type="READ",
        tool_name="rag_search",
        parameters={"query": "test query"},
    )
    assert dec == "ALLOW"
    assert risk == "LOW"


def test_consequential_operation_requires_approval(governance_setup):
    engine, _, workspace = governance_setup
    dec, risk, reason = engine.evaluate_action(
        action_type="WRITE",
        tool_name="apply_code_edit",
        parameters={"file_path": str(workspace / "code.py"), "diff": "+print()"},
        authorized_root=str(workspace),
    )
    assert dec == "REQUIRE_APPROVAL"
    assert risk == "HIGH"


def test_approval_lifecycle_and_atomic_consumption(governance_setup):
    engine, task_repo, workspace = governance_setup
    file_path = str(workspace / "script.py")
    params = {"file_path": file_path, "new_content": "print('hello')"}

    # 1. Register approval
    appr_id = "appr_test_123"
    rec = engine.register_approval_request(
        approval_id=appr_id,
        tool_name="apply_code_edit",
        parameters=params,
        reason="Modify script.py",
        risk_level="HIGH",
        ttl_minutes=15,
    )
    assert rec["id"] == appr_id
    assert rec["status"] == "pending"

    # Evaluate before user approval -> REJECTED because not yet approved
    dec, _, reason = engine.evaluate_action(
        action_type="WRITE",
        tool_name="apply_code_edit",
        parameters=params,
        approval_id=appr_id,
        authorized_root=str(workspace),
    )
    assert dec == "DENY"
    assert "not in approved state" in reason

    # 2. User approves
    engine.resolve_approval(appr_id, approved=True, decision_maker="user")

    # 3. Evaluate with approved ID -> ALLOW and consume
    dec, risk, reason = engine.evaluate_action(
        action_type="WRITE",
        tool_name="apply_code_edit",
        parameters=params,
        approval_id=appr_id,
        authorized_root=str(workspace),
    )
    assert dec == "ALLOW"
    assert "verified single-use human approval" in reason

    # 4. Immediate second attempt with same approval -> DENY (already consumed!)
    dec, _, reason = engine.evaluate_action(
        action_type="WRITE",
        tool_name="apply_code_edit",
        parameters=params,
        approval_id=appr_id,
        authorized_root=str(workspace),
    )
    assert dec == "DENY"
    assert "already been consumed" in reason


def test_approval_parameter_mismatch_denied(governance_setup):
    engine, _, workspace = governance_setup
    params = {"file_path": str(workspace / "code.py"), "action": "format"}
    appr_id = "appr_mismatch"

    engine.register_approval_request(
        approval_id=appr_id,
        tool_name="apply_code_edit",
        parameters=params,
        reason="Format code",
        risk_level="HIGH",
    )
    engine.resolve_approval(appr_id, approved=True)

    # Tamper with parameter: change 'format' to 'delete'
    tampered_params = {"file_path": str(workspace / "code.py"), "action": "delete"}
    dec, _, reason = engine.evaluate_action(
        action_type="WRITE",
        tool_name="apply_code_edit",
        parameters=tampered_params,
        approval_id=appr_id,
        authorized_root=str(workspace),
    )
    assert dec == "DENY"
    assert "Parameters modified" in reason


def test_approval_expiry_denied(governance_setup):
    engine, task_repo, workspace = governance_setup
    params = {"app_name": "Terminal"}
    appr_id = "appr_expired"

    # Register with negative ttl so it is expired immediately
    engine.register_approval_request(
        approval_id=appr_id,
        tool_name="desktop_open_application",
        parameters=params,
        reason="Launch Terminal",
        risk_level="MEDIUM",
        ttl_minutes=-5,  # expired 5 minutes ago
    )
    engine.resolve_approval(appr_id, approved=True)

    dec, _, reason = engine.evaluate_action(
        action_type="SYSTEM",
        tool_name="desktop_open_application",
        parameters=params,
        approval_id=appr_id,
    )
    assert dec == "DENY"
    assert "expired" in reason


def test_local_only_privacy_mode_enforced(governance_setup):
    engine, _, _ = governance_setup
    # Cloud routing blocked
    dec1, _, reason1 = engine.evaluate_action(
        action_type="CLOUD_ROUTING",
        tool_name="cloud_llm",
        parameters={"prompt": "hi"},
        privacy_mode="local_only",
    )
    assert dec1 == "DENY"
    assert "Local-Only privacy mode" in reason1

    # External web tools blocked
    dec2, _, reason2 = engine.evaluate_action(
        action_type="EXTERNAL_API",
        tool_name="search_web",
        parameters={"query": "python"},
        privacy_mode="local_only",
    )
    assert dec2 == "DENY"
    assert "Local-Only privacy mode" in reason2
