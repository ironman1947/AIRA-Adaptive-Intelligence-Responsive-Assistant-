"""Task Manager subsystem for AIRA 2.0.

Orchestrates task creation, lifecycle transitions, event logging, and status queries.
"""

import uuid
from typing import List, Dict, Any, Optional

from src.tasks.models import (
    Task,
    TaskStatus,
    TaskEvent,
    TaskCreateRequest,
    utc_now_iso,
)
from src.tasks.repository import TaskRepository
from src.tasks.lifecycle import validate_transition, is_terminal_status


class TaskManager:
    """High-level orchestration manager for asynchronous and background tasks."""

    def __init__(self, task_repo: TaskRepository):
        self.repo = task_repo

    def create_task(
        self,
        title: str,
        objective: Optional[str] = None,
        task_type: str = "standard",
        conversation_id: Optional[str] = None,
        project_id: Optional[str] = None,
        priority: int = 5,
        privacy_mode: str = "standard",
        input_data: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        request_id: Optional[str] = None,
        max_attempts: int = 3,
    ) -> Task:
        """Creates a new task in QUEUED state with validated attributes and idempotency check."""
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()

        task = Task(
            id=task_id,
            conversation_id=conversation_id,
            project_id=project_id,
            task_type=task_type,
            title=title.strip(),
            objective=objective.strip() if objective else None,
            status=TaskStatus.QUEUED,
            priority=max(1, min(10, priority)),
            privacy_mode="local_only" if privacy_mode == "local_only" else "standard",
            input_data=input_data or {},
            result_data={},
            error_details=None,
            request_id=request_id,
            idempotency_key=idempotency_key,
            attempt_count=0,
            max_attempts=max_attempts,
            worker_id=None,
            lease_expiry=None,
            heartbeat=None,
            version=1,
            created_at=now,
            updated_at=now,
        )

        return self.repo.create_task(task)

    def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieves a task by ID."""
        return self.repo.get_task(task_id)

    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        conversation_id: Optional[str] = None,
        project_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Task]:
        """Lists tasks with optional status and workspace filtering."""
        return self.repo.list_tasks(
            status=status,
            conversation_id=conversation_id,
            project_id=project_id,
            limit=limit,
            offset=offset,
        )

    def cancel_task(self, task_id: str, reason: str = "User requested cancellation") -> Optional[Task]:
        """Requests cancellation or cancels queued task immediately."""
        return self.repo.cancel_task(task_id, reason=reason)

    def update_task_status(
        self,
        task_id: str,
        new_status: TaskStatus,
        result_data: Optional[Dict[str, Any]] = None,
        error_details: Optional[Dict[str, Any]] = None,
        actor_id: Optional[str] = None,
        event_message: Optional[str] = None,
    ) -> Optional[Task]:
        """Validates transition and updates status."""
        return self.repo.update_task_status(
            task_id=task_id,
            new_status=new_status,
            result_data=result_data,
            error_details=error_details,
            actor_id=actor_id,
            event_message=event_message,
        )

    def get_task_events(self, task_id: str, limit: int = 100) -> List[TaskEvent]:
        """Retrieves chronological event log for a task."""
        return self.repo.list_task_events(task_id, limit=limit)
