-- Migration 001: Tasks, Task Events, Approval Requests, and Action Events

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    project_id TEXT,
    task_type TEXT NOT NULL DEFAULT 'standard',
    title TEXT NOT NULL,
    objective TEXT,
    status TEXT NOT NULL DEFAULT 'QUEUED' CHECK (status IN (
        'QUEUED',
        'RUNNING',
        'COMPLETED',
        'FAILED',
        'AWAITING_APPROVAL',
        'CANCEL_REQUESTED',
        'CANCELLED',
        'NEEDS_RECONCILIATION'
    )),
    priority INTEGER NOT NULL DEFAULT 5,
    privacy_mode TEXT NOT NULL DEFAULT 'standard' CHECK (privacy_mode IN ('standard', 'local_only')),
    input_data TEXT DEFAULT '{}',
    result_data TEXT DEFAULT '{}',
    error_details TEXT,
    request_id TEXT,
    idempotency_key TEXT UNIQUE,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    worker_id TEXT,
    lease_expiry TEXT,
    heartbeat TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    cancelled_at TEXT,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE SET NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    previous_status TEXT,
    new_status TEXT,
    actor_type TEXT NOT NULL DEFAULT 'system',
    actor_id TEXT,
    event_message TEXT,
    event_payload TEXT DEFAULT '{}',
    request_id TEXT,
    timestamp TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS approval_requests (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    action_id TEXT,
    tool_name TEXT NOT NULL,
    action_type TEXT NOT NULL,
    target_resource TEXT,
    parameters TEXT DEFAULT '{}',
    canonical_param_hash TEXT NOT NULL,
    risk_level TEXT NOT NULL DEFAULT 'HIGH',
    policy_reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending',
        'approved',
        'rejected',
        'expired',
        'consumed'
    )),
    requested_at TEXT NOT NULL,
    expires_at TEXT,
    decision_at TEXT,
    decision_maker TEXT,
    decision_reason TEXT,
    consumed_at TEXT,
    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS action_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id TEXT NOT NULL,
    task_id TEXT,
    approval_id TEXT,
    event_type TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    action_type TEXT NOT NULL,
    target_resource TEXT,
    parameter_fingerprint TEXT,
    policy_decision TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    result_summary TEXT,
    error_details TEXT,
    event_payload TEXT DEFAULT '{}',
    request_id TEXT,
    timestamp TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE SET NULL,
    FOREIGN KEY(approval_id) REFERENCES approval_requests(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, priority DESC, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_tasks_conversation ON tasks(conversation_id);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_idempotency ON tasks(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id, id ASC);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approval_requests(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_approvals_task ON approval_requests(task_id);
CREATE INDEX IF NOT EXISTS idx_action_events_task ON action_events(task_id);
CREATE INDEX IF NOT EXISTS idx_action_events_approval ON action_events(approval_id);
CREATE INDEX IF NOT EXISTS idx_action_events_action ON action_events(action_id);
