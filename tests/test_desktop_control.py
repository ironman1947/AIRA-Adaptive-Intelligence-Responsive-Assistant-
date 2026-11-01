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


def test_open_url_requires_approval_and_open_url_category(desktop_service):
    """Verify proposing a public URL creates OPEN_URL plan requiring explicit approval."""
    plan = desktop_service.propose_open_url("https://python.org", browser="Safari")
    assert plan.category == ActionCategory.OPEN_URL
    assert plan.category.requires_explicit_approval is True
    assert plan.status == "pending_approval"
    assert plan.tool_name == "open_url"
    assert plan.parameters["url"] == "https://python.org"
    assert plan.plan_id in desktop_service.policy_engine.pending_approvals


def test_open_url_security_rejections(desktop_service):
    """Verify cloud metadata, file schemes, and loopback URLs are rejected before proposal."""
    with pytest.raises(PermissionError) as exc1:
        desktop_service.propose_open_url("http://169.254.169.254/latest/meta-data/")
    assert "security policy" in str(exc1.value).lower()

    with pytest.raises(PermissionError) as exc2:
        desktop_service.propose_open_url("file:///etc/passwd")
    assert "security policy" in str(exc2.value).lower()

    with pytest.raises(PermissionError) as exc3:
        desktop_service.propose_open_url("http://127.0.0.1:8000/secret")
    assert "security policy" in str(exc3.value).lower()


def test_youtube_query_encoding(desktop_service):
    """Verify YouTube query URL builder properly encodes spaces and special characters."""
    from src.desktop.service import build_youtube_search_url
    url = build_youtube_search_url("lofi hip hop & jazz / chill 100%")
    assert url.startswith("https://www.youtube.com/results?search_query=")
    assert " " not in url
    assert "lofi+hip+hop" in url or "lofi%20hip%20hop" in url
    assert "%26" in url or "%2F" in url or "%25" in url

    # Also test instance helper
    inst_url = desktop_service.build_youtube_search_url("Python 3.12 release")
    assert "Python+3.12+release" in inst_url or "Python%203.12%20release" in inst_url


def test_open_url_verification_success_and_failure(desktop_service):
    """Verify execute_approved_plan sets verified=True on success and verified=False on timeout."""
    from unittest.mock import patch, MagicMock

    # 1. Success case
    plan = desktop_service.propose_open_url("https://example.com", "Safari")
    desktop_service.policy_engine.resolve_approval(plan.plan_id, approved=True)

    def mock_subp_success(cmd, **kwargs):
        proc = MagicMock()
        if cmd[0] == "open":
            proc.returncode = 0
            return proc
        elif cmd[0] == "pgrep":
            proc.returncode = 0
            proc.stdout = "9999\n"
            return proc
        proc.returncode = 0
        return proc

    with patch("subprocess.run", side_effect=mock_subp_success):
        res = desktop_service.execute_approved_plan(plan.plan_id)
        assert res["success"] is True
        assert res["verified"] is True
        assert plan.verified is True
        assert "running" in res["verification_detail"]

    # 2. Failure case
    plan2 = desktop_service.propose_open_url("https://example.org", "Safari")
    desktop_service.policy_engine.resolve_approval(plan2.plan_id, approved=True)

    def mock_subp_fail(cmd, **kwargs):
        proc = MagicMock()
        if cmd[0] == "open":
            proc.returncode = 0
            return proc
        elif cmd[0] in ("pgrep", "osascript"):
            proc.returncode = 1
            proc.stdout = ""
            return proc
        return proc

    with patch("subprocess.run", side_effect=mock_subp_fail), patch("time.sleep"):
        res2 = desktop_service.execute_approved_plan(plan2.plan_id)
        assert res2["success"] is True
        assert res2["verified"] is False
        assert plan2.verified is False
        assert "Could not verify" in res2["verification_detail"]


def test_policy_engine_url_and_youtube_tools(desktop_service):
    """Verify policy engine requires approval for open_url and search_youtube with MEDIUM risk."""
    from src.security.policy import ActionRisk, PolicyDecision

    engine = desktop_service.policy_engine

    # Safe URL -> REQUIRE_APPROVAL, MEDIUM
    dec1, risk1, _ = engine.evaluate_action(
        action_type="DESKTOP_ACTION",
        tool_name="desktop_open_url",
        parameters={"url": "https://example.com", "browser": "Safari"},
    )
    assert dec1 == PolicyDecision.REQUIRE_APPROVAL
    assert risk1 == ActionRisk.MEDIUM

    # SSRF URL -> DENY, HIGH
    dec2, risk2, _ = engine.evaluate_action(
        action_type="DESKTOP_ACTION",
        tool_name="desktop_open_url",
        parameters={"url": "http://169.254.169.254/latest/meta-data/"},
    )
    assert dec2 == PolicyDecision.DENY
    assert risk2 == ActionRisk.HIGH

    # YouTube search -> REQUIRE_APPROVAL, MEDIUM
    dec3, risk3, _ = engine.evaluate_action(
        action_type="DESKTOP_ACTION",
        tool_name="desktop_search_youtube",
        parameters={"query": "python tutorial"},
    )
    assert dec3 == PolicyDecision.REQUIRE_APPROVAL
    assert risk3 == ActionRisk.MEDIUM
