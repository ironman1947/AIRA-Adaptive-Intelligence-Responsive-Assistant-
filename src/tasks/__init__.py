"""AIRA 2.0 Tasks Subsystem."""

from .models import (
    Task,
    TaskStatus,
    TaskEvent,
    ApprovalRequest,
    ApprovalStatus,
    ActionEvent,
    TaskCreateRequest,
    TaskCancelRequest,
    ApprovalDecisionRequest,
)
from .lifecycle import (
    validate_transition,
    is_valid_transition,
    is_terminal_status,
    is_active_status,
    InvalidStateTransitionError,
)
from .repository import TaskRepository
from .manager import TaskManager
from .worker import TaskWorker, WorkerPool, TaskRecoveryManager

__all__ = [
    "Task",
    "TaskStatus",
    "TaskEvent",
    "ApprovalRequest",
    "ApprovalStatus",
    "ActionEvent",
    "TaskCreateRequest",
    "TaskCancelRequest",
    "ApprovalDecisionRequest",
    "validate_transition",
    "is_valid_transition",
    "is_terminal_status",
    "is_active_status",
    "InvalidStateTransitionError",
    "TaskRepository",
    "TaskManager",
    "TaskWorker",
    "WorkerPool",
    "TaskRecoveryManager",
]
