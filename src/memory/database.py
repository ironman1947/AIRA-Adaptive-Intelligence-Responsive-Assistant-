"""SQLite database connection and schema initialization for AIRA."""

import sqlite3
from pathlib import Path
from contextlib import contextmanager
from src.config import AIRA_DB_PATH

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS user_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL,
    source TEXT DEFAULT 'user_input',
    confidence REAL DEFAULT 1.0,
    date_observed TEXT NOT NULL,
    date_confirmed TEXT,
    user_approved INTEGER DEFAULT 1,
    is_sensitive INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    preference_key TEXT NOT NULL,
    preference_value TEXT NOT NULL,
    supporting_observations TEXT,
    confidence REAL DEFAULT 0.8,
    date_first_observed TEXT NOT NULL,
    date_last_confirmed TEXT,
    is_explicit INTEGER DEFAULT 0,
    user_approved INTEGER DEFAULT 0,
    is_temporary INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    purpose TEXT,
    tech_stack TEXT, -- JSON array
    repo_path TEXT,
    current_objectives TEXT, -- JSON array
    completed_milestones TEXT, -- JSON array
    known_bugs TEXT, -- JSON array
    open_issues TEXT, -- JSON array
    architectural_decisions TEXT, -- JSON array
    documentation TEXT,
    last_verified_state TEXT,
    next_steps TEXT, -- JSON array
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    title TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS session_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    project_id TEXT,
    objective TEXT,
    accomplished TEXT, -- JSON array
    unfinished TEXT, -- JSON array
    decisions_and_corrections TEXT, -- JSON array
    next_steps TEXT, -- JSON array
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS episodic_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    project_id TEXT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    event_type TEXT DEFAULT 'task_outcome',
    tags TEXT, -- JSON array
    importance REAL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS semantic_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_value TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT DEFAULT 'verified_interaction',
    verification_status TEXT DEFAULT 'verified',
    confidence REAL DEFAULT 1.0,
    project_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS procedural_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    applicability TEXT NOT NULL,
    prerequisites TEXT, -- JSON array
    steps TEXT NOT NULL, -- JSON array
    validation_status TEXT DEFAULT 'validated',
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    project_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS working_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL, -- JSON
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    helpful INTEGER NOT NULL,
    rating INTEGER,
    category TEXT NOT NULL,
    user_explanation TEXT,
    model_used TEXT,
    tools_triggered INTEGER DEFAULT 0,
    prompt TEXT,
    response TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT,
    action_type TEXT NOT NULL,
    tool_name TEXT,
    target_resource TEXT,
    risk_level TEXT DEFAULT 'LOW',
    policy_decision TEXT DEFAULT 'ALLOW',
    reason TEXT,
    user_approved INTEGER,
    details TEXT, -- JSON
    timestamp TEXT NOT NULL
);

-- RAG Document index tables
CREATE TABLE IF NOT EXISTS rag_documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    project_id TEXT,
    privacy_level TEXT DEFAULT 'standard',
    chunk_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rag_chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    page_or_section TEXT,
    metadata TEXT, -- JSON
    embedding_blob BLOB,
    created_at TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES rag_documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT DEFAULT 'default_user',
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    engine TEXT,
    model TEXT,
    created_at TEXT NOT NULL,
    metadata TEXT DEFAULT '{}',
    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

-- Indexes for fast retrieval
CREATE INDEX IF NOT EXISTS idx_episodic_project ON episodic_memory(project_id);
CREATE INDEX IF NOT EXISTS idx_semantic_subject ON semantic_memory(subject);
CREATE INDEX IF NOT EXISTS idx_semantic_project ON semantic_memory(project_id);
CREATE INDEX IF NOT EXISTS idx_procedural_app ON procedural_memory(applicability);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc ON rag_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_audit_req ON audit_logs(request_id);
CREATE INDEX IF NOT EXISTS idx_conv_messages_session ON conversation_messages(session_id, id);
CREATE INDEX IF NOT EXISTS idx_conversations_user_updated ON conversations(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id ASC);
"""

class DatabaseManager:
    def __init__(self, db_path: str = AIRA_DB_PATH):
        self.db_path = db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize_schema()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    @contextmanager
    def connection(self):
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize_schema(self):
        with self.connection() as conn:
            conn.executescript(SCHEMA_SQL)
        from src.memory.migrations.runner import MigrationRunner
        runner = MigrationRunner(self.db_path)
        runner.apply_pending()

# Global database manager instance
_db_manager = None

def get_db_manager(db_path: str = AIRA_DB_PATH) -> DatabaseManager:
    global _db_manager
    if _db_manager is None or _db_manager.db_path != db_path:
        _db_manager = DatabaseManager(db_path)
    return _db_manager
