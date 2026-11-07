"""Background Task Worker and Recovery Subsystem for AIRA 2.0.

Provides local queue processing, atomic task claiming, execution leases,
heartbeats, retry limits, cooperative cancellation, concurrency management,
and crash recovery with uncertain side-effect reconciliation.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Callable, List, TYPE_CHECKING

from src.tasks.models import Task, TaskStatus, utc_now_iso
from src.tasks.repository import TaskRepository
from src.tasks.lifecycle import validate_transition

if TYPE_CHECKING:
    from src.tools.executor import ControlledToolExecutor

logger = logging.getLogger("aira.tasks.worker")


class TaskRecoveryManager:
    """Manages crash recovery, lease expiration, and task reconciliation."""

    # Action types that carry side-effects or external modifications
    SIDE_EFFECT_ACTION_TYPES = {
        "WRITE",
        "EXECUTE",
        "SYSTEM",
        "DESKTOP",
        "NETWORK_FETCH",
        "MUTATION",
        "SEND",
    }

    # High-risk tools known to have persistent side-effects
    SIDE_EFFECT_TOOLS = {
        "apply_code_edit",
        "run_project_tests",
        "desktop_click",
        "desktop_key_tap",
        "desktop_type",
        "desktop_press_hotkey",
    }

    def __init__(self, repo: TaskRepository):
        self.repo = repo

    def inspect_task_interruption(self, task: Task) -> str:
        """Inspects an interrupted task and decides recovery path.

        Returns one of:
            - 'RECONCILE': if side-effecting operations were attempted or in-flight (uncertain outcome)
            - 'RETRY': if the task is strictly idempotent and attempts remain
            - 'FAIL': if retry limit has been exhausted
        """
        # 1. Check max attempts
        if task.attempt_count >= task.max_attempts:
            return "FAIL"

        # 2. Check task declaration
        if task.input_data.get("idempotent") is False or task.input_data.get("side_effect") is True:
            return "RECONCILE"

        if task.task_type in ("side_effecting", "destructive", "code_edit", "shell", "desktop", "write"):
            return "RECONCILE"

        tool_name = task.input_data.get("tool_name")
        if tool_name and tool_name in self.SIDE_EFFECT_TOOLS:
            return "RECONCILE"

        # 3. Inspect recorded action events for this task
        action_events = self.repo.list_action_events(task_id=task.id)
        for event in action_events:
            # If an action event was attempted or completed with side effects
            if event.action_type and event.action_type.upper() in self.SIDE_EFFECT_ACTION_TYPES:
                return "RECONCILE"
            if event.risk_level and event.risk_level.upper() in ("HIGH", "CRITICAL"):
                return "RECONCILE"
            if event.tool_name and event.tool_name in self.SIDE_EFFECT_TOOLS:
                return "RECONCILE"
            if event.event_type in ("ACTION_STARTED", "ACTION_EXECUTED", "EXECUTE_SUCCESS"):
                # If an action actually executed
                return "RECONCILE"

        # Purely safe/idempotent or zero actions taken
        return "RETRY"

    def recover_on_startup(self) -> Dict[str, int]:
        """Scans all interrupted tasks left in RUNNING on startup and safely reconciles or requeues them."""
        running_tasks = self.repo.get_running_tasks()
        stats = {"recovered_queued": 0, "reconciled": 0, "failed": 0, "total": len(running_tasks)}

        for task in running_tasks:
            decision = self.inspect_task_interruption(task)
            if decision == "RECONCILE":
                self.repo.update_task_status(
                    task_id=task.id,
                    new_status=TaskStatus.NEEDS_RECONCILIATION,
                    error_details={
                        "reconciliation_reason": "Task was interrupted mid-flight during potentially non-idempotent or side-effecting operations.",
                        "recovered_at": utc_now_iso(),
                        "previous_worker": task.worker_id,
                    },
                    event_message="Interrupted task flagged for manual reconciliation after startup recovery.",
                )
                stats["reconciled"] += 1
                logger.warning("Task %s flagged for reconciliation after restart.", task.id)

            elif decision == "RETRY":
                self.repo.update_task_status(
                    task_id=task.id,
                    new_status=TaskStatus.QUEUED,
                    error_details={
                        "recovery_reason": "Interrupted idempotent task safely recovered and requeued.",
                        "recovered_at": utc_now_iso(),
                    },
                    event_message="Interrupted idempotent task recovered and returned to QUEUED state.",
                )
                stats["recovered_queued"] += 1
                logger.info("Task %s safely requeued after restart.", task.id)

            else:  # FAIL
                self.repo.update_task_status(
                    task_id=task.id,
                    new_status=TaskStatus.FAILED,
                    error_details={
                        "failure_reason": f"Max attempts ({task.max_attempts}) reached upon recovery.",
                        "recovered_at": utc_now_iso(),
                    },
                    event_message=f"Task failed on recovery: attempt count ({task.attempt_count}) reached maximum ({task.max_attempts}).",
                )
                stats["failed"] += 1
                logger.warning("Task %s failed on recovery due to max attempts.", task.id)

        return stats

    def reap_stale_tasks(self, cutoff_iso: Optional[str] = None) -> Dict[str, int]:
        """Scans tasks whose worker leases have expired without active heartbeats."""
        stale_tasks = self.repo.get_stale_tasks(cutoff_iso=cutoff_iso)
        stats = {"recovered_queued": 0, "reconciled": 0, "failed": 0, "total": len(stale_tasks)}

        for task in stale_tasks:
            decision = self.inspect_task_interruption(task)
            if decision == "RECONCILE":
                self.repo.update_task_status(
                    task_id=task.id,
                    new_status=TaskStatus.NEEDS_RECONCILIATION,
                    error_details={
                        "reconciliation_reason": "Worker lease expired with uncertain side-effecting operations.",
                        "reaped_at": utc_now_iso(),
                        "expired_worker": task.worker_id,
                    },
                    event_message=f"Task lease expired for worker '{task.worker_id}'. Flagged for reconciliation.",
                )
                stats["reconciled"] += 1
            elif decision == "RETRY":
                self.repo.update_task_status(
                    task_id=task.id,
                    new_status=TaskStatus.QUEUED,
                    error_details={
                        "recovery_reason": f"Worker '{task.worker_id}' lease expired; task safely requeued.",
                        "reaped_at": utc_now_iso(),
                    },
                    event_message=f"Task lease expired for worker '{task.worker_id}'. Safely requeued for retry.",
                )
                stats["recovered_queued"] += 1
            else:
                self.repo.update_task_status(
                    task_id=task.id,
                    new_status=TaskStatus.FAILED,
                    error_details={
                        "failure_reason": "Worker lease expired and max retry attempts reached.",
                        "reaped_at": utc_now_iso(),
                    },
                    event_message="Task failed after lease expiry and max retry attempts reached.",
                )
                stats["failed"] += 1

        return stats


class TaskWorker:
    """Individual background task worker instance."""

    def __init__(
        self,
        repo: TaskRepository,
        executor: Optional[ControlledToolExecutor] = None,
        worker_id: Optional[str] = None,
        lease_seconds: int = 30,
        heartbeat_interval: float = 2.0,
        poll_interval: float = 0.5,
    ):
        self.repo = repo
        self.executor = executor
        self.worker_id = worker_id or f"worker_{uuid.uuid4().hex[:8]}"
        self.lease_seconds = lease_seconds
        self.heartbeat_interval = heartbeat_interval
        self.poll_interval = poll_interval
        self._handlers: Dict[str, Callable[[Task], Dict[str, Any]]] = {}
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def register_handler(self, task_type: str, handler: Callable[[Task], Dict[str, Any]]) -> None:
        """Registers a custom handler for a specific task_type."""
        self._handlers[task_type] = handler

    def check_cancelled(self, task_id: str) -> bool:
        """Checks if cancellation was requested for the active task."""
        task = self.repo.get_task(task_id)
        if task and task.status == TaskStatus.CANCEL_REQUESTED:
            return True
        return False

    def execute_task(self, task: Task) -> Task:
        """Executes a claimed task with heartbeats, cancellation checks, and error handling."""
        # 1. Immediate cancellation check
        if self.check_cancelled(task.id):
            updated = self.repo.update_task_status(
                task_id=task.id,
                new_status=TaskStatus.CANCELLED,
                actor_id=self.worker_id,
                event_message="Task cancelled cooperatively prior to execution.",
            )
            return updated or task

        # 2. Heartbeat management in background thread
        stop_heartbeat = threading.Event()

        def _heartbeat_loop():
            while not stop_heartbeat.wait(self.heartbeat_interval):
                try:
                    self.repo.heartbeat_task(task.id, self.worker_id, self.lease_seconds)
                except Exception as e:
                    logger.debug("Heartbeat exception for task %s: %s", task.id, e)

        hb_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
        hb_thread.start()

        try:
            # 3. Check cancellation again before running action
            if self.check_cancelled(task.id):
                updated = self.repo.update_task_status(
                    task_id=task.id,
                    new_status=TaskStatus.CANCELLED,
                    actor_id=self.worker_id,
                    event_message="Task cancelled cooperatively before action execution.",
                )
                return updated or task

            # 4. Dispatch execution
            result: Dict[str, Any] = {}
            tool_name = task.input_data.get("tool_name")

            if self.executor and tool_name:
                arguments = task.input_data.get("arguments", {})
                pre_approved = task.input_data.get("pre_approved", False)
                approval_id = task.input_data.get("approval_id")

                exec_result = self.executor.execute_tool(
                    tool_name=tool_name,
                    arguments=arguments,
                    request_id=task.request_id,
                    task_id=task.id,
                    privacy_mode=task.privacy_mode,
                    pre_approved=pre_approved,
                    approval_id=approval_id,
                )

                # Check if approval required
                if exec_result.get("status") == "AWAITING_APPROVAL" or exec_result.get("policy_decision") == "REQUIRE_APPROVAL":
                    updated = self.repo.update_task_status(
                        task_id=task.id,
                        new_status=TaskStatus.AWAITING_APPROVAL,
                        result_data=exec_result,
                        actor_id=self.worker_id,
                        event_message=f"Action requires approval: {exec_result.get('approval_id')}",
                    )
                    return updated or task

                if exec_result.get("status") == "error":
                    # Action execution error
                    if task.attempt_count < task.max_attempts:
                        updated = self.repo.update_task_status(
                            task_id=task.id,
                            new_status=TaskStatus.QUEUED,
                            error_details=exec_result,
                            actor_id=self.worker_id,
                            event_message=f"Tool error on attempt {task.attempt_count}/{task.max_attempts}; requeued.",
                        )
                    else:
                        updated = self.repo.update_task_status(
                            task_id=task.id,
                            new_status=TaskStatus.FAILED,
                            error_details=exec_result,
                            actor_id=self.worker_id,
                            event_message=f"Task failed after {task.attempt_count} attempts.",
                        )
                    return updated or task

                result = exec_result

            elif task.task_type in self._handlers:
                result = self._handlers[task.task_type](task)
            else:
                # Default handler
                result = {
                    "message": f"Task '{task.title}' processed successfully by {self.worker_id}.",
                    "input_data": task.input_data,
                }

            # 5. Check cancellation after action before marking complete
            if self.check_cancelled(task.id):
                updated = self.repo.update_task_status(
                    task_id=task.id,
                    new_status=TaskStatus.CANCELLED,
                    actor_id=self.worker_id,
                    event_message="Task cancelled cooperatively after execution finished.",
                )
                return updated or task

            # 6. Mark COMPLETED
            updated = self.repo.update_task_status(
                task_id=task.id,
                new_status=TaskStatus.COMPLETED,
                result_data=result,
                actor_id=self.worker_id,
                event_message="Task completed successfully.",
            )
            return updated or task

        except Exception as exc:
            logger.error("Unhandled error executing task %s: %s", task.id, exc, exc_info=True)
            err_details = {
                "error": str(exc),
                "type": type(exc).__name__,
                "traceback": traceback.format_exc(),
            }
            if task.attempt_count < task.max_attempts:
                updated = self.repo.update_task_status(
                    task_id=task.id,
                    new_status=TaskStatus.QUEUED,
                    error_details=err_details,
                    actor_id=self.worker_id,
                    event_message=f"Exception on attempt {task.attempt_count}/{task.max_attempts}; requeued for retry.",
                )
            else:
                updated = self.repo.update_task_status(
                    task_id=task.id,
                    new_status=TaskStatus.FAILED,
                    error_details=err_details,
                    actor_id=self.worker_id,
                    event_message=f"Task failed permanently after exception: {str(exc)}",
                )
            return updated or task

        finally:
            stop_heartbeat.set()
            hb_thread.join(timeout=1.0)

    def run_once(self) -> Optional[Task]:
        """Claims and executes a single queued task if available."""
        task = self.repo.claim_next_queued_task(self.worker_id, self.lease_seconds)
        if not task:
            return None
        return self.execute_task(task)

    def start(self) -> None:
        """Starts worker loop in background thread."""
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()

        def _loop():
            logger.info("TaskWorker %s started.", self.worker_id)
            while not self._stop_event.is_set():
                try:
                    task = self.run_once()
                    if not task:
                        self._stop_event.wait(self.poll_interval)
                except Exception as e:
                    logger.error("TaskWorker %s encountered loop error: %s", self.worker_id, e)
                    self._stop_event.wait(self.poll_interval)
            logger.info("TaskWorker %s stopped.", self.worker_id)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        """Signals worker to stop and waits for thread termination."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)


