"""Tests for AIRA 2.0 Persistent Task Management Subsystem."""

import pytest
from src.memory.database import DatabaseManager
from src.tasks import (
    TaskManager,
    TaskRepository,
    Task,
    TaskStatus,
    InvalidStateTransitionError,
)


@pytest.fixture
def task_manager(tmp_path):
    db_file = str(tmp_path / "task_test.db")
    db_mgr = DatabaseManager(db_file)
    repo = TaskRepository(db_mgr)
    return TaskManager(repo)


def test_task_creation_and_retrieval(task_manager):
    task = task_manager.create_task(
        title="Analyze System Architecture",
        objective="Assess concurrency and database latency.",
        priority=8,
        privacy_mode="local_only",
        input_data={"subsystem": "database"},
    )
    assert task.id.startswith("task_")
    assert task.status == TaskStatus.QUEUED
    assert task.priority == 8
    assert task.privacy_mode == "local_only"
    assert task.input_data == {"subsystem": "database"}

    # Fetch
    fetched = task_manager.get_task(task.id)
    assert fetched is not None
    assert fetched.id == task.id
    assert fetched.title == "Analyze System Architecture"


def test_task_idempotency_protection(task_manager):
    task1 = task_manager.create_task(
        title="Idempotent Task",
        idempotency_key="unique_key_12345",
    )
    # Second create with exact same key must return existing task
    task2 = task_manager.create_task(
        title="Different Title Ignored",
        idempotency_key="unique_key_12345",
    )
    assert task1.id == task2.id
    assert task2.title == "Idempotent Task"


def test_task_lifecycle_valid_transitions(task_manager):
    task = task_manager.create_task(title="Lifecycle Test")
    assert task.status == TaskStatus.QUEUED

    # QUEUED -> RUNNING
    task = task_manager.update_task_status(task.id, TaskStatus.RUNNING)
    assert task.status == TaskStatus.RUNNING
    assert task.started_at is not None

    # RUNNING -> AWAITING_APPROVAL
    task = task_manager.update_task_status(task.id, TaskStatus.AWAITING_APPROVAL)
    assert task.status == TaskStatus.AWAITING_APPROVAL

    # AWAITING_APPROVAL -> RUNNING
    task = task_manager.update_task_status(task.id, TaskStatus.RUNNING)
    assert task.status == TaskStatus.RUNNING

    # RUNNING -> COMPLETED
    task = task_manager.update_task_status(
        task.id,
        TaskStatus.COMPLETED,
        result_data={"output": "success"},
    )
    assert task.status == TaskStatus.COMPLETED
    assert task.completed_at is not None
    assert task.result_data == {"output": "success"}


def test_task_lifecycle_rejects_invalid_transitions(task_manager):
    task = task_manager.create_task(title="Invalid Transition Test")

    # QUEUED directly to COMPLETED is illegal
    with pytest.raises(InvalidStateTransitionError):
        task_manager.update_task_status(task.id, TaskStatus.COMPLETED)

    # Move to RUNNING then COMPLETED
    task_manager.update_task_status(task.id, TaskStatus.RUNNING)
    task_manager.update_task_status(task.id, TaskStatus.COMPLETED)

    # COMPLETED to RUNNING is illegal (terminal state)
    with pytest.raises(InvalidStateTransitionError):
        task_manager.update_task_status(task.id, TaskStatus.RUNNING)


def test_task_event_history_recorded(task_manager):
    task = task_manager.create_task(title="Event History Test")
    task_manager.update_task_status(task.id, TaskStatus.RUNNING)
    task_manager.update_task_status(task.id, TaskStatus.COMPLETED)

    events = task_manager.get_task_events(task.id)
    assert len(events) >= 3
    event_types = [e.event_type for e in events]
    assert "TASK_CREATED" in event_types
    assert "STATUS_CHANGE" in event_types


def test_task_cancellation_queued_vs_running(task_manager):
    # Queued cancellation transitions directly to CANCELLED
    t1 = task_manager.create_task(title="Cancel Queued")
    res1 = task_manager.cancel_task(t1.id, reason="User changed mind")
    assert res1.status == TaskStatus.CANCELLED
    assert res1.cancelled_at is not None

    # Running cancellation transitions to CANCEL_REQUESTED
    t2 = task_manager.create_task(title="Cancel Running")
    task_manager.update_task_status(t2.id, TaskStatus.RUNNING)
    res2 = task_manager.cancel_task(t2.id, reason="Emergency halt")
    assert res2.status == TaskStatus.CANCEL_REQUESTED


def test_task_atomic_claiming(task_manager):
    t1 = task_manager.create_task(title="Low Priority", priority=2)
    t2 = task_manager.create_task(title="High Priority", priority=9)

    repo = task_manager.repo
    # First claim should pick t2 (highest priority)
    claimed1 = repo.claim_next_queued_task(worker_id="worker_A", lease_seconds=30)
    assert claimed1 is not None
    assert claimed1.id == t2.id
    assert claimed1.status == TaskStatus.RUNNING
    assert claimed1.worker_id == "worker_A"
    assert claimed1.attempt_count == 1

    # Second claim should pick t1
    claimed2 = repo.claim_next_queued_task(worker_id="worker_B", lease_seconds=30)
    assert claimed2 is not None
    assert claimed2.id == t1.id

    # Third claim finds nothing queued
    claimed3 = repo.claim_next_queued_task(worker_id="worker_C", lease_seconds=30)
    assert claimed3 is None


def test_task_persistence_across_restarts(tmp_path):
    db_file = str(tmp_path / "restart_test.db")
    mgr1 = TaskManager(TaskRepository(DatabaseManager(db_file)))
    t = mgr1.create_task(title="Persistent Across Restarts", objective="Verify SQLite persistence")
    task_id = t.id

    # Simulate restart by creating fresh TaskManager pointing to same db
    mgr2 = TaskManager(TaskRepository(DatabaseManager(db_file)))
    restored = mgr2.get_task(task_id)
    assert restored is not None
    assert restored.title == "Persistent Across Restarts"
    assert restored.objective == "Verify SQLite persistence"
    assert restored.status == TaskStatus.QUEUED
