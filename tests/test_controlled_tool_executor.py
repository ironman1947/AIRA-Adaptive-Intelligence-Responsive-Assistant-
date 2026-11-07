"""Tests for AIRA 2.0 Centralized Controlled Tool Executor."""

import json
import pytest

from src.memory.database import DatabaseManager
from src.tasks.repository import TaskRepository
from src.security.audit import AuditService
from src.security.policy import PolicyDecisionEngine
from src.tools.registry import ToolRegistry, ToolDefinition
from src.tools.executor import ControlledToolExecutor


@pytest.fixture
def executor_setup(tmp_path):
    db_file = str(tmp_path / "executor_test.db")
    db_mgr = DatabaseManager(db_file)
    task_repo = TaskRepository(db_mgr)
    from src.memory.repository import MemoryRepository
    mem_repo = MemoryRepository(db_mgr)
    audit = AuditService(mem_repo)
    policy = PolicyDecisionEngine(audit, task_repo=task_repo)

    registry = ToolRegistry(workspace_root=str(tmp_path), memory_repo=mem_repo)

    # Register a custom tool for testing
    def sample_tool_handler(message: str, api_key: str = "") -> str:
        return f"Processed: {message}"

    registry.register(
        ToolDefinition(
            name="sample_test_tool",
            description="Sample testing tool",
            schema={
                "type": "function",
                "function": {
                    "name": "sample_test_tool",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message": {"type": "string"},
                            "api_key": {"type": "string"},
                        },
                        "required": ["message"],
                    },
                },
            },
            handler=sample_tool_handler,
            risk_level="LOW",
            action_type="TEST_ACTION",
        )
    )

    executor = ControlledToolExecutor(
        tool_registry=registry,
        policy_engine=policy,
        audit_service=audit,
        task_repo=task_repo,
        workspace_root=str(tmp_path),
    )

    return executor, task_repo, tmp_path


def test_registered_tool_execution_success(executor_setup):
    executor, task_repo, _ = executor_setup

    res = executor.execute_tool(
        tool_name="sample_test_tool",
        arguments={"message": "Hello Tool Executor", "api_key": "sk-secret123456789"},
        request_id="req_test_exec",
    )

    assert res["status"] == "success"
    assert res["policy_decision"] == "ALLOW"
    assert "Processed: Hello Tool Executor" in res["result"]

    # Verify action event was recorded and credentials redacted
    events = task_repo.list_action_events()
    assert len(events) >= 1
    ev = events[0]
    assert ev.tool_name == "sample_test_tool"
    assert ev.policy_decision == "ALLOW"
    assert ev.event_type == "TOOL_EXECUTED"
    # Credential in arguments payload must be redacted
    payload_args = ev.event_payload.get("arguments", {})
    assert payload_args.get("api_key") == "***REDACTED***"


def test_unknown_tool_rejection(executor_setup):
    executor, task_repo, _ = executor_setup

    res = executor.execute_tool(
        tool_name="unregistered_dangerous_tool",
        arguments={"param": "value"},
    )

    assert res["status"] == "error"
    assert res["policy_decision"] == "DENY"
    assert "not found in registry" in res["error"]


def test_invalid_arguments_rejection(executor_setup):
    executor, task_repo, _ = executor_setup

    # 'message' is a required argument for sample_test_tool
    res = executor.execute_tool(
        tool_name="sample_test_tool",
        arguments={},
    )

    assert res["status"] == "error"
    assert res["policy_decision"] == "DENY"
    assert "Missing required parameter 'message'" in res["error"]


def test_path_traversal_denied_by_executor(executor_setup):
    executor, task_repo, tmp_path = executor_setup
    outside_file = tmp_path.parent / "unauthorized_file.txt"

    res = executor.execute_tool(
        tool_name="read_project_file",
        arguments={"file_path": str(outside_file)},
    )

    assert res["status"] == "denied"
    assert res["policy_decision"] == "DENY"
    assert "outside authorized workspace" in res["reason"]


def test_tool_exception_handled_gracefully(executor_setup):
    executor, task_repo, _ = executor_setup

    def failing_handler(message: str) -> str:
        raise RuntimeError("Simulated crash inside tool")

    executor.registry.register(
        ToolDefinition(
            name="crash_tool",
            description="Tool that raises error",
            schema={"type": "function", "function": {"name": "crash_tool"}},
            handler=failing_handler,
            risk_level="LOW",
            action_type="TEST",
        )
    )

    res = executor.execute_tool(
        tool_name="crash_tool",
        arguments={"message": "fail"},
    )

    assert res["status"] == "error"
    assert "Simulated crash inside tool" in res["error"]

    events = task_repo.list_action_events()
    assert any(e.event_type == "TOOL_EXECUTION_FAILED" for e in events)
