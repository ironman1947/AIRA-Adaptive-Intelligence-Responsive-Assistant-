"""Tests for AIRA Controlled Mac Desktop Subsystem and Mandatory Approvals."""

import pytest
import tempfile
import os
from pathlib import Path

from src.desktop.service import DesktopControlService
from src.desktop.models import ActionCategory, DesktopActionPlan
from src.security.policy import PolicyDecisionEngine
from src.security.audit import AuditService
from src.memory.repository import MemoryRepository, get_db_manager


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_path = Path(tmpdir).resolve()
        # Create a sample file
        sample_file = workspace_path / "hello.py"
        sample_file.write_text("print('hello world')\n")
        yield workspace_path


@pytest.fixture
def desktop_service(temp_workspace):
    repo = MemoryRepository(get_db_manager())
    audit = AuditService(repo)
    policy = PolicyDecisionEngine(audit)
    service = DesktopControlService(
        authorized_roots=[str(temp_workspace)],
        policy_engine=policy,
        audit_service=audit,
    )
    return service


def test_inspect_authorized_directory(desktop_service, temp_workspace):
    res = desktop_service.inspect_directory(str(temp_workspace))
    assert res["success"] is True
    assert res["total_items"] >= 1
    assert any(e["name"] == "hello.py" for e in res["entries"])


def test_inspect_unauthorized_directory(desktop_service):
    # System root or user desktop outside authorized root must be rejected
    res = desktop_service.inspect_directory("/etc")
    assert res["success"] is False
    assert "outside authorized workspaces" in res["error"]


def test_find_files(desktop_service, temp_workspace):
    res = desktop_service.find_files("*.py", str(temp_workspace))
    assert res["success"] is True
    assert res["count"] == 1
    assert "hello.py" in res["matches"]


def test_read_file(desktop_service, temp_workspace):
    target = temp_workspace / "hello.py"
    res = desktop_service.read_file(str(target))
    assert res["success"] is True
    assert "print('hello world')" in res["content"]


def test_system_diagnostics(desktop_service):
    res = desktop_service.get_system_diagnostics()
    assert res["success"] is True
    diag = res["diagnostics"]
    assert diag["platform"] == "macOS"
    assert "cpu_brand" in diag or "product_version" in diag


def test_mandatory_approval_before_file_modification(desktop_service, temp_workspace):
    target = temp_workspace / "test_mod.py"
    target.write_text("initial_code = 1\n")

    # 1. Propose change
    plan = desktop_service.propose_file_change(
        file_path=str(target),
        new_content="initial_code = 2\n",
        explanation="Update constant from 1 to 2",
    )

    assert plan.status == "pending_approval"
    assert plan.category == ActionCategory.MODIFY
    assert "-initial_code = 1" in plan.diff
    assert "+initial_code = 2" in plan.diff

    # CRITICAL CHECK: File on disk MUST NOT have changed before approval!
    assert target.read_text() == "initial_code = 1\n"

    # 2. Rejecting the plan leaves the file completely untouched
    reject_res = desktop_service.reject_plan(plan.plan_id, reason="Testing reject")
    assert reject_res["status"] == "rejected"
    assert target.read_text() == "initial_code = 1\n"


def test_execute_approved_file_modification(desktop_service, temp_workspace):
    target = temp_workspace / "approved_mod.py"
    target.write_text("v = 'old'\n")

    plan = desktop_service.propose_file_change(
        file_path=str(target),
        new_content="v = 'new'\n",
        explanation="Apply approved patch",
    )

    # Cannot execute before approval
    fail_exec = desktop_service.execute_approved_plan(plan.plan_id)
    assert fail_exec["success"] is False
    assert "not in approved state" in fail_exec["error"] or "not been approved" in fail_exec["error"]
    assert target.read_text() == "v = 'old'\n"

    # Explicitly approve via policy engine
    desktop_service.policy_engine.resolve_approval(plan.plan_id, approved=True)

    # Now execute
    exec_res = desktop_service.execute_approved_plan(plan.plan_id)
    assert exec_res["success"] is True
    assert target.read_text() == "v = 'new'\n"


def test_app_launch_whitelisting(desktop_service):
    # Approved app
    plan = desktop_service.propose_app_launch("Safari")
    assert plan.tool_name == "open_application"
    assert plan.status == "pending_approval"
    assert plan.category.requires_explicit_approval is True

    # Unapproved app raises error
    with pytest.raises(ValueError) as exc:
        desktop_service.propose_app_launch("MaliciousApp")
    assert "not in the approved whitelist" in str(exc.value)
