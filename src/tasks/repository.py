"""Task, Approval, and Event Persistence Repository for AIRA 2.0."""

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from src.memory.database import DatabaseManager
from src.tasks.models import (
    Task,
    TaskStatus,
    TaskEvent,
    ApprovalRequest,
    ApprovalStatus,
    ActionEvent,
    utc_now_iso,
)
from src.tasks.lifecycle import validate_transition


class TaskRepository:
    """Manages transactional persistence for Tasks, Task Events, Approvals, and Action Audits."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    # --------------------------------------------------------------------------
    # Task Operations
    # --------------------------------------------------------------------------

    def create_task(self, task: Task) -> Task:
        """Persists a new task. If an idempotency key is present and already exists, returns the existing task."""
        if task.idempotency_key:
            existing = self.get_task_by_idempotency_key(task.idempotency_key)
            if existing:
                return existing

        now = utc_now_iso()
        created_at = task.created_at or now
        updated_at = task.updated_at or now

        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    id, conversation_id, project_id, task_type, title, objective,
                    status, priority, privacy_mode, input_data, result_data,
                    error_details, request_id, idempotency_key, attempt_count,
                    max_attempts, worker_id, lease_expiry, heartbeat, version,
                    created_at, updated_at, started_at, completed_at, cancelled_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
                );
                """,
                (
                    task.id,
                    task.conversation_id,
                    task.project_id,
                    task.task_type,
                    task.title,
                    task.objective,
                    task.status.value,
                    task.priority,
                    task.privacy_mode,
                    json.dumps(task.input_data or {}),
                    json.dumps(task.result_data or {}),
                    json.dumps(task.error_details) if task.error_details else None,
                    task.request_id,
                    task.idempotency_key,
                    task.attempt_count,
                    task.max_attempts,
                    task.worker_id,
                    task.lease_expiry,
                    task.heartbeat,
                    task.version,
                    created_at,
                    updated_at,
                    task.started_at,
                    task.completed_at,
                    task.cancelled_at,
                ),
            )

        # Record creation event
        self.add_task_event(
            TaskEvent(
                task_id=task.id,
                event_type="TASK_CREATED",
                previous_status=None,
                new_status=task.status.value,
                actor_type="system",
                event_message=f"Task '{task.title}' created with status {task.status.value}.",
                event_payload={"priority": task.priority, "task_type": task.task_type},
                request_id=task.request_id,
            )
        )

        return self.get_task(task.id) or task

    def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieves a task by its unique ID."""
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?;", (task_id,)).fetchone()
            if not row:
                return None
            return self._row_to_task(row)

    def get_task_by_idempotency_key(self, key: str) -> Optional[Task]:
        """Retrieves a task matching an idempotency key."""
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE idempotency_key = ?;", (key,)).fetchone()
            if not row:
                return None
            return self._row_to_task(row)

    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        conversation_id: Optional[str] = None,
        project_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Task]:
        """Lists tasks with optional status and workspace filtering."""
        query = "SELECT * FROM tasks WHERE 1=1"
        params: List[Any] = []

        if status:
            query += " AND status = ?"
            params.append(status.value)
        if conversation_id:
            query += " AND conversation_id = ?"
            params.append(conversation_id)
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)

        query += " ORDER BY priority DESC, created_at DESC LIMIT ? OFFSET ?;"
        params.extend([limit, offset])

        with self.db.connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            return [self._row_to_task(r) for r in rows]

    def update_task_status(
        self,
        task_id: str,
        new_status: TaskStatus,
        result_data: Optional[Dict[str, Any]] = None,
        error_details: Optional[Dict[str, Any]] = None,
        actor_id: Optional[str] = None,
        event_message: Optional[str] = None,
    ) -> Optional[Task]:
        """Validates and updates task status, timestamps, and records transition event."""
        current = self.get_task(task_id)
        if not current:
            return None

        validate_transition(current.status, new_status)

        now = utc_now_iso()
        started_at = current.started_at
        completed_at = current.completed_at
        cancelled_at = current.cancelled_at

        new_worker_id = current.worker_id
        new_lease_expiry = current.lease_expiry
        new_heartbeat = current.heartbeat

        if new_status == TaskStatus.RUNNING and not started_at:
            started_at = now
        elif new_status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            completed_at = now
            new_lease_expiry = None
        elif new_status == TaskStatus.CANCELLED:
            cancelled_at = now
            new_lease_expiry = None
        elif new_status == TaskStatus.QUEUED:
            # Requeued: clear worker lease so it can be picked up
            new_worker_id = None
            new_lease_expiry = None
            new_heartbeat = None
        elif new_status == TaskStatus.NEEDS_RECONCILIATION:
            new_lease_expiry = None

        new_result = result_data if result_data is not None else current.result_data
        new_error = error_details if error_details is not None else current.error_details

        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE tasks SET
                    status = ?,
                    result_data = ?,
                    error_details = ?,
                    started_at = ?,
                    completed_at = ?,
                    cancelled_at = ?,
                    worker_id = ?,
                    lease_expiry = ?,
                    heartbeat = ?,
                    version = version + 1,
                    updated_at = ?
                WHERE id = ?;
                """,
                (
                    new_status.value,
                    json.dumps(new_result or {}),
                    json.dumps(new_error) if new_error else None,
                    started_at,
                    completed_at,
                    cancelled_at,
                    new_worker_id,
                    new_lease_expiry,
                    new_heartbeat,
                    now,
                    task_id,
                ),
            )

        # Record event
        msg = event_message or f"Status transitioned from {current.status.value} to {new_status.value}."
        self.add_task_event(
            TaskEvent(
                task_id=task_id,
                event_type="STATUS_CHANGE",
                previous_status=current.status.value,
                new_status=new_status.value,
                actor_type="worker" if actor_id else "system",
                actor_id=actor_id,
                event_message=msg,
                event_payload={"error": new_error} if new_error else {},
            )
        )

        return self.get_task(task_id)

    def claim_next_queued_task(
        self,
        worker_id: str,
        lease_seconds: int = 60,
    ) -> Optional[Task]:
        """Atomically claims the highest priority available QUEUED task.

        Returns the claimed Task, or None if no task is ready for execution.
        """
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        lease_expiry = (now_dt + timedelta(seconds=lease_seconds)).isoformat()

        with self.db.connection() as conn:
            # Find candidate task: QUEUED (highest priority, oldest first)
            candidate = conn.execute(
                """
                SELECT id, version FROM tasks
                WHERE status = 'QUEUED'
                ORDER BY priority DESC, created_at ASC
                LIMIT 1;
                """
            ).fetchone()

            if not candidate:
                return None

            task_id = candidate["id"]
            expected_version = candidate["version"]

            # Optimistic lock atomic claim
            cursor = conn.execute(
                """
                UPDATE tasks SET
                    status = 'RUNNING',
                    worker_id = ?,
                    lease_expiry = ?,
                    heartbeat = ?,
                    started_at = COALESCE(started_at, ?),
                    attempt_count = attempt_count + 1,
                    version = version + 1,
                    updated_at = ?
                WHERE id = ? AND version = ? AND status = 'QUEUED';
                """,
                (
                    worker_id,
                    lease_expiry,
                    now_iso,
                    now_iso,
                    now_iso,
                    task_id,
                    expected_version,
                ),
            )

            if cursor.rowcount == 0:
                # Lost race to another worker
                return None

        self.add_task_event(
            TaskEvent(
                task_id=task_id,
                event_type="TASK_CLAIMED",
                previous_status="QUEUED",
                new_status="RUNNING",
                actor_type="worker",
                actor_id=worker_id,
                event_message=f"Task claimed by worker '{worker_id}' with lease for {lease_seconds}s.",
            )
        )

        return self.get_task(task_id)

    def heartbeat_task(self, task_id: str, worker_id: str, lease_seconds: int = 60) -> bool:
        """Extends worker lease and records heartbeat."""
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        lease_expiry = (now_dt + timedelta(seconds=lease_seconds)).isoformat()

        with self.db.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE tasks SET
                    heartbeat = ?,
                    lease_expiry = ?,
                    updated_at = ?
                WHERE id = ? AND worker_id = ? AND status = 'RUNNING';
                """,
                (now_iso, lease_expiry, now_iso, task_id, worker_id),
            )
            return cursor.rowcount > 0

    def get_running_tasks(self) -> List[Task]:
        """Returns all tasks currently in RUNNING state."""
        return self.list_tasks(status=TaskStatus.RUNNING, limit=1000)

    def get_stale_tasks(self, cutoff_iso: Optional[str] = None) -> List[Task]:
        """Returns RUNNING tasks whose lease has expired before cutoff_iso."""
        cutoff = cutoff_iso or utc_now_iso()
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status = 'RUNNING' AND lease_expiry IS NOT NULL AND lease_expiry < ?
                ORDER BY created_at ASC;
                """,
                (cutoff,),
            ).fetchall()
            return [self._row_to_task(r) for r in rows]

    def cancel_task(self, task_id: str, reason: str = "User requested cancellation") -> Optional[Task]:
        """Cancels a task if in QUEUED state, or sets CANCEL_REQUESTED if in RUNNING state."""
        current = self.get_task(task_id)
        if not current:
            return None

        if current.status == TaskStatus.QUEUED:
            return self.update_task_status(
                task_id,
                TaskStatus.CANCELLED,
                event_message=f"Cancelled before execution: {reason}",
            )
        elif current.status in (TaskStatus.RUNNING, TaskStatus.AWAITING_APPROVAL):
            return self.update_task_status(
                task_id,
                TaskStatus.CANCEL_REQUESTED,
                event_message=f"Cancellation requested: {reason}",
            )
        return current

    # --------------------------------------------------------------------------
    # Task Event Operations
    # --------------------------------------------------------------------------

    def add_task_event(self, event: TaskEvent) -> TaskEvent:
        """Records an immutable lifecycle or execution event for a task."""
        now = event.timestamp or utc_now_iso()
        with self.db.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO task_events (
                    task_id, event_type, previous_status, new_status,
                    actor_type, actor_id, event_message, event_payload,
                    request_id, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    event.task_id,
                    event.event_type,
                    event.previous_status,
                    event.new_status,
                    event.actor_type,
                    event.actor_id,
                    event.event_message,
                    json.dumps(event.event_payload or {}),
                    event.request_id,
                    now,
                ),
            )
            event_id = cursor.lastrowid

        return TaskEvent(
            id=event_id,
            task_id=event.task_id,
            event_type=event.event_type,
            previous_status=event.previous_status,
            new_status=event.new_status,
            actor_type=event.actor_type,
            actor_id=event.actor_id,
            event_message=event.event_message,
            event_payload=event.event_payload,
            request_id=event.request_id,
            timestamp=now,
        )

    def list_task_events(self, task_id: str, limit: int = 100) -> List[TaskEvent]:
        """Retrieves chronological events for a specific task."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM task_events WHERE task_id = ? ORDER BY id ASC LIMIT ?;",
                (task_id, limit),
            ).fetchall()

            events = []
            for r in rows:
                try:
                    payload = json.loads(r["event_payload"] or "{}")
                except Exception:
                    payload = {}
                events.append(
                    TaskEvent(
                        id=r["id"],
                        task_id=r["task_id"],
                        event_type=r["event_type"],
                        previous_status=r["previous_status"],
                        new_status=r["new_status"],
                        actor_type=r["actor_type"],
                        actor_id=r["actor_id"],
                        event_message=r["event_message"],
                        event_payload=payload,
                        request_id=r["request_id"],
                        timestamp=r["timestamp"],
                    )
                )
            return events

    # --------------------------------------------------------------------------
    # Approval Request Operations
    # --------------------------------------------------------------------------

    def create_approval_request(self, req: ApprovalRequest) -> ApprovalRequest:
        """Persists a new pending human approval request with canonical hash binding."""
        now = req.requested_at or utc_now_iso()
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO approval_requests (
                    id, task_id, action_id, tool_name, action_type,
                    target_resource, parameters, canonical_param_hash,
                    risk_level, policy_reason, status, requested_at,
                    expires_at, decision_at, decision_maker, decision_reason, consumed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    req.id,
                    req.task_id,
                    req.action_id,
                    req.tool_name,
                    req.action_type,
                    req.target_resource,
                    json.dumps(req.parameters or {}),
                    req.canonical_param_hash,
                    req.risk_level,
                    req.policy_reason,
                    req.status.value,
                    now,
                    req.expires_at,
                    req.decision_at,
                    req.decision_maker,
                    req.decision_reason,
                    req.consumed_at,
                ),
            )
        return self.get_approval_request(req.id) or req

    def get_approval_request(self, approval_id: str) -> Optional[ApprovalRequest]:
        """Retrieves an approval request by its ID."""
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM approval_requests WHERE id = ?;", (approval_id,)).fetchone()
            if not row:
                return None
            return self._row_to_approval(row)

    def list_approval_requests(
        self,
        status: Optional[ApprovalStatus] = None,
        task_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[ApprovalRequest]:
        """Lists approval requests filtered by status or task."""
        query = "SELECT * FROM approval_requests WHERE 1=1"
        params: List[Any] = []

        if status:
            query += " AND status = ?"
            params.append(status.value)
        if task_id:
            query += " AND task_id = ?"
            params.append(task_id)

        query += " ORDER BY requested_at DESC LIMIT ?;"
        params.append(limit)

        with self.db.connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            return [self._row_to_approval(r) for r in rows]

    def resolve_approval_request(
        self,
        approval_id: str,
        approved: bool,
        decision_maker: str = "user",
        decision_reason: Optional[str] = None,
    ) -> Optional[ApprovalRequest]:
        """Atomically approves or rejects a pending approval request."""
        now = utc_now_iso()
        new_status = ApprovalStatus.APPROVED.value if approved else ApprovalStatus.REJECTED.value

        with self.db.connection() as conn:
            # Check expiry before resolving
            current = conn.execute("SELECT * FROM approval_requests WHERE id = ?;", (approval_id,)).fetchone()
            if not current:
                return None

            if current["status"] != "pending":
                return self._row_to_approval(current)

            expires_at = current["expires_at"]
            if expires_at and expires_at < now:
                conn.execute(
                    "UPDATE approval_requests SET status = 'expired', decision_at = ? WHERE id = ?;",
                    (now, approval_id),
                )
                return self.get_approval_request(approval_id)

            conn.execute(
                """
                UPDATE approval_requests SET
                    status = ?,
                    decision_at = ?,
                    decision_maker = ?,
                    decision_reason = ?
                WHERE id = ? AND status = 'pending';
                """,
                (new_status, now, decision_maker, decision_reason, approval_id),
            )

        return self.get_approval_request(approval_id)

    def consume_approval_request(
        self,
        approval_id: str,
        canonical_param_hash: str,
    ) -> Optional[ApprovalRequest]:
        """Atomically consumes an approved request once.

        Returns the consumed request if valid, or None if invalid, expired, or hash mismatch.
        """
        now = utc_now_iso()
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM approval_requests WHERE id = ?;", (approval_id,)).fetchone()
            if not row:
                return None

            # Must be in 'approved' status
            if row["status"] != "approved":
                return None

            # Check expiration
            expires_at = row["expires_at"]
            if expires_at and expires_at < now:
                conn.execute(
                    "UPDATE approval_requests SET status = 'expired' WHERE id = ?;",
                    (approval_id,),
                )
                return None

            # Check exact canonical hash match
            if row["canonical_param_hash"] != canonical_param_hash:
                return None

            # Atomic one-time consumption
            cursor = conn.execute(
                """
                UPDATE approval_requests SET
                    status = 'consumed',
                    consumed_at = ?
                WHERE id = ? AND status = 'approved';
                """,
                (now, approval_id),
            )

            if cursor.rowcount == 0:
                return None

        return self.get_approval_request(approval_id)

    # --------------------------------------------------------------------------
    # Action Event Auditing
    # --------------------------------------------------------------------------

    def record_action_event(self, event: ActionEvent) -> ActionEvent:
        """Records an action audit event tied to tool execution and governance."""
        now = event.timestamp or utc_now_iso()
        with self.db.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO action_events (
                    action_id, task_id, approval_id, event_type,
                    tool_name, action_type, target_resource,
                    parameter_fingerprint, policy_decision, risk_level,
                    result_summary, error_details, event_payload,
                    request_id, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    event.action_id,
                    event.task_id,
                    event.approval_id,
                    event.event_type,
                    event.tool_name,
                    event.action_type,
                    event.target_resource,
                    event.parameter_fingerprint,
                    event.policy_decision,
                    event.risk_level,
                    event.result_summary,
                    json.dumps(event.error_details) if event.error_details else None,
                    json.dumps(event.event_payload or {}),
                    event.request_id,
                    now,
                ),
            )
            event_id = cursor.lastrowid

        return ActionEvent(
            id=event_id,
            action_id=event.action_id,
            task_id=event.task_id,
            approval_id=event.approval_id,
            event_type=event.event_type,
            tool_name=event.tool_name,
            action_type=event.action_type,
            target_resource=event.target_resource,
            parameter_fingerprint=event.parameter_fingerprint,
            policy_decision=event.policy_decision,
            risk_level=event.risk_level,
            result_summary=event.result_summary,
            error_details=event.error_details,
            event_payload=event.event_payload,
            request_id=event.request_id,
            timestamp=now,
        )

    def list_action_events(
        self,
        task_id: Optional[str] = None,
        action_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[ActionEvent]:
        """Lists chronological action audit events."""
        query = "SELECT * FROM action_events WHERE 1=1"
        params: List[Any] = []
        if task_id:
            query += " AND task_id = ?"
            params.append(task_id)
        if action_id:
            query += " AND action_id = ?"
            params.append(action_id)
        query += " ORDER BY id DESC LIMIT ?;"
        params.append(limit)

        with self.db.connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            events = []
            for r in rows:
                try:
                    payload = json.loads(r["event_payload"] or "{}")
                except Exception:
                    payload = {}
                try:
                    err = json.loads(r["error_details"]) if r["error_details"] else None
                except Exception:
                    err = None
                events.append(
                    ActionEvent(
                        id=r["id"],
                        action_id=r["action_id"],
                        task_id=r["task_id"],
                        approval_id=r["approval_id"],
                        event_type=r["event_type"],
                        tool_name=r["tool_name"],
                        action_type=r["action_type"],
                        target_resource=r["target_resource"],
                        parameter_fingerprint=r["parameter_fingerprint"],
                        policy_decision=r["policy_decision"],
                        risk_level=r["risk_level"],
                        result_summary=r["result_summary"],
                        error_details=err,
                        event_payload=payload,
                        request_id=r["request_id"],
                        timestamp=r["timestamp"],
                    )
                )
            return events

    # --------------------------------------------------------------------------
    # Deserialization Helpers
    # --------------------------------------------------------------------------

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        def parse_json(val, default):
            if not val:
                return default
            try:
                return json.loads(val)
            except Exception:
                return default

        return Task(
            id=row["id"],
            conversation_id=row["conversation_id"],
            project_id=row["project_id"],
            task_type=row["task_type"],
            title=row["title"],
            objective=row["objective"],
            status=TaskStatus(row["status"]),
            priority=row["priority"],
            privacy_mode=row["privacy_mode"],
            input_data=parse_json(row["input_data"], {}),
            result_data=parse_json(row["result_data"], {}),
            error_details=parse_json(row["error_details"], None),
            request_id=row["request_id"],
            idempotency_key=row["idempotency_key"],
            attempt_count=row["attempt_count"],
            max_attempts=row["max_attempts"],
            worker_id=row["worker_id"],
            lease_expiry=row["lease_expiry"],
            heartbeat=row["heartbeat"],
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            cancelled_at=row["cancelled_at"],
        )

    def _row_to_approval(self, row: sqlite3.Row) -> ApprovalRequest:
        try:
            params = json.loads(row["parameters"] or "{}")
        except Exception:
            params = {}

        return ApprovalRequest(
            id=row["id"],
            task_id=row["task_id"],
            action_id=row["action_id"],
            tool_name=row["tool_name"],
            action_type=row["action_type"],
            target_resource=row["target_resource"],
            parameters=params,
            canonical_param_hash=row["canonical_param_hash"],
            risk_level=row["risk_level"],
            policy_reason=row["policy_reason"],
            status=ApprovalStatus(row["status"]),
            requested_at=row["requested_at"],
            expires_at=row["expires_at"],
            decision_at=row["decision_at"],
            decision_maker=row["decision_maker"],
            decision_reason=row["decision_reason"],
            consumed_at=row["consumed_at"],
        )
