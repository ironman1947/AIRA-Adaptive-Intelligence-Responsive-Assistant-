"""Data models for AIRA 2.0 Tasks, Approvals, Events, and Lifecycles."""

from enum import Enum
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    """Returns current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


class TaskStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CONSUMED = "consumed"


class Task(BaseModel):
    id: str
    conversation_id: Optional[str] = None
    project_id: Optional[str] = None
    task_type: str = "standard"
    title: str
    objective: Optional[str] = None
    status: TaskStatus = TaskStatus.QUEUED
    priority: int = 5
    privacy_mode: str = "standard"
    input_data: Dict[str, Any] = Field(default_factory=dict)
    result_data: Dict[str, Any] = Field(default_factory=dict)
    error_details: Optional[Dict[str, Any]] = None
    request_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    attempt_count: int = 0
    max_attempts: int = 3
    worker_id: Optional[str] = None
    lease_expiry: Optional[str] = None
    heartbeat: Optional[str] = None
    version: int = 1
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    cancelled_at: Optional[str] = None


class TaskEvent(BaseModel):
    id: Optional[int] = None
    task_id: str
    event_type: str
    previous_status: Optional[str] = None
    new_status: Optional[str] = None
    actor_type: str = "system"
    actor_id: Optional[str] = None
    event_message: Optional[str] = None
    event_payload: Dict[str, Any] = Field(default_factory=dict)
    request_id: Optional[str] = None
    timestamp: str = Field(default_factory=utc_now_iso)


class ApprovalRequest(BaseModel):
    id: str
    task_id: Optional[str] = None
    action_id: Optional[str] = None
    tool_name: str
    action_type: str
    target_resource: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)
    canonical_param_hash: str
    risk_level: str = "HIGH"
    policy_reason: Optional[str] = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_at: str = Field(default_factory=utc_now_iso)
    expires_at: Optional[str] = None
    decision_at: Optional[str] = None
    decision_maker: Optional[str] = None
    decision_reason: Optional[str] = None
    consumed_at: Optional[str] = None


class ActionEvent(BaseModel):
    id: Optional[int] = None
    action_id: str
    task_id: Optional[str] = None
    approval_id: Optional[str] = None
    event_type: str
    tool_name: str
    action_type: str
    target_resource: Optional[str] = None
    parameter_fingerprint: Optional[str] = None
    policy_decision: str
    risk_level: str
    result_summary: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None
    event_payload: Dict[str, Any] = Field(default_factory=dict)
    request_id: Optional[str] = None
    timestamp: str = Field(default_factory=utc_now_iso)


class TaskCreateRequest(BaseModel):
    title: str
    objective: Optional[str] = None
    task_type: str = "standard"
    conversation_id: Optional[str] = None
    project_id: Optional[str] = None
    priority: int = 5
    privacy_mode: str = "standard"
    input_data: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = None
    max_attempts: int = 3


class TaskCancelRequest(BaseModel):
    reason: Optional[str] = "User requested cancellation"


class ApprovalDecisionRequest(BaseModel):
    decision: str  # "approved" or "rejected"
    decision_maker: Optional[str] = "user"
    reason: Optional[str] = None
