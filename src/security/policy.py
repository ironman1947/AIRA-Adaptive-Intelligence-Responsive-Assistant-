"""AIRA Policy Decision Layer.

Enforces security, permissions, privacy boundaries, and human oversight
prior to executing any tool or operation.
"""

import json
import hashlib
from typing import Dict, Any, Optional, Tuple, List
from pathlib import Path
from enum import Enum
from datetime import datetime, timezone, timedelta

from src.security.audit import AuditService
from src.security.network import validate_url_security


class ActionRisk(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PolicyDecision(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    DENY = "DENY"


def compute_canonical_parameter_hash(parameters: Dict[str, Any]) -> str:
    """Computes a deterministic SHA-256 fingerprint of action parameters.

    Ignores non-semantic variations by sorting keys and removing extraneous whitespace.
    """
    clean_params = parameters or {}
    # Exclude internal metadata keys if present
    normalized = {
        k: v for k, v in clean_params.items()
        if not k.startswith("_") and k not in ("approval_id", "request_id")
    }
    dumped = json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


class PolicyDecisionEngine:
    def __init__(self, audit_service: AuditService, task_repo: Optional[Any] = None):
        self.audit = audit_service
        self.task_repo = task_repo
        self.pending_approvals: Dict[str, Dict[str, Any]] = {}

    def set_task_repository(self, task_repo: Any) -> None:
        """Configures or updates the backing persistent task repository."""
        self.task_repo = task_repo

    def evaluate_action(
        self,
        action_type: str,
        tool_name: str,
        parameters: Dict[str, Any],
        request_id: Optional[str] = None,
        privacy_mode: str = "standard",
        authorized_root: Optional[str] = None,
        pre_approved: bool = False,
        approval_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Tuple[str, str, str]:
        """Evaluates an action against AIRA's security constitution and policies.

        Returns:
            (decision, risk_level, reason)
            where decision is one of 'ALLOW', 'REQUIRE_APPROVAL', 'DENY'.
        """
        # Check if an explicit approval_id was passed in parameters
        active_approval_id = approval_id or parameters.get("approval_id")

        # 1. Deny path traversal or access outside authorized workspace
        if "file_path" in parameters or "path" in parameters:
            target_path_str = parameters.get("file_path") or parameters.get("path")
            if target_path_str and authorized_root:
                try:
                    target_path = Path(target_path_str).resolve()
                    auth_root = Path(authorized_root).resolve()
                    if not target_path.is_relative_to(auth_root):
                        reason = f"Path '{target_path_str}' is outside authorized workspace '{authorized_root}'."
                        self.audit.record_event(
                            action_type=action_type,
                            tool_name=tool_name,
                            target_resource=target_path_str,
                            risk_level=ActionRisk.CRITICAL.value,
                            policy_decision=PolicyDecision.DENY.value,
                            reason=reason,
                            request_id=request_id,
                            details=parameters,
                        )
                        return PolicyDecision.DENY.value, ActionRisk.CRITICAL.value, reason
                except Exception as e:
                    reason = f"Invalid file path syntax: {e}"
                    return PolicyDecision.DENY.value, ActionRisk.CRITICAL.value, reason

        # 2. Check Network Safety for URL fetching and URL opening
        if tool_name in ("fetch_webpage", "desktop_open_url", "open_url") and "url" in parameters:
            url = parameters.get("url", "")
            is_safe, error_msg = validate_url_security(url)
            if not is_safe:
                reason = f"URL blocked by SSRF/Network Safety Policy: {error_msg}"
                self.audit.record_event(
                    action_type=action_type,
                    tool_name=tool_name,
                    target_resource=url,
                    risk_level=ActionRisk.HIGH.value,
                    policy_decision=PolicyDecision.DENY.value,
                    reason=reason,
                    request_id=request_id,
                    details=parameters,
                )
                return PolicyDecision.DENY.value, ActionRisk.HIGH.value, reason

        # 3. Privacy Policy Enforcement: Local-only mode
        if privacy_mode == "local_only":
            if action_type in ("CLOUD_ROUTING", "EXTERNAL_API") or tool_name in ("cloud_llm", "search_web", "fetch_webpage"):
                reason = "Cloud escalation or external web access blocked: User has enforced Local-Only privacy mode."
                self.audit.record_event(
                    action_type=action_type,
                    tool_name=tool_name,
                    risk_level=ActionRisk.HIGH.value,
                    policy_decision=PolicyDecision.DENY.value,
                    reason=reason,
                    request_id=request_id,
                    details=parameters,
                )
                return PolicyDecision.DENY.value, ActionRisk.HIGH.value, reason

        # 4. Human Approval Consumption Verification
        if active_approval_id:
            consumed, consume_msg = self.consume_approval(active_approval_id, parameters)
            if not consumed:
                reason = f"Operation rejected: {consume_msg}"
                self.audit.record_event(
                    action_type=action_type,
                    tool_name=tool_name,
                    target_resource=str(parameters.get("file_path") or parameters.get("url") or ""),
                    risk_level=ActionRisk.HIGH.value,
                    policy_decision=PolicyDecision.DENY.value,
                    reason=reason,
                    request_id=request_id,
                    details=parameters,
                )
                return PolicyDecision.DENY.value, ActionRisk.HIGH.value, reason
            else:
                decision = PolicyDecision.ALLOW.value
                risk = ActionRisk.HIGH.value
                reason = "Action explicitly authorized by verified single-use human approval."
                self.audit.record_event(
                    action_type=action_type,
                    tool_name=tool_name,
                    target_resource=str(parameters.get("file_path") or parameters.get("url") or ""),
                    risk_level=risk,
                    policy_decision=decision,
                    reason=reason,
                    request_id=request_id,
                    user_approved=True,
                    details=parameters,
                )
                return decision, risk, reason

        # 5. Determine Risk Levels and Standard Policies
        if tool_name in (
            "search_web", "rag_search", "inspect_workspace", "read_project_file", "evaluate_logic",
            "desktop_inspect_directory", "desktop_find_files", "desktop_read_file",
            "desktop_system_diagnostics", "desktop_list_running_apps", "desktop_analyze_error_logs",
        ):
            risk = ActionRisk.LOW.value
            decision = PolicyDecision.ALLOW.value
            reason = "Read-only inspection or safe retrieval permitted."

        elif tool_name in ("fetch_webpage", "manage_memory"):
            risk = ActionRisk.MEDIUM.value
            decision = PolicyDecision.ALLOW.value
            reason = "Medium-risk external retrieval or memory update permitted."

        elif tool_name in (
            "desktop_open_application",
            "desktop_open_url",
            "open_url",
            "desktop_search_youtube",
            "search_youtube",
        ):
            risk = ActionRisk.MEDIUM.value
            if pre_approved:
                decision = PolicyDecision.ALLOW.value
                reason = "URL open or application launch explicitly pre-approved by user."
            else:
                decision = PolicyDecision.REQUIRE_APPROVAL.value
                reason = "Opening URL or application requires explicit user confirmation."

        elif tool_name in ("apply_code_edit", "run_project_tests", "desktop_modify_file", "desktop_run_workspace_test"):
            risk = ActionRisk.HIGH.value
            if pre_approved:
                decision = PolicyDecision.ALLOW.value
                reason = "High-risk file modification or test execution explicitly pre-approved by user."
            else:
                decision = PolicyDecision.REQUIRE_APPROVAL.value
                reason = "File modifications and test execution require user confirmation."

        elif tool_name in ("execute_arbitrary_shell", "delete_project_file", "desktop_delete_file"):
            risk = ActionRisk.CRITICAL.value
            if pre_approved:
                decision = PolicyDecision.ALLOW.value
                reason = "Critical operation approved by user."
            else:
                decision = PolicyDecision.REQUIRE_APPROVAL.value
                reason = "Potentially destructive or system-level operation requires explicit human oversight."
        else:
            risk = ActionRisk.MEDIUM.value
            decision = PolicyDecision.ALLOW.value
            reason = "Operation permitted under standard policy."

        # Audit log the decision
        self.audit.record_event(
            action_type=action_type,
            tool_name=tool_name,
            target_resource=str(parameters.get("file_path") or parameters.get("url") or ""),
            risk_level=risk,
            policy_decision=decision,
            reason=reason,
            request_id=request_id,
            user_approved=True if pre_approved else None,
            details=parameters,
        )

        return decision, risk, reason

    def register_approval_request(
        self,
        approval_id: str,
        tool_name: str,
        parameters: Dict[str, Any],
        reason: str,
        risk_level: str,
        task_id: Optional[str] = None,
        action_id: Optional[str] = None,
        ttl_minutes: int = 15,
    ) -> Dict[str, Any]:
        """Registers a pending approval request in SQLite and memory."""
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        expires_at = (now_dt + timedelta(minutes=ttl_minutes)).isoformat()
        param_hash = compute_canonical_parameter_hash(parameters)

        record = {
            "id": approval_id,
            "task_id": task_id,
            "action_id": action_id,
            "tool_name": tool_name,
            "action_type": "TOOL_EXECUTION",
            "target_resource": str(parameters.get("file_path") or parameters.get("url") or ""),
            "parameters": parameters,
            "canonical_param_hash": param_hash,
            "reason": reason,
            "risk_level": risk_level,
            "status": "pending",
            "requested_at": now_iso,
            "expires_at": expires_at,
        }

        self.pending_approvals[approval_id] = record

        if self.task_repo:
            from src.tasks.models import ApprovalRequest, ApprovalStatus
            self.task_repo.create_approval_request(
                ApprovalRequest(
                    id=approval_id,
                    task_id=task_id,
                    action_id=action_id,
                    tool_name=tool_name,
                    action_type="TOOL_EXECUTION",
                    target_resource=record["target_resource"],
                    parameters=parameters,
                    canonical_param_hash=param_hash,
                    risk_level=risk_level,
                    policy_reason=reason,
                    status=ApprovalStatus.PENDING,
                    requested_at=now_iso,
                    expires_at=expires_at,
                )
            )

        return record

    def resolve_approval(
        self,
        approval_id: str,
        approved: bool,
        decision_maker: str = "user",
        reason: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Resolves a pending human approval request."""
        now_iso = datetime.now(timezone.utc).isoformat()
        new_status = "approved" if approved else "rejected"

        if approval_id in self.pending_approvals:
            rec = self.pending_approvals[approval_id]
            rec["status"] = new_status
            rec["decision_at"] = now_iso
            rec["decision_maker"] = decision_maker
            rec["decision_reason"] = reason

        if self.task_repo:
            resolved = self.task_repo.resolve_approval_request(
                approval_id=approval_id,
                approved=approved,
                decision_maker=decision_maker,
                decision_reason=reason,
            )
            if resolved:
                res_dict = resolved.model_dump()
                self.pending_approvals[approval_id] = res_dict
                return res_dict

        return self.pending_approvals.get(approval_id)

    def consume_approval(
        self,
        approval_id: str,
        parameters: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """Atomically checks and consumes a single-use approval.

        Validates status, expiration, and canonical parameter match.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        param_hash = compute_canonical_parameter_hash(parameters)

        if self.task_repo:
            consumed = self.task_repo.consume_approval_request(
                approval_id=approval_id,
                canonical_param_hash=param_hash,
            )
            if not consumed:
                # Determine detailed reason
                raw_rec = self.task_repo.get_approval_request(approval_id)
                if not raw_rec:
                    return False, f"Approval request '{approval_id}' not found."
                if raw_rec.status.value == "consumed":
                    return False, f"Approval '{approval_id}' has already been consumed (single-use)."
                if raw_rec.status.value in ("rejected", "denied"):
                    return False, f"Approval '{approval_id}' was rejected."
                if raw_rec.status.value == "expired" or (raw_rec.expires_at and raw_rec.expires_at < now_iso):
                    return False, f"Approval '{approval_id}' has expired."
                if raw_rec.canonical_param_hash != param_hash:
                    return False, f"Parameters modified since approval was granted for '{approval_id}'."
                return False, f"Approval '{approval_id}' is not in approved state (status: {raw_rec.status.value})."

            res_dict = consumed.model_dump()
            self.pending_approvals[approval_id] = res_dict
            return True, "Approval verified and atomically consumed."

        # In-memory fallback
        if approval_id not in self.pending_approvals:
            return False, f"Approval request '{approval_id}' not found in memory."

        rec = self.pending_approvals[approval_id]
        if rec["status"] == "consumed":
            return False, f"Approval '{approval_id}' has already been consumed (single-use)."
        if rec["status"] != "approved":
            return False, f"Approval '{approval_id}' is not approved (status: {rec['status']})."
        if rec.get("expires_at") and rec["expires_at"] < now_iso:
            rec["status"] = "expired"
            return False, f"Approval '{approval_id}' has expired."
        if rec.get("canonical_param_hash") and rec["canonical_param_hash"] != param_hash:
            return False, f"Parameters modified since approval was granted for '{approval_id}'."

        rec["status"] = "consumed"
        rec["consumed_at"] = now_iso
        return True, "Approval verified and consumed."

    def get_approval(self, approval_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves approval by ID from database or memory."""
        if self.task_repo:
            rec = self.task_repo.get_approval_request(approval_id)
            if rec:
                return rec.model_dump()
        return self.pending_approvals.get(approval_id)

    def list_pending_approvals(self) -> List[Dict[str, Any]]:
        """Returns list of pending approval requests."""
        if self.task_repo:
            from src.tasks.models import ApprovalStatus
            recs = self.task_repo.list_approval_requests(status=ApprovalStatus.PENDING)
            return [r.model_dump() for r in recs]
        return [v for v in self.pending_approvals.values() if v.get("status") == "pending"]
