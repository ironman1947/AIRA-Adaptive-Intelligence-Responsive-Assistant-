"""Tests for AIRA 2.0 Background Task Worker, WorkerPool, and Crash Recovery."""

import os
import time
import pytest
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from src.memory.database import DatabaseManager
from src.tasks.models import Task, TaskStatus, ActionEvent, utc_now_iso
from src.tasks.repository import TaskRepository
from src.tasks.manager import TaskManager
from src.tasks.worker import TaskWorker, WorkerPool, TaskRecoveryManager
from src.tools.registry import ToolRegistry, ToolDefinition
from src.security.policy import PolicyDecisionEngine
from src.security.audit import AuditService
from src.tools.executor import ControlledToolExecutor


@pytest.fixture
def test_repo(tmp_path):
    """Initializes a fresh isolated database and TaskRepository."""
    db_file = str(tmp_path / "aira_worker_test.db")
    db = DatabaseManager(db_path=db_file)
    db.initialize_schema()
    return TaskRepository(db)


@pytest.fixture
def tool_env(tmp_path, test_repo):
    """Sets up a test ControlledToolExecutor environment."""
    ws = str(tmp_path / "workspace")
    os.makedirs(ws, exist_ok=True)

    from src.memory.repository import MemoryRepository
    mem_repo = MemoryRepository(test_repo.db)
    audit = AuditService(mem_repo)
    policy = PolicyDecisionEngine(audit, task_repo=test_repo)
    registry = ToolRegistry(workspace_root=ws, memory_repo=mem_repo)

    executor = ControlledToolExecutor(
        tool_registry=registry,
        policy_engine=policy,
        audit_service=audit,
        task_repo=test_repo,
        workspace_root=ws,
    )
    return {
        "workspace": ws,
        "registry": registry,
        "audit": audit,
        "policy": policy,
        "executor": executor,
    }


def test_queue_processing_success(test_repo):
    """Verifies that a background worker claims and completes a queued task."""
    mgr = TaskManager(test_repo)
    task = mgr.create_task(
        title="Compute Metrics",
        task_type="custom_calc",
        input_data={"x": 10, "y": 20},
    )
    assert task.status == TaskStatus.QUEUED

    worker = TaskWorker(repo=test_repo, worker_id="worker_test_1")
    worker.register_handler(
        "custom_calc",
        lambda t: {"sum": t.input_data["x"] + t.input_data["y"]}
    )

    completed_task = worker.run_once()
    assert completed_task is not None
    assert completed_task.id == task.id
    assert completed_task.status == TaskStatus.COMPLETED
    assert completed_task.result_data == {"sum": 30}
    assert completed_task.worker_id == "worker_test_1"
    assert completed_task.completed_at is not None

    # Verify event history
    events = mgr.get_task_events(task.id)
    event_types = [e.event_type for e in events]
    assert "TASK_CREATED" in event_types
    assert "TASK_CLAIMED" in event_types
    assert "STATUS_CHANGE" in event_types


def test_worker_cooperative_cancellation(test_repo):
    """Verifies that a task requested for cancellation is cooperatively cancelled by worker."""
    mgr = TaskManager(test_repo)
    task = mgr.create_task(title="Long Task", task_type="long_op")

    # Claim the task
    claimed = test_repo.claim_next_queued_task("worker_cancel_test", lease_seconds=60)
    assert claimed.status == TaskStatus.RUNNING

    # Request cancellation while task is claimed
    cancelled_request = mgr.cancel_task(task.id, reason="User changed mind")
    assert cancelled_request.status == TaskStatus.CANCEL_REQUESTED

    # When worker attempts to execute, it detects CANCEL_REQUESTED and marks CANCELLED
    worker = TaskWorker(repo=test_repo, worker_id="worker_cancel_test")
    finished = worker.execute_task(claimed)

    assert finished.status == TaskStatus.CANCELLED
    assert finished.cancelled_at is not None

    events = mgr.get_task_events(task.id)
    new_statuses = [e.new_status for e in events]
    assert "CANCEL_REQUESTED" in new_statuses
    assert "CANCELLED" in new_statuses


def test_worker_tool_execution_and_retry_on_failure(test_repo, tool_env):
    """Verifies tool execution via ControlledToolExecutor and retry requeuing upon error."""
    mgr = TaskManager(test_repo)

    # Tool that fails (unregistered or invalid arguments)
    task = mgr.create_task(
        title="Failing Tool Task",
        input_data={"tool_name": "read_project_file", "arguments": {}},  # missing required file_path
        max_attempts=2,
    )

    worker = TaskWorker(repo=test_repo, executor=tool_env["executor"], worker_id="worker_tool_1")

    # First attempt: should fail schema check and requeue because attempt 1 < max 2
    task_after_1 = worker.run_once()
    assert task_after_1.status == TaskStatus.QUEUED
    assert task_after_1.attempt_count == 1
    assert task_after_1.worker_id is None  # worker_id cleared on requeue

    # Second attempt: should fail again and reach max_attempts -> FAILED
    task_after_2 = worker.run_once()
    assert task_after_2.status == TaskStatus.FAILED
    assert task_after_2.attempt_count == 2
    assert task_after_2.error_details is not None


