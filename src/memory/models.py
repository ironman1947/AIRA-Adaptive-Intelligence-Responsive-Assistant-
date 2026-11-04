"""Data models for AIRA persistent memory, user profile, projects, and feedback."""

from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class Conversation(BaseModel):
    id: str
    user_id: Optional[str] = "default_user"
    title: str = "New Conversation"
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = Field(default_factory=dict)

class Message(BaseModel):
    id: Optional[int] = None
    conversation_id: str
    role: str  # 'user' | 'assistant' | 'system'
    content: str
    engine: Optional[str] = None
    model: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ConversationMessage(BaseModel):
    id: Optional[int] = None
    session_id: str
    role: str  # 'user' | 'assistant' | 'system'
    content: str
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

class UserProfileItem(BaseModel):
    id: Optional[int] = None
    key: str
    value: str
    source: str = "user_input"
    confidence: float = 1.0
    date_observed: str = Field(default_factory=lambda: datetime.now().isoformat())
    date_confirmed: Optional[str] = None
    user_approved: bool = True
    is_sensitive: bool = False

class UserPreference(BaseModel):
    id: Optional[int] = None
    preference_key: str
    preference_value: str
    supporting_observations: str = ""
    confidence: float = 0.8
    date_first_observed: str = Field(default_factory=lambda: datetime.now().isoformat())
    date_last_confirmed: Optional[str] = None
    is_explicit: bool = False
    user_approved: bool = False
    is_temporary: bool = False

class ProjectWorkspace(BaseModel):
    id: str
    name: str
    purpose: str = ""
    tech_stack: List[str] = Field(default_factory=list)
    repo_path: Optional[str] = None
    current_objectives: List[str] = Field(default_factory=list)
    completed_milestones: List[str] = Field(default_factory=list)
    known_bugs: List[str] = Field(default_factory=list)
    open_issues: List[str] = Field(default_factory=list)
    architectural_decisions: List[str] = Field(default_factory=list)
    documentation: str = ""
    last_verified_state: str = ""
    next_steps: List[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

class EpisodicMemory(BaseModel):
    id: Optional[int] = None
    session_id: Optional[str] = None
    project_id: Optional[str] = None
    title: str
    content: str
    event_type: str = "task_outcome"  # task_outcome, decision, milestone, feedback, debugging
    tags: List[str] = Field(default_factory=list)
    importance: float = 0.5
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

class SemanticMemory(BaseModel):
    id: Optional[int] = None
    subject: str
    predicate: str
    object_value: str
    content: str
    source: str = "verified_interaction"
    verification_status: str = "verified"  # verified, proposed, unverified
    confidence: float = 1.0
    project_id: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

class ProceduralMemory(BaseModel):
    id: Optional[int] = None
    title: str
    applicability: str
    prerequisites: List[str] = Field(default_factory=list)
    steps: List[str] = Field(default_factory=list)
    validation_status: str = "validated"  # draft, validated, deprecated
    success_count: int = 0
    fail_count: int = 0
    project_id: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

class WorkingMemoryItem(BaseModel):
    id: Optional[int] = None
    session_id: str
    key: str
    value: Any
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

class SessionSummary(BaseModel):
    id: Optional[int] = None
    session_id: str
    project_id: Optional[str] = None
    objective: str = ""
    accomplished: List[str] = Field(default_factory=list)
    unfinished: List[str] = Field(default_factory=list)
    decisions_and_corrections: List[str] = Field(default_factory=list)
    next_steps: List[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

class FeedbackRecord(BaseModel):
    id: Optional[int] = None
    request_id: str
    helpful: bool
    rating: Optional[int] = None
    category: str = "helpful"  # helpful, not_helpful, incorrect_fact, incorrect_reasoning, tool_failure, irrelevant_retrieval, incorrect_code, user_correction
    user_explanation: Optional[str] = None
    model_used: Optional[str] = None
    tools_triggered: bool = False
    prompt: Optional[str] = None
    response: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

class AuditLogRecord(BaseModel):
    id: Optional[int] = None
    request_id: Optional[str] = None
    action_type: str
    tool_name: Optional[str] = None
    target_resource: Optional[str] = None
    risk_level: str = "LOW"  # LOW, MEDIUM, HIGH, CRITICAL
    policy_decision: str = "ALLOW"  # ALLOW, REQUIRE_APPROVAL, DENY
    reason: str = ""
    user_approved: Optional[bool] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
