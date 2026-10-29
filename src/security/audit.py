"""Audit logger for AIRA with sensitive data redaction."""

import re
from typing import Dict, Any, Optional
from src.memory.models import AuditLogRecord
from src.memory.repository import MemoryRepository

SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*['\"]?)([^'\";\s]{8,})(['\"]?)"),
    re.compile(r"(?i)(bearer\s+)([^'\";\s]{12,})"),
    re.compile(r"(?i)(password\s*[:=]\s*['\"]?)([^'\";\s]+)(['\"]?)"),
    re.compile(r"(?i)(secret\s*[:=]\s*['\"]?)([^'\";\s]+)(['\"]?)"),
    re.compile(r"sk-[a-zA-Z0-9_-]{20,}"),
]

def redact_sensitive_text(text: str) -> str:
    """Redacts sensitive tokens, API keys, and passwords from text."""
    if not isinstance(text, str):
        return str(text)

    redacted = text
    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub(r"\1***REDACTED***\3" if pattern.groups == 3 else "***REDACTED***", redacted)
    return redacted

def redact_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    redacted = {}
    for k, v in data.items():
        if any(secret_term in k.lower() for secret_term in ("key", "secret", "password", "token", "auth")):
            redacted[k] = "***REDACTED***"
        elif isinstance(v, str):
            redacted[k] = redact_sensitive_text(v)
        elif isinstance(v, dict):
            redacted[k] = redact_dict(v)
        else:
            redacted[k] = v
    return redacted

class AuditService:
    def __init__(self, repo: MemoryRepository):
        self.repo = repo

    def record_event(
        self,
        action_type: str,
        tool_name: Optional[str] = None,
        target_resource: Optional[str] = None,
        risk_level: str = "LOW",
        policy_decision: str = "ALLOW",
        reason: str = "",
        request_id: Optional[str] = None,
        user_approved: Optional[bool] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditLogRecord:
        safe_details = redact_dict(details or {})
        safe_resource = redact_sensitive_text(target_resource or "")
        safe_reason = redact_sensitive_text(reason)

        log = AuditLogRecord(
            request_id=request_id,
            action_type=action_type,
            tool_name=tool_name,
            target_resource=safe_resource,
            risk_level=risk_level,
            policy_decision=policy_decision,
            reason=safe_reason,
            user_approved=user_approved,
            details=safe_details,
        )
        return self.repo.log_audit(log)
