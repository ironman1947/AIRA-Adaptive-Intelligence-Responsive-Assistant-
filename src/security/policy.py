"""AIRA Policy Decision Layer.

Enforces security, permissions, privacy boundaries, and human oversight
prior to executing any tool or operation.
"""

from typing import Dict, Any, Optional, Tuple
from pathlib import Path
from src.security.audit import AuditService
from src.security.network import validate_url_security

class PolicyDecisionEngine:
    def __init__(self, audit_service: AuditService):
        self.audit = audit_service
        self.pending_approvals: Dict[str, Dict[str, Any]] = {}

    def evaluate_action(
        self,
        action_type: str,
        tool_name: str,
        parameters: Dict[str, Any],
        request_id: Optional[str] = None,
        privacy_mode: str = "standard",
        authorized_root: Optional[str] = None,
        pre_approved: bool = False,
    ) -> Tuple[str, str, str]:
        """Evaluates an action against AIRA's security constitution and policies.

        Returns:
            (decision, risk_level, reason)
            where decision is one of 'ALLOW', 'REQUIRE_APPROVAL', 'DENY'.
        """
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
                            risk_level="CRITICAL",
                            policy_decision="DENY",
                            reason=reason,
                            request_id=request_id,
                            details=parameters,
                        )
                        return "DENY", "CRITICAL", reason
                except Exception as e:
                    reason = f"Invalid file path syntax: {e}"
                    return "DENY", "CRITICAL", reason

        # 2. Check Network Safety for URL fetching
        if tool_name == "fetch_webpage" and "url" in parameters:
            url = parameters.get("url", "")
            is_safe, error_msg = validate_url_security(url)
            if not is_safe:
                reason = f"URL blocked by SSRF/Network Safety Policy: {error_msg}"
                self.audit.record_event(
                    action_type=action_type,
                    tool_name=tool_name,
                    target_resource=url,
                    risk_level="HIGH",
                    policy_decision="DENY",
                    reason=reason,
                    request_id=request_id,
                    details=parameters,
                )
                return "DENY", "HIGH", reason

        # 3. Privacy Policy Enforcement: Local-only mode
        if privacy_mode == "local_only" and action_type in ("CLOUD_ROUTING", "EXTERNAL_API"):
            reason = "Cloud escalation blocked: User has enforced Local-Only privacy mode."
            self.audit.record_event(
                action_type=action_type,
                tool_name=tool_name,
                risk_level="HIGH",
                policy_decision="DENY",
                reason=reason,
                request_id=request_id,
                details=parameters,
            )
            return "DENY", "HIGH", reason

        # 4. Determine Risk Levels and Approval Requirements
        if tool_name in (
            "search_web", "rag_search", "inspect_workspace", "read_project_file", "evaluate_logic",
            "desktop_inspect_directory", "desktop_find_files", "desktop_read_file",
            "desktop_system_diagnostics", "desktop_list_running_apps", "desktop_analyze_error_logs",
        ):
            risk = "LOW"
            decision = "ALLOW"
            reason = "Read-only inspection or safe retrieval permitted."

        elif tool_name in ("fetch_webpage", "manage_memory"):
            risk = "MEDIUM"
            decision = "ALLOW"
            reason = "Medium-risk external retrieval or memory update permitted."

        elif tool_name in ("desktop_open_application",):
            risk = "MEDIUM"
            if pre_approved:
                decision = "ALLOW"
                reason = "Application launch explicitly pre-approved by user."
            else:
                decision = "REQUIRE_APPROVAL"
                reason = "Application launch requires explicit user confirmation."

        elif tool_name in ("apply_code_edit", "run_project_tests", "desktop_modify_file", "desktop_run_workspace_test"):
            risk = "HIGH"
            if pre_approved:
                decision = "ALLOW"
                reason = "High-risk file modification or test execution explicitly pre-approved by user."
            else:
                decision = "REQUIRE_APPROVAL"
                reason = "File modifications and test execution require user confirmation."

        elif tool_name in ("execute_arbitrary_shell", "delete_project_file", "desktop_delete_file"):
            risk = "CRITICAL"
            if pre_approved:
                decision = "ALLOW"
                reason = "Critical operation approved by user."
            else:
                decision = "REQUIRE_APPROVAL"
                reason = "Potentially destructive or system-level operation requires explicit human oversight."
        else:
            risk = "MEDIUM"
            decision = "ALLOW"
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
    ) -> Dict[str, Any]:
        record = {
            "id": approval_id,
            "tool_name": tool_name,
            "parameters": parameters,
            "reason": reason,
            "risk_level": risk_level,
            "status": "pending",
        }
        self.pending_approvals[approval_id] = record
        return record

    def resolve_approval(self, approval_id: str, approved: bool) -> Optional[Dict[str, Any]]:
        if approval_id in self.pending_approvals:
            record = self.pending_approvals[approval_id]
            record["status"] = "approved" if approved else "denied"
            return record
        return None
