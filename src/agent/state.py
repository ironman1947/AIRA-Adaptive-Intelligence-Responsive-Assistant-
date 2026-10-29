"""AIRA Runtime Session and Execution State Tracking."""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime

@dataclass
class AgentSessionState:
    session_id: str
    project_id: Optional[str] = None
    privacy_mode: str = "standard"  # standard | local_only
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    interaction_count: int = 0
    active_plan: List[str] = field(default_factory=list)
    pending_approvals: List[Dict[str, Any]] = field(default_factory=list)
    recent_tools_called: List[str] = field(default_factory=list)
    last_error: Optional[str] = None

# Active session cache
_ACTIVE_SESSIONS: Dict[str, AgentSessionState] = {}

def get_or_create_session(session_id: str, project_id: Optional[str] = None) -> AgentSessionState:
    if session_id not in _ACTIVE_SESSIONS:
        _ACTIVE_SESSIONS[session_id] = AgentSessionState(
            session_id=session_id,
            project_id=project_id,
        )
    elif project_id:
        _ACTIVE_SESSIONS[session_id].project_id = project_id
    return _ACTIVE_SESSIONS[session_id]
