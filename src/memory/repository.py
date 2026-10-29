"""Memory repository providing clean CRUD, querying, review, and export abstractions for AIRA."""

import json
from datetime import datetime
from typing import List, Optional, Dict, Any
from src.memory.database import DatabaseManager, get_db_manager
from src.memory.models import (
    ConversationMessage,
    UserProfileItem,
    UserPreference,
    ProjectWorkspace,
    EpisodicMemory,
    SemanticMemory,
    ProceduralMemory,
    WorkingMemoryItem,
    SessionSummary,
    FeedbackRecord,
    AuditLogRecord,
)

class MemoryRepository:
    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or get_db_manager()

    # --------------------------------------------------------------------------
    # User Profile
    # --------------------------------------------------------------------------
    def get_profile(self) -> Dict[str, UserProfileItem]:
        with self.db.connection() as conn:
            rows = conn.execute("SELECT * FROM user_profile;").fetchall()
            profile = {}
            for r in rows:
                item = UserProfileItem(
                    id=r["id"],
                    key=r["key"],
                    value=r["value"],
                    source=r["source"],
                    confidence=r["confidence"],
                    date_observed=r["date_observed"],
                    date_confirmed=r["date_confirmed"],
                    user_approved=bool(r["user_approved"]),
                    is_sensitive=bool(r["is_sensitive"]),
                )
                profile[item.key] = item
            return profile

    def set_profile_item(self, item: UserProfileItem) -> UserProfileItem:
        with self.db.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO user_profile (key, value, source, confidence, date_observed, date_confirmed, user_approved, is_sensitive)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    source = excluded.source,
                    confidence = excluded.confidence,
                    date_confirmed = excluded.date_confirmed,
                    user_approved = excluded.user_approved,
                    is_sensitive = excluded.is_sensitive;
                """,
                (
                    item.key,
                    item.value,
                    item.source,
                    item.confidence,
                    item.date_observed,
                    item.date_confirmed,
                    int(item.user_approved),
                    int(item.is_sensitive),
                ),
            )
            if not item.id:
                item.id = cursor.lastrowid
            return item

    def delete_profile_item(self, key: str) -> bool:
        with self.db.connection() as conn:
            cursor = conn.execute("DELETE FROM user_profile WHERE key = ?;", (key,))
            return cursor.rowcount > 0

    # --------------------------------------------------------------------------
    # User Preferences (Evidence-Based Personalization)
    # --------------------------------------------------------------------------
    def list_preferences(self, approved_only: bool = False) -> List[UserPreference]:
        query = "SELECT * FROM user_preferences"
        params = ()
        if approved_only:
            query += " WHERE user_approved = 1"
        query += " ORDER BY id DESC;"

        with self.db.connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [
                UserPreference(
                    id=r["id"],
                    preference_key=r["preference_key"],
                    preference_value=r["preference_value"],
                    supporting_observations=r["supporting_observations"] or "",
                    confidence=r["confidence"],
                    date_first_observed=r["date_first_observed"],
                    date_last_confirmed=r["date_last_confirmed"],
                    is_explicit=bool(r["is_explicit"]),
                    user_approved=bool(r["user_approved"]),
                    is_temporary=bool(r["is_temporary"]),
                )
                for r in rows
            ]

    def add_preference(self, pref: UserPreference) -> UserPreference:
        with self.db.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO user_preferences 
                (preference_key, preference_value, supporting_observations, confidence, date_first_observed, date_last_confirmed, is_explicit, user_approved, is_temporary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    pref.preference_key,
                    pref.preference_value,
                    pref.supporting_observations,
                    pref.confidence,
                    pref.date_first_observed,
                    pref.date_last_confirmed,
                    int(pref.is_explicit),
                    int(pref.user_approved),
                    int(pref.is_temporary),
                ),
            )
            pref.id = cursor.lastrowid
            return pref

    def set_preference_approval(self, pref_id: int, approved: bool) -> bool:
        with self.db.connection() as conn:
            cursor = conn.execute(
                "UPDATE user_preferences SET user_approved = ? WHERE id = ?;",
                (1 if approved else 0, pref_id),
            )
            return cursor.rowcount > 0

    def delete_preference(self, pref_id: int) -> bool:
        with self.db.connection() as conn:
            cursor = conn.execute("DELETE FROM user_preferences WHERE id = ?;", (pref_id,))
            return cursor.rowcount > 0

    # --------------------------------------------------------------------------
    # Projects
    # --------------------------------------------------------------------------
    def list_projects(self) -> List[ProjectWorkspace]:
        with self.db.connection() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC;").fetchall()
            return [
                ProjectWorkspace(
                    id=r["id"],
                    name=r["name"],
                    purpose=r["purpose"] or "",
                    tech_stack=json.loads(r["tech_stack"] or "[]"),
                    repo_path=r["repo_path"],
                    current_objectives=json.loads(r["current_objectives"] or "[]"),
                    completed_milestones=json.loads(r["completed_milestones"] or "[]"),
                    known_bugs=json.loads(r["known_bugs"] or "[]"),
                    open_issues=json.loads(r["open_issues"] or "[]"),
                    architectural_decisions=json.loads(r["architectural_decisions"] or "[]"),
                    documentation=r["documentation"] or "",
                    last_verified_state=r["last_verified_state"] or "",
                    next_steps=json.loads(r["next_steps"] or "[]"),
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ]

    def get_project(self, project_id: str) -> Optional[ProjectWorkspace]:
        with self.db.connection() as conn:
            r = conn.execute("SELECT * FROM projects WHERE id = ?;", (project_id,)).fetchone()
            if not r:
                return None
            return ProjectWorkspace(
                id=r["id"],
                name=r["name"],
                purpose=r["purpose"] or "",
                tech_stack=json.loads(r["tech_stack"] or "[]"),
                repo_path=r["repo_path"],
                current_objectives=json.loads(r["current_objectives"] or "[]"),
                completed_milestones=json.loads(r["completed_milestones"] or "[]"),
                known_bugs=json.loads(r["known_bugs"] or "[]"),
                open_issues=json.loads(r["open_issues"] or "[]"),
                architectural_decisions=json.loads(r["architectural_decisions"] or "[]"),
                documentation=r["documentation"] or "",
                last_verified_state=r["last_verified_state"] or "",
                next_steps=json.loads(r["next_steps"] or "[]"),
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )

    def save_project(self, proj: ProjectWorkspace) -> ProjectWorkspace:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO projects (
                    id, name, purpose, tech_stack, repo_path, current_objectives, 
                    completed_milestones, known_bugs, open_issues, architectural_decisions,
                    documentation, last_verified_state, next_steps, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    purpose = excluded.purpose,
                    tech_stack = excluded.tech_stack,
                    repo_path = excluded.repo_path,
                    current_objectives = excluded.current_objectives,
                    completed_milestones = excluded.completed_milestones,
                    known_bugs = excluded.known_bugs,
                    open_issues = excluded.open_issues,
                    architectural_decisions = excluded.architectural_decisions,
                    documentation = excluded.documentation,
                    last_verified_state = excluded.last_verified_state,
                    next_steps = excluded.next_steps,
                    updated_at = excluded.updated_at;
                """,
                (
                    proj.id,
                    proj.name,
                    proj.purpose,
                    json.dumps(proj.tech_stack),
                    proj.repo_path,
                    json.dumps(proj.current_objectives),
                    json.dumps(proj.completed_milestones),
                    json.dumps(proj.known_bugs),
                    json.dumps(proj.open_issues),
                    json.dumps(proj.architectural_decisions),
                    proj.documentation,
                    proj.last_verified_state,
                    json.dumps(proj.next_steps),
                    proj.created_at,
                    proj.updated_at,
                ),
            )
            return proj

    def delete_project(self, project_id: str) -> bool:
        with self.db.connection() as conn:
            cursor = conn.execute("DELETE FROM projects WHERE id = ?;", (project_id,))
            return cursor.rowcount > 0

    # --------------------------------------------------------------------------
    # Episodic Memory
    # --------------------------------------------------------------------------
    def add_episodic(self, item: EpisodicMemory) -> EpisodicMemory:
        with self.db.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO episodic_memory (session_id, project_id, title, content, event_type, tags, importance, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    item.session_id,
                    item.project_id,
                    item.title,
                    item.content,
                    item.event_type,
                    json.dumps(item.tags),
                    item.importance,
                    item.created_at,
                ),
            )
            item.id = cursor.lastrowid
            return item

    def get_episodic_memories(self, project_id: Optional[str] = None, limit: int = 20) -> List[EpisodicMemory]:
        query = "SELECT * FROM episodic_memory"
        params: List[Any] = []
        if project_id:
            query += " WHERE project_id = ?"
            params.append(project_id)
        query += " ORDER BY id DESC LIMIT ?;"
        params.append(limit)

        with self.db.connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            return [
                EpisodicMemory(
                    id=r["id"],
                    session_id=r["session_id"],
                    project_id=r["project_id"],
                    title=r["title"],
                    content=r["content"],
                    event_type=r["event_type"],
                    tags=json.loads(r["tags"] or "[]"),
                    importance=r["importance"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    def delete_episodic(self, item_id: int) -> bool:
        with self.db.connection() as conn:
            cursor = conn.execute("DELETE FROM episodic_memory WHERE id = ?;", (item_id,))
            return cursor.rowcount > 0

    # --------------------------------------------------------------------------
    # Semantic Memory
    # --------------------------------------------------------------------------
    def add_semantic(self, item: SemanticMemory) -> SemanticMemory:
        with self.db.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO semantic_memory (subject, predicate, object_value, content, source, verification_status, confidence, project_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    item.subject,
                    item.predicate,
                    item.object_value,
                    item.content,
                    item.source,
                    item.verification_status,
                    item.confidence,
                    item.project_id,
                    item.created_at,
                ),
            )
            item.id = cursor.lastrowid
            return item

    def get_semantic_memories(self, project_id: Optional[str] = None, limit: int = 50) -> List[SemanticMemory]:
        query = "SELECT * FROM semantic_memory"
        params: List[Any] = []
        if project_id:
            query += " WHERE project_id = ? OR project_id IS NULL"
            params.append(project_id)
        query += " ORDER BY id DESC LIMIT ?;"
        params.append(limit)

        with self.db.connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            return [
                SemanticMemory(
                    id=r["id"],
                    subject=r["subject"],
                    predicate=r["predicate"],
                    object_value=r["object_value"],
                    content=r["content"],
                    source=r["source"],
                    verification_status=r["verification_status"],
                    confidence=r["confidence"],
                    project_id=r["project_id"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    def delete_semantic(self, item_id: int) -> bool:
        with self.db.connection() as conn:
            cursor = conn.execute("DELETE FROM semantic_memory WHERE id = ?;", (item_id,))
            return cursor.rowcount > 0

    # --------------------------------------------------------------------------
    # Procedural Memory
    # --------------------------------------------------------------------------
    def add_procedural(self, item: ProceduralMemory) -> ProceduralMemory:
        with self.db.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO procedural_memory (title, applicability, prerequisites, steps, validation_status, success_count, fail_count, project_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    item.title,
                    item.applicability,
                    json.dumps(item.prerequisites),
                    json.dumps(item.steps),
                    item.validation_status,
                    item.success_count,
                    item.fail_count,
                    item.project_id,
                    item.created_at,
                ),
            )
            item.id = cursor.lastrowid
            return item

    def get_procedural_memories(self, project_id: Optional[str] = None, validated_only: bool = False) -> List[ProceduralMemory]:
        query = "SELECT * FROM procedural_memory"
        clauses = []
        params: List[Any] = []
        if validated_only:
            clauses.append("validation_status = 'validated'")
        if project_id:
            clauses.append("(project_id = ? OR project_id IS NULL)")
            params.append(project_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY success_count DESC, id DESC;"

        with self.db.connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            return [
                ProceduralMemory(
                    id=r["id"],
                    title=r["title"],
                    applicability=r["applicability"],
                    prerequisites=json.loads(r["prerequisites"] or "[]"),
                    steps=json.loads(r["steps"] or "[]"),
                    validation_status=r["validation_status"],
                    success_count=r["success_count"],
                    fail_count=r["fail_count"],
                    project_id=r["project_id"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    def record_procedure_result(self, proc_id: int, success: bool) -> bool:
        col = "success_count" if success else "fail_count"
        with self.db.connection() as conn:
            cursor = conn.execute(f"UPDATE procedural_memory SET {col} = {col} + 1 WHERE id = ?;", (proc_id,))
            return cursor.rowcount > 0

    def delete_procedural(self, item_id: int) -> bool:
        with self.db.connection() as conn:
            cursor = conn.execute("DELETE FROM procedural_memory WHERE id = ?;", (item_id,))
            return cursor.rowcount > 0

    # --------------------------------------------------------------------------
    # Working Memory
    # --------------------------------------------------------------------------
    def set_working_memory(self, session_id: str, key: str, value: Any) -> None:
        val_str = json.dumps(value)
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO working_memory (session_id, key, value, created_at)
                VALUES (?, ?, ?, datetime('now'));
                """,
                (session_id, key, val_str),
            )

    def get_working_memory(self, session_id: str) -> Dict[str, Any]:
        with self.db.connection() as conn:
            rows = conn.execute("SELECT key, value FROM working_memory WHERE session_id = ?;", (session_id,)).fetchall()
            result = {}
            for r in rows:
                try:
                    result[r["key"]] = json.loads(r["value"])
                except Exception:
                    result[r["key"]] = r["value"]
            return result

    def clear_working_memory(self, session_id: str) -> None:
        with self.db.connection() as conn:
            conn.execute("DELETE FROM working_memory WHERE session_id = ?;", (session_id,))

    # --------------------------------------------------------------------------
    # Session Summaries
    # --------------------------------------------------------------------------
    def save_session_summary(self, summary: SessionSummary) -> SessionSummary:
        with self.db.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO session_summaries (session_id, project_id, objective, accomplished, unfinished, decisions_and_corrections, next_steps, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    summary.session_id,
                    summary.project_id,
                    summary.objective,
                    json.dumps(summary.accomplished),
                    json.dumps(summary.unfinished),
                    json.dumps(summary.decisions_and_corrections),
                    json.dumps(summary.next_steps),
                    summary.created_at,
                ),
            )
            summary.id = cursor.lastrowid
            return summary

    def get_latest_session_summary(self, project_id: Optional[str] = None) -> Optional[SessionSummary]:
        query = "SELECT * FROM session_summaries"
        params = ()
        if project_id:
            query += " WHERE project_id = ?"
            params = (project_id,)
        query += " ORDER BY id DESC LIMIT 1;"

        with self.db.connection() as conn:
            r = conn.execute(query, params).fetchone()
            if not r:
                return None
            return SessionSummary(
                id=r["id"],
                session_id=r["session_id"],
                project_id=r["project_id"],
                objective=r["objective"] or "",
                accomplished=json.loads(r["accomplished"] or "[]"),
                unfinished=json.loads(r["unfinished"] or "[]"),
                decisions_and_corrections=json.loads(r["decisions_and_corrections"] or "[]"),
                next_steps=json.loads(r["next_steps"] or "[]"),
                created_at=r["created_at"],
            )

    # --------------------------------------------------------------------------
    # Feedback & Evaluation
    # --------------------------------------------------------------------------
    def record_feedback(self, fb: FeedbackRecord) -> FeedbackRecord:
        with self.db.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO feedback (request_id, helpful, rating, category, user_explanation, model_used, tools_triggered, prompt, response, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    fb.request_id,
                    1 if fb.helpful else 0,
                    fb.rating,
                    fb.category,
                    fb.user_explanation,
                    fb.model_used,
                    1 if fb.tools_triggered else 0,
                    fb.prompt,
                    fb.response,
                    fb.created_at,
                ),
            )
            fb.id = cursor.lastrowid
            return fb

    def list_feedback(self, limit: int = 50) -> List[FeedbackRecord]:
        with self.db.connection() as conn:
            rows = conn.execute("SELECT * FROM feedback ORDER BY id DESC LIMIT ?;", (limit,)).fetchall()
            return [
                FeedbackRecord(
                    id=r["id"],
                    request_id=r["request_id"],
                    helpful=bool(r["helpful"]),
                    rating=r["rating"],
                    category=r["category"],
                    user_explanation=r["user_explanation"],
                    model_used=r["model_used"],
                    tools_triggered=bool(r["tools_triggered"]),
                    prompt=r["prompt"],
                    response=r["response"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    # --------------------------------------------------------------------------
    # Audit Logs
    # --------------------------------------------------------------------------
    def log_audit(self, log: AuditLogRecord) -> AuditLogRecord:
        with self.db.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO audit_logs (request_id, action_type, tool_name, target_resource, risk_level, policy_decision, reason, user_approved, details, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    log.request_id,
                    log.action_type,
                    log.tool_name,
                    log.target_resource,
                    log.risk_level,
                    log.policy_decision,
                    log.reason,
                    int(log.user_approved) if log.user_approved is not None else None,
                    json.dumps(log.details),
                    log.timestamp,
                ),
            )
            log.id = cursor.lastrowid
            return log

    def list_audit_logs(self, limit: int = 100) -> List[AuditLogRecord]:
        with self.db.connection() as conn:
            rows = conn.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?;", (limit,)).fetchall()
            return [
                AuditLogRecord(
                    id=r["id"],
                    request_id=r["request_id"],
                    action_type=r["action_type"],
                    tool_name=r["tool_name"],
                    target_resource=r["target_resource"],
                    risk_level=r["risk_level"],
                    policy_decision=r["policy_decision"],
                    reason=r["reason"],
                    user_approved=bool(r["user_approved"]) if r["user_approved"] is not None else None,
                    details=json.loads(r["details"] or "{}"),
                    timestamp=r["timestamp"],
                )
                for r in rows
            ]

    # --------------------------------------------------------------------------
    # Export and Clear
    # --------------------------------------------------------------------------
    def export_all_memories(self) -> Dict[str, Any]:
        return {
            "user_profile": {k: v.model_dump() for k, v in self.get_profile().items()},
            "preferences": [p.model_dump() for p in self.list_preferences()],
            "projects": [p.model_dump() for p in self.list_projects()],
            "episodic_memory": [e.model_dump() for e in self.get_episodic_memories(limit=500)],
            "semantic_memory": [s.model_dump() for s in self.get_semantic_memories(limit=500)],
            "procedural_memory": [p.model_dump() for p in self.get_procedural_memories()],
        }

    def clear_memory_category(self, category: str) -> bool:
        valid_tables = {
            "episodic": "episodic_memory",
            "semantic": "semantic_memory",
            "procedural": "procedural_memory",
            "preferences": "user_preferences",
            "feedback": "feedback",
            "audit_logs": "audit_logs",
            "messages": "conversation_messages",
        }
        if category not in valid_tables:
            return False
        tbl = valid_tables[category]
        with self.db.connection() as conn:
            conn.execute(f"DELETE FROM {tbl};")
            return True

    # --------------------------------------------------------------------------
    # Conversation Messages (Chat History Continuity)
    # --------------------------------------------------------------------------
    def add_conversation_message(self, session_id: str, role: str, content: str) -> ConversationMessage:
        with self.db.connection() as conn:
            now = datetime.now().isoformat()
            cursor = conn.execute(
                "INSERT INTO conversation_messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?);",
                (session_id, role, content, now),
            )
            return ConversationMessage(
                id=cursor.lastrowid,
                session_id=session_id,
                role=role,
                content=content,
                created_at=now,
            )

    def get_conversation_history(self, session_id: str, limit: int = 20) -> List[ConversationMessage]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM (
                    SELECT * FROM conversation_messages
                    WHERE session_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                ) ORDER BY id ASC;
                """,
                (session_id, limit),
            ).fetchall()
            return [
                ConversationMessage(
                    id=r["id"],
                    session_id=r["session_id"],
                    role=r["role"],
                    content=r["content"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    def clear_conversation_history(self, session_id: Optional[str] = None) -> bool:
        with self.db.connection() as conn:
            if session_id:
                cursor = conn.execute("DELETE FROM conversation_messages WHERE session_id = ?;", (session_id,))
            else:
                cursor = conn.execute("DELETE FROM conversation_messages;")
            return cursor.rowcount > 0
