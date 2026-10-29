"""Tests for AIRA Operational Constitution, Policy Decision Layer, and Audit Logger."""

import os
import pytest
from src.security.constitution import PRINCIPLES, CONSTITUTION_VERSION, get_constitution_summary
from src.security.network import validate_url_security
from src.security.audit import AuditService, redact_sensitive_text, redact_dict
from src.security.policy import PolicyDecisionEngine
from src.memory.database import DatabaseManager
from src.memory.repository import MemoryRepository

@pytest.fixture
def temp_repo(tmp_path):
    db_file = tmp_path / "test_policy.db"
    mgr = DatabaseManager(str(db_file))
    return MemoryRepository(mgr)

def test_constitution_principles():
    assert len(PRINCIPLES) == 7
    ids = [p["id"] for p in PRINCIPLES]
    assert ids == [1, 2, 3, 4, 5, 6, 7]
    assert CONSTITUTION_VERSION == "1.0.0"

    summary = get_constitution_summary()
    assert "Principle 1 [Human Safety" in summary
    assert "Principle 5 [Human Oversight" in summary
    assert "Principle 6 [Bounded Autonomy" in summary

def test_ssrf_blocking():
    # Private IPv4 addresses
    assert validate_url_security("http://127.0.0.1:8080/api")[0] is False
    assert validate_url_security("http://10.0.0.1/admin")[0] is False
    assert validate_url_security("http://192.168.1.1/")[0] is False
    assert validate_url_security("http://172.16.0.5/api")[0] is False
    assert validate_url_security("http://169.254.169.254/latest/meta-data/")[0] is False

    # Blocked domains
    assert validate_url_security("http://localhost:3000")[0] is False
    assert validate_url_security("http://metadata.google.internal")[0] is False

    # Disallowed protocols
    assert validate_url_security("file:///etc/passwd")[0] is False
    assert validate_url_security("ftp://example.com/file")[0] is False

def test_credential_redaction():
    text = "Connecting with api_key='sk-or-v1-abcdef012345678901234567' and password='SuperSecretPassword123!'"
    redacted = redact_sensitive_text(text)
    assert "sk-or-v1" not in redacted
    assert "SuperSecretPassword123!" not in redacted
    assert "***REDACTED***" in redacted

    data = {
        "user": "om",
        "api_key": "sk-secret123456789",
        "nested": {"token": "bearer xyz987654321"}
    }
    safe_data = redact_dict(data)
    assert safe_data["api_key"] == "***REDACTED***"
    assert safe_data["nested"]["token"] == "***REDACTED***"

def test_policy_decision_engine(temp_repo, tmp_path):
    audit = AuditService(temp_repo)
    engine = PolicyDecisionEngine(audit)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    inside_file = workspace / "script.py"
    inside_file.write_text("print('hello')")
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("secret")

    # 1. Low risk read permitted
    dec, risk, _ = engine.evaluate_action(
        action_type="READ",
        tool_name="search_web",
        parameters={"query": "python"},
        authorized_root=str(workspace),
    )
    assert dec == "ALLOW"
    assert risk == "LOW"

    # 2. Path traversal outside workspace denied
    dec, risk, reason = engine.evaluate_action(
        action_type="READ",
        tool_name="read_project_file",
        parameters={"file_path": str(outside_file)},
        authorized_root=str(workspace),
    )
    assert dec == "DENY"
    assert risk == "CRITICAL"
    assert "outside authorized workspace" in reason

    # 3. High risk code modification requires approval unless pre-approved
    dec, risk, _ = engine.evaluate_action(
        action_type="WRITE",
        tool_name="apply_code_edit",
        parameters={"file_path": str(inside_file), "new_content": "print('updated')"},
        authorized_root=str(workspace),
        pre_approved=False,
    )
    assert dec == "REQUIRE_APPROVAL"
    assert risk == "HIGH"

    # With pre-approval
    dec, risk, _ = engine.evaluate_action(
        action_type="WRITE",
        tool_name="apply_code_edit",
        parameters={"file_path": str(inside_file), "new_content": "print('updated')"},
        authorized_root=str(workspace),
        pre_approved=True,
    )
    assert dec == "ALLOW"

    # 4. Local-only mode blocks cloud routing
    dec, risk, _ = engine.evaluate_action(
        action_type="CLOUD_ROUTING",
        tool_name="cloud_llm",
        parameters={},
        privacy_mode="local_only",
    )
    assert dec == "DENY"
