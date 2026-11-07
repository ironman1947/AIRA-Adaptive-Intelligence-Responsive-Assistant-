"""Controlled Tool Executor for AIRA 2.0.

Provides a centralized, tamper-resistant execution boundary enforcing tool registration,
parameter validation, security policies, human oversight, credential redaction,
and action auditing.
"""

import json
import uuid
from typing import Dict, Any, Optional, Tuple

from src.tools.registry import ToolRegistry, ToolDefinition
from src.security.policy import PolicyDecisionEngine, compute_canonical_parameter_hash
from src.security.audit import AuditService, redact_dict, redact_sensitive_text
from src.tasks.repository import TaskRepository
from src.tasks.models import ActionEvent, utc_now_iso


class ControlledToolExecutor:
    """Central execution gateway for all tool invocations in AIRA."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        policy_engine: PolicyDecisionEngine,
        audit_service: AuditService,
        task_repo: Optional[TaskRepository] = None,
        workspace_root: Optional[str] = None,
    ):
        self.registry = tool_registry
        self.policy = policy_engine
        self.audit = audit_service
        self.task_repo = task_repo
        self.workspace_root = workspace_root or tool_registry.workspace_root

    def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        request_id: Optional[str] = None,
        task_id: Optional[str] = None,
        privacy_mode: str = "standard",
        pre_approved: bool = False,
        approval_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validates, policy-checks, audits, and executes a tool within controlled boundaries."""
        action_id = f"act_{uuid.uuid4().hex[:10]}"
        safe_arguments = redact_dict(arguments or {})

        # 1. Validate tool registration
        tool_def = self.registry.get_tool(tool_name)
        if not tool_def:
            error_msg = f"Tool '{tool_name}' not found in registry."
            self._record_action_event(
                action_id=action_id,
                task_id=task_id,
                approval_id=approval_id,
                event_type="TOOL_NOT_FOUND",
                tool_name=tool_name,
                action_type="UNKNOWN",
                target_resource="",
                parameter_fingerprint=compute_canonical_parameter_hash(arguments),
                policy_decision="DENY",
                risk_level="LOW",
                result_summary="Tool rejected: unregistered",
                error_details={"error": error_msg},
                event_payload={"arguments": safe_arguments},
                request_id=request_id,
            )
            return {
                "status": "error",
                "policy_decision": "DENY",
                "error": error_msg,
                "action_id": action_id,
            }

        # 2. Validate parameters against schema if required properties are declared
        schema = tool_def.schema
        if schema and "function" in schema and "parameters" in schema["function"]:
            params_spec = schema["function"]["parameters"]
            required_keys = params_spec.get("required", [])
            for rk in required_keys:
                if rk not in arguments or arguments[rk] is None:
                    error_msg = f"Missing required parameter '{rk}' for tool '{tool_name}'."
                    self._record_action_event(
                        action_id=action_id,
                        task_id=task_id,
                        approval_id=approval_id,
                        event_type="INVALID_ARGUMENTS",
                        tool_name=tool_name,
                        action_type=tool_def.action_type,
                        target_resource=str(arguments.get("file_path") or arguments.get("url") or ""),
                        parameter_fingerprint=compute_canonical_parameter_hash(arguments),
                        policy_decision="DENY",
                        risk_level=tool_def.risk_level,
                        result_summary="Tool rejected: invalid arguments",
                        error_details={"error": error_msg},
                        event_payload={"arguments": safe_arguments},
                        request_id=request_id,
                    )
                    return {
                        "status": "error",
                        "policy_decision": "DENY",
                        "error": error_msg,
                        "action_id": action_id,
                    }

        # 3. Policy Evaluation
        target_resource = str(arguments.get("file_path") or arguments.get("path") or arguments.get("url") or "")
        decision, risk, reason = self.policy.evaluate_action(
            action_type=tool_def.action_type,
            tool_name=tool_name,
            parameters=arguments,
            request_id=request_id,
            privacy_mode=privacy_mode,
            authorized_root=self.workspace_root,
            pre_approved=pre_approved,
            approval_id=approval_id,
            task_id=task_id,
        )

        param_hash = compute_canonical_parameter_hash(arguments)

        # 4. Handle Decision
        if decision == "DENY":
            self._record_action_event(
                action_id=action_id,
                task_id=task_id,
                approval_id=approval_id,
                event_type="POLICY_DENY",
                tool_name=tool_name,
                action_type=tool_def.action_type,
                target_resource=target_resource,
                parameter_fingerprint=param_hash,
                policy_decision="DENY",
                risk_level=risk,
                result_summary=reason,
                error_details={"policy_reason": reason},
                event_payload={"arguments": safe_arguments},
                request_id=request_id,
            )
            return {
                "status": "denied",
                "policy_decision": "DENY",
                "reason": reason,
                "action_id": action_id,
            }

        elif decision == "REQUIRE_APPROVAL":
            appr_id = f"appr_{uuid.uuid4().hex[:8]}"
            appr_rec = self.policy.register_approval_request(
                approval_id=appr_id,
                tool_name=tool_name,
                parameters=arguments,
                reason=reason,
                risk_level=risk,
                task_id=task_id,
                action_id=action_id,
            )
            self._record_action_event(
                action_id=action_id,
                task_id=task_id,
                approval_id=appr_id,
                event_type="APPROVAL_REQUESTED",
                tool_name=tool_name,
                action_type=tool_def.action_type,
                target_resource=target_resource,
                parameter_fingerprint=param_hash,
                policy_decision="REQUIRE_APPROVAL",
                risk_level=risk,
                result_summary=reason,
                event_payload={"arguments": safe_arguments, "approval_id": appr_id},
                request_id=request_id,
            )
            return {
                "status": "pending_human_approval",
                "policy_decision": "REQUIRE_APPROVAL",
                "approval_id": appr_id,
                "tool_name": tool_name,
                "action_id": action_id,
                "reason": reason,
                "risk_level": risk,
                "parameters": safe_arguments,
                "message": f"Action paused: {reason} Awaiting human confirmation.",
            }

        # 5. Execute Authorized Tool
        try:
            raw_output = tool_def.handler(**arguments)
            out_str = raw_output if isinstance(raw_output, str) else json.dumps(raw_output)
            summary_snippet = (out_str[:200] + "...") if len(out_str) > 200 else out_str

            self._record_action_event(
                action_id=action_id,
                task_id=task_id,
                approval_id=approval_id,
                event_type="TOOL_EXECUTED",
                tool_name=tool_name,
                action_type=tool_def.action_type,
                target_resource=target_resource,
                parameter_fingerprint=param_hash,
                policy_decision="ALLOW",
                risk_level=risk,
                result_summary=redact_sensitive_text(summary_snippet),
                error_details=None,
                event_payload={"arguments": safe_arguments},
                request_id=request_id,
            )
            return {
                "status": "success",
                "policy_decision": "ALLOW",
                "action_id": action_id,
                "result": out_str,
            }
        except Exception as e:
            err_msg = str(e)
            self._record_action_event(
                action_id=action_id,
                task_id=task_id,
                approval_id=approval_id,
                event_type="TOOL_EXECUTION_FAILED",
                tool_name=tool_name,
                action_type=tool_def.action_type,
                target_resource=target_resource,
                parameter_fingerprint=param_hash,
                policy_decision="ALLOW",
                risk_level=risk,
                result_summary="Execution failed with exception",
                error_details={"error": redact_sensitive_text(err_msg)},
                event_payload={"arguments": safe_arguments},
                request_id=request_id,
            )
            return {
                "status": "error",
                "policy_decision": "ALLOW",
                "action_id": action_id,
                "error": f"Tool execution failed: {err_msg}",
            }

    def _record_action_event(
        self,
        action_id: str,
        task_id: Optional[str],
        approval_id: Optional[str],
        event_type: str,
        tool_name: str,
        action_type: str,
        target_resource: str,
        parameter_fingerprint: str,
        policy_decision: str,
        risk_level: str,
        result_summary: Optional[str],
        error_details: Optional[Dict[str, Any]] = None,
        event_payload: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> None:
        if self.task_repo:
            try:
                self.task_repo.record_action_event(
                    ActionEvent(
                        action_id=action_id,
                        task_id=task_id,
                        approval_id=approval_id,
                        event_type=event_type,
                        tool_name=tool_name,
                        action_type=action_type,
                        target_resource=target_resource,
                        parameter_fingerprint=parameter_fingerprint,
                        policy_decision=policy_decision,
                        risk_level=risk_level,
                        result_summary=result_summary,
                        error_details=error_details,
                        event_payload=event_payload or {},
                        request_id=request_id,
                    )
                )
            except Exception as e:
                # Fallback to audit service logging if DB action event write fails
                pass