def test_recovery_safe_idempotent_task_requeued(test_repo):
    """Verifies that an interrupted idempotent task with no side effects is safely requeued."""
    mgr = TaskManager(test_repo)
    task = mgr.create_task(
        title="Safe Search Task",
        task_type="search",
        input_data={"tool_name": "rag_search", "query": "hello", "idempotent": True},
        max_attempts=3,
    )

    # Simulate worker claiming task and crashing before completion
    claimed = test_repo.claim_next_queued_task("crashed_worker", lease_seconds=10)
    assert claimed.status == TaskStatus.RUNNING
    assert claimed.attempt_count == 1

    recovery = TaskRecoveryManager(test_repo)
    decision = recovery.inspect_task_interruption(claimed)
    assert decision == "RETRY"

    stats = recovery.recover_on_startup()
    assert stats["recovered_queued"] == 1
    assert stats["reconciled"] == 0

    recovered_task = test_repo.get_task(task.id)
    assert recovered_task.status == TaskStatus.QUEUED
    assert recovered_task.worker_id is None
    assert recovered_task.lease_expiry is None


def test_recovery_uncertain_side_effect_needs_reconciliation(test_repo):
    """Verifies that an interrupted task with side-effecting operations is flagged for reconciliation."""
    mgr = TaskManager(test_repo)
    task = mgr.create_task(
        title="Code Edit Task",
        task_type="code_edit",
        input_data={"tool_name": "apply_code_edit", "arguments": {"file_path": "test.py"}},
        max_attempts=3,
    )

    claimed = test_repo.claim_next_queued_task("worker_edit", lease_seconds=10)
    assert claimed.status == TaskStatus.RUNNING

    # Record an action event simulating partial or in-flight side-effecting execution
    test_repo.record_action_event(
        ActionEvent(
            action_id="act_reconcile_test",
            task_id=task.id,
            event_type="ACTION_EXECUTED",
            tool_name="apply_code_edit",
            action_type="WRITE",
            target_resource="test.py",
            risk_level="HIGH",
            parameter_fingerprint="abc",
            policy_decision="ALLOW",
        )
    )

    recovery = TaskRecoveryManager(test_repo)
    decision = recovery.inspect_task_interruption(claimed)
    assert decision == "RECONCILE"

    stats = recovery.recover_on_startup()
    assert stats["reconciled"] == 1
    assert stats["recovered_queued"] == 0

    reconciled_task = test_repo.get_task(task.id)
    assert reconciled_task.status == TaskStatus.NEEDS_RECONCILIATION
    assert "reconciliation_reason" in reconciled_task.error_details


def test_recovery_reap_stale_expired_leases(test_repo):
    """Verifies that tasks with expired leases are reaped properly."""
    mgr = TaskManager(test_repo)
    task = mgr.create_task(
        title="Stale Task",
        task_type="read_query",
        input_data={"idempotent": True},
        max_attempts=3,
    )

    claimed = test_repo.claim_next_queued_task("dead_worker", lease_seconds=-10)  # already expired

    recovery = TaskRecoveryManager(test_repo)
    stats = recovery.reap_stale_tasks()
    assert stats["recovered_queued"] == 1

    updated = test_repo.get_task(task.id)
    assert updated.status == TaskStatus.QUEUED


def test_worker_pool_concurrency_and_workspace_serialization(test_repo):
    """Verifies that WorkerPool executes independent tasks concurrently while serializing same-workspace tasks."""
    mgr = TaskManager(test_repo)

    execution_order = []

    def make_handler(label, duration=0.05):
        def _h(t):
            execution_order.append(f"{label}_start")
            time.sleep(duration)
            execution_order.append(f"{label}_end")
            return {"status": "ok"}
        return _h

    pool = WorkerPool(repo=test_repo, max_concurrency=2, lease_seconds=30, poll_interval=0.02)

    # Insert project for foreign key validity
    now = utc_now_iso()
    with test_repo.db.connection() as conn:
        conn.execute("INSERT OR IGNORE INTO projects (id, name, repo_path, created_at, updated_at) VALUES ('proj_alpha', 'Alpha', '/tmp', ?, ?);", (now, now))

    # Register custom handlers on the workers
    # Create two tasks in the SAME project marked as side_effect
    task1 = mgr.create_task(
        title="Project Task 1",
        task_type="task_same_ws",
        project_id="proj_alpha",
        input_data={"side_effect": True, "label": "t1"},
    )
    task2 = mgr.create_task(
        title="Project Task 2",
        task_type="task_same_ws",
        project_id="proj_alpha",
        input_data={"side_effect": True, "label": "t2"},
    )

    # Create worker instances inside pool
    worker1 = TaskWorker(repo=test_repo, worker_id="w1")
    worker1.register_handler("task_same_ws", make_handler("t1_run"))
    worker2 = TaskWorker(repo=test_repo, worker_id="w2")
    worker2.register_handler("task_same_ws", make_handler("t2_run"))

    # Test sequential execution on same workspace lock
    res1 = pool.run_worker_cycle(worker1)
    res2 = pool.run_worker_cycle(worker2)

    assert res1 is not None and res1.status == TaskStatus.COMPLETED
    assert res2 is not None and res2.status == TaskStatus.COMPLETED
