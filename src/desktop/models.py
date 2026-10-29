"""Data models and action categories for AIRA Desktop Control Subsystem."""

import time
from enum import Enum
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field


class ActionCategory(str, Enum):
    """Explicit permission and risk tiers for desktop operations."""
    READ_ONLY = "read_only"
    PREVIEW = "preview"
    MODIFY = "modify"
    DESTRUCTIVE = "destructive"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"

    @property
    def requires_explicit_approval(self) -> bool:
        """Non-negotiable rule: Any action categorized as MODIFY, DESTRUCTIVE,
        or EXTERNAL_SIDE_EFFECT MUST receive user confirmation before execution."""
        return self in (
            ActionCategory.MODIFY,
            ActionCategory.DESTRUCTIVE,
            ActionCategory.EXTERNAL_SIDE_EFFECT,
        )


@dataclass
class DesktopActionPlan:
    """Structured plan proposed before any computer modification is performed."""
    plan_id: str
    tool_name: str
    category: ActionCategory
    description: str
    affected_resource: str
    diff: Optional[str] = None
    command: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending_approval"  # pending_approval, approved, rejected, executed, failed
    created_at: float = field(default_factory=time.time)
    executed_at: Optional[float] = None
    execution_result: Optional[Dict[str, Any]] = None
    verified_outcome: Optional[str] = None
    rejection_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "tool_name": self.tool_name,
            "category": self.category.value,
            "requires_approval": self.category.requires_explicit_approval,
            "description": self.description,
            "affected_resource": self.affected_resource,
            "diff": self.diff,
            "command": self.command,
            "parameters": self.parameters,
            "status": self.status,
            "created_at": self.created_at,
            "executed_at": self.executed_at,
            "execution_result": self.execution_result,
            "verified_outcome": self.verified_outcome,
            "rejection_reason": self.rejection_reason,
        }