class WorkerPool:
    """Manages a pool of concurrent workers with workspace coordination and serialization."""

    def __init__(
        self,
        repo: TaskRepository,
        executor: Optional[ControlledToolExecutor] = None,
        max_concurrency: int = 2,
        lease_seconds: int = 30,
        poll_interval: float = 0.5,
    ):
        self.repo = repo
        self.executor = executor
        self.max_concurrency = max(1, min(10, max_concurrency))
        self.lease_seconds = lease_seconds
        self.poll_interval = poll_interval

        # Serialization controls:
        # 1. Per-workspace lock to prevent concurrent modifications to the same project
        self._workspace_locks: Dict[str, threading.Lock] = {}
        self._workspace_registry_lock = threading.Lock()

        # 2. Global side-effect lock to ensure side-effecting operations are serialized
        self._side_effect_lock = threading.Lock()

        self._workers: List[TaskWorker] = []
        self._stop_event = threading.Event()
        self._pool_threads: List[threading.Thread] = []

    def _get_workspace_lock(self, workspace_key: str) -> threading.Lock:
        with self._workspace_registry_lock:
            if workspace_key not in self._workspace_locks:
                self._workspace_locks[workspace_key] = threading.Lock()
            return self._workspace_locks[workspace_key]

    def _is_side_effecting_task(self, task: Task) -> bool:
        """Determines if a task requires serialized side-effect execution."""
        if task.task_type in ("side_effecting", "destructive", "code_edit", "shell", "desktop", "write"):
            return True
        if task.input_data.get("side_effect") is True or task.input_data.get("idempotent") is False:
            return True
        tool_name = task.input_data.get("tool_name")
        if tool_name and tool_name in TaskRecoveryManager.SIDE_EFFECT_TOOLS:
            return True
        return False

    def run_worker_cycle(self, worker: TaskWorker) -> Optional[Task]:
        """Claims a task and executes it with proper serialization and workspace locking."""
        task = self.repo.claim_next_queued_task(worker.worker_id, self.lease_seconds)
        if not task:
            return None

        workspace_key = task.project_id or "default"
        ws_lock = self._get_workspace_lock(workspace_key)
        is_side_effect = self._is_side_effecting_task(task)

        # Coordinate execution:
        # Acquire workspace lock to prevent concurrent modifications to the same workspace
        with ws_lock:
            if is_side_effect:
                # Acquire global side-effect lock to serialize side-effecting operations
                with self._side_effect_lock:
                    return worker.execute_task(task)
            else:
                return worker.execute_task(task)

    def start(self) -> None:
        """Starts worker pool threads."""
        self._stop_event.clear()
        self._workers = [
            TaskWorker(
                repo=self.repo,
                executor=self.executor,
                worker_id=f"worker_pool_{i+1}_{uuid.uuid4().hex[:6]}",
                lease_seconds=self.lease_seconds,
                poll_interval=self.poll_interval,
            )
            for i in range(self.max_concurrency)
        ]

        self._pool_threads = []
        for worker in self._workers:
            def _pool_loop(w=worker):
                while not self._stop_event.is_set():
                    try:
                        res = self.run_worker_cycle(w)
                        if not res:
                            self._stop_event.wait(self.poll_interval)
                    except Exception as e:
                        logger.error("Worker %s pool error: %s", w.worker_id, e)
                        self._stop_event.wait(self.poll_interval)

            t = threading.Thread(target=_pool_loop, daemon=True)
            self._pool_threads.append(t)
            t.start()

        logger.info("WorkerPool started with %d workers.", self.max_concurrency)

    def stop(self, timeout: float = 3.0) -> None:
        """Stops all workers in the pool."""
        self._stop_event.set()
        for t in self._pool_threads:
            if t.is_alive():
                t.join(timeout=timeout)
        logger.info("WorkerPool stopped.")
