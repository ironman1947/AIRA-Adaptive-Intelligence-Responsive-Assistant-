"""Task Lifecycle validation and state transition rules for AIRA 2.0."""

from typing import Set, Dict
from src.tasks.models import TaskStatus


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal task state transition is attempted."""

    def __init__(self, current_status: TaskStatus, target_status: TaskStatus, message: str = ""):
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(
            message or f"Illegal task transition from '{current_status.value}' to '{target_status.value}'."
        )


# Valid transition graph
ALLOWED_TRANSITIONS: Dict[TaskStatus, Set[TaskStatus]] = {
    TaskStatus.QUEUED: {
        TaskStatus.RUNNING,
        TaskStatus.CANCEL_REQUESTED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.RUNNING: {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.AWAITING_APPROVAL,
        TaskStatus.CANCEL_REQUESTED,
        TaskStatus.NEEDS_RECONCILIATION,
        TaskStatus.QUEUED,  # Requeued for retry or lease release
    },
    TaskStatus.AWAITING_APPROVAL: {
        TaskStatus.RUNNING,   # Approved, resuming
        TaskStatus.QUEUED,    # Approved, waiting for worker
        TaskStatus.FAILED,    # Rejected
        TaskStatus.CANCEL_REQUESTED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.CANCEL_REQUESTED: {
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,
        TaskStatus.COMPLETED,  # Operation raced and finished before cancel took effect
    },
    TaskStatus.NEEDS_RECONCILIATION: {
        TaskStatus.RUNNING,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    # FAILED can be retried by transition back to QUEUED if attempts remain
    TaskStatus.FAILED: {
        TaskStatus.QUEUED,
    },
    # Terminal states
    TaskStatus.COMPLETED: set(),
    TaskStatus.CANCELLED: set(),
}

TERMINAL_STATES: Set[TaskStatus] = {
    TaskStatus.COMPLETED,
    TaskStatus.CANCELLED,
}

ACTIVE_STATES: Set[TaskStatus] = {
    TaskStatus.QUEUED,
    TaskStatus.RUNNING,
    TaskStatus.AWAITING_APPROVAL,
    TaskStatus.CANCEL_REQUESTED,
    TaskStatus.NEEDS_RECONCILIATION,
}


def is_valid_transition(current: TaskStatus, target: TaskStatus) -> bool:
    """Checks whether transitioning from current to target status is permitted."""
    if current == target:
        return True
    return target in ALLOWED_TRANSITIONS.get(current, set())


def validate_transition(current: TaskStatus, target: TaskStatus) -> None:
    """Validates state transition and raises InvalidStateTransitionError if illegal."""
    if not is_valid_transition(current, target):
        raise InvalidStateTransitionError(current, target)


def is_terminal_status(status: TaskStatus) -> bool:
    """Returns True if the task has concluded in a permanent terminal state."""
    return status in TERMINAL_STATES


def is_active_status(status: TaskStatus) -> bool:
    """Returns True if the task is currently active or in-flight."""
    return status in ACTIVE_STATES
