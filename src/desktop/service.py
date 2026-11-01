"""AIRA Desktop Control Service.

Enforces scope restriction, macOS system inspection, and mandatory human approval
prior to executing ANY computer modification.
"""

import os
import uuid
import time
import difflib
import subprocess
import shutil
import urllib.parse
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from src.desktop.models import ActionCategory, DesktopActionPlan, DesktopActionProposal
from src.security.policy import PolicyDecisionEngine
from src.security.audit import AuditService


def build_youtube_search_url(query: str) -> str:
    """Builds a safely encoded YouTube search URL."""
    encoded_query = urllib.parse.quote_plus(query.strip())
    return f"https://www.youtube.com/results?search_query={encoded_query}"


class DesktopControlService:
    """Coordinates local macOS desktop operations under strict policy enforcement."""

    APPROVED_APPLICATIONS = {
        "safari": "Safari",
        "terminal": "Terminal",
        "vs code": "Visual Studio Code",
        "visual studio code": "Visual Studio Code",
        "code": "Visual Studio Code",
        "finder": "Finder",
        "textedit": "TextEdit",
        "notes": "Notes",
        "calculator": "Calculator",
        "system settings": "System Settings",
        "slack": "Slack",
        "xcode": "Xcode",
    }

    def __init__(
        self,
        authorized_roots: Optional[List[str]] = None,
        policy_engine: Optional[PolicyDecisionEngine] = None,
        audit_service: Optional[AuditService] = None,
    ):
        from src.config import BASE_DIR
        self.authorized_roots = [
            Path(r).resolve() for r in (authorized_roots or [str(BASE_DIR)])
        ]
        self.policy_engine = policy_engine
        self.audit = audit_service
        self.active_plans: Dict[str, DesktopActionPlan] = {}

    def is_path_authorized(self, target_path: str) -> Tuple[bool, Optional[Path], str]:
        """Validates that a path resides strictly within one of the authorized workspaces."""
        try:
            resolved = Path(target_path).expanduser().resolve()
            for root in self.authorized_roots:
                if resolved == root or resolved.is_relative_to(root):
                    return True, resolved, "Authorized"
            return False, resolved, f"Path '{target_path}' is outside authorized workspaces."
        except Exception as e:
            return False, None, f"Invalid path syntax: {str(e)}"

    # --------------------------------------------------------------------------
    # Read-Only Operations (Executed directly within authorized scopes)
    # --------------------------------------------------------------------------

    def inspect_directory(self, directory_path: Optional[str] = None, max_depth: int = 2) -> Dict[str, Any]:
        """Inspects directory structure, file counts, and sizes in an authorized workspace."""
        target_str = directory_path or str(self.authorized_roots[0])
        is_auth, resolved, reason = self.is_path_authorized(target_str)
        if not is_auth or not resolved:
            return {"success": False, "error": reason}

        if not resolved.exists():
            return {"success": False, "error": f"Directory not found: '{target_str}'"}
        if not resolved.is_dir():
            return {"success": False, "error": f"Path is not a directory: '{target_str}'"}

        entries = []
        try:
            for item in sorted(resolved.iterdir()):
                # Skip hidden dotfiles and cache dirs
                if item.name.startswith(".") and item.name not in (".env.example", ".streamlit"):
                    continue
                if item.name in ("__pycache__", "node_modules", ".git", ".venv"):
                    continue

                is_directory = item.is_dir()
                size_bytes = 0
                if not is_directory:
                    try:
                        size_bytes = item.stat().st_size
                    except Exception:
                        pass

                entries.append({
                    "name": item.name,
                    "type": "directory" if is_directory else "file",
                    "size_bytes": size_bytes,
                    "relative_path": str(item.relative_to(resolved)),
                })

            return {
                "success": True,
                "directory": str(resolved),
                "total_items": len(entries),
                "entries": entries[:100],  # cap at 100 entries for safety
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to inspect directory: {str(e)}"}

    def find_files(self, pattern: str, directory_path: Optional[str] = None) -> Dict[str, Any]:
        """Finds files matching a glob pattern inside an authorized workspace."""
        target_str = directory_path or str(self.authorized_roots[0])
        is_auth, resolved, reason = self.is_path_authorized(target_str)
        if not is_auth or not resolved:
            return {"success": False, "error": reason}

        try:
            matches = []
            for path in resolved.glob(pattern):
                if any(p in path.parts for p in (".git", ".venv", "__pycache__", "node_modules")):
                    continue
                matches.append(str(path.relative_to(resolved)))

            return {
                "success": True,
                "pattern": pattern,
                "directory": str(resolved),
                "count": len(matches),
                "matches": matches[:50],
            }
        except Exception as e:
            return {"success": False, "error": f"Glob search failed: {str(e)}"}

    def read_file(
        self,
        file_path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Safely reads file lines from an authorized workspace."""
        is_auth, resolved, reason = self.is_path_authorized(file_path)
        if not is_auth or not resolved:
            return {"success": False, "error": reason}

        if not resolved.exists():
            return {"success": False, "error": f"File does not exist: '{file_path}'"}
        if resolved.is_dir():
            return {"success": False, "error": f"Path is a directory, not a file: '{file_path}'"}

        try:
            with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            total_lines = len(lines)
            s_idx = max(0, (start_line - 1)) if start_line else 0
            e_idx = min(total_lines, end_line) if end_line else total_lines

            content = "".join(lines[s_idx:e_idx])
            return {
                "success": True,
                "file_path": str(resolved),
                "total_lines": total_lines,
                "start_line": s_idx + 1,
                "end_line": e_idx,
                "content": content,
            }
        except Exception as e:
            return {"success": False, "error": f"Read error: {str(e)}"}

    def get_system_diagnostics(self) -> Dict[str, Any]:
        """Gathers non-destructive macOS system diagnostics (CPU, RAM, Disk, OS version)."""
        diag = {
            "platform": "macOS",
            "timestamp": time.time(),
        }

        # OS Version
        try:
            proc = subprocess.run(["sw_vers"], capture_output=True, text=True, timeout=3)
            for line in proc.stdout.strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    diag[k.strip().lower().replace(" ", "_")] = v.strip()
        except Exception:
            diag["product_version"] = "macOS Unknown"

        # Hardware Model & Chip
        try:
            proc = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=2)
            diag["cpu_brand"] = proc.stdout.strip()
        except Exception:
            diag["cpu_brand"] = "Apple Silicon"

        # Disk Space
        try:
            proc = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=2)
            lines = proc.stdout.strip().splitlines()
            if len(lines) > 1:
                parts = lines[1].split()
                diag["disk_total"] = parts[1]
                diag["disk_used"] = parts[2]
                diag["disk_available"] = parts[3]
                diag["disk_usage_pct"] = parts[4]
        except Exception:
            pass

        # System Uptime
        try:
            proc = subprocess.run(["uptime"], capture_output=True, text=True, timeout=2)
            diag["uptime"] = proc.stdout.strip()
        except Exception:
            pass

        return {"success": True, "diagnostics": diag}

    def list_running_apps(self) -> Dict[str, Any]:
        """Lists active visible GUI applications running on macOS."""
        try:
            script = 'tell application "System Events" to get name of every process whose visible is true'
            proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=4)
            if proc.returncode == 0:
                raw_apps = [a.strip() for a in proc.stdout.strip().split(",") if a.strip()]
                return {
                    "success": True,
                    "running_apps": sorted(list(set(raw_apps))),
                    "count": len(raw_apps),
                }
        except Exception as e:
            print(f"⚠️ list_running_apps osascript error: {e}")

        # Fallback to ps listing if AppleScript automation is not granted
        try:
            proc = subprocess.run(["ps", "-eo", "comm"], capture_output=True, text=True, timeout=3)
            app_names = set()
            for line in proc.stdout.splitlines():
                if ".app/" in line:
                    name = line.split(".app/")[0].split("/")[-1]
                    app_names.add(name)
            return {
                "success": True,
                "running_apps": sorted(list(app_names)),
                "count": len(app_names),
            }
        except Exception as e:
            return {"success": False, "error": str(e), "running_apps": []}

    def analyze_error_logs(self, log_path: str, max_lines: int = 100) -> Dict[str, Any]:
        """Safely inspects log files within authorized workspace."""
        is_auth, resolved, reason = self.is_path_authorized(log_path)
        if not is_auth or not resolved:
            return {"success": False, "error": reason}

        if not resolved.exists():
            return {"success": False, "error": f"Log file not found: {log_path}"}

        try:
            with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            return {
                "success": True,
                "file": str(resolved),
                "total_lines": len(lines),
                "lines": lines[-max_lines:],
            }
        except Exception as e:
            return {"success": False, "error": f"Failed reading log: {str(e)}"}

    # --------------------------------------------------------------------------
    # Mandatory Approval Before Modification (Plans & Execution)
    # --------------------------------------------------------------------------

    def propose_file_change(
        self,
        file_path: str,
        new_content: str,
        explanation: str,
        action_type: str = "edit",  # create, edit, delete
    ) -> DesktopActionPlan:
        """Constructs an action plan with unified diff WITHOUT modifying the file.

        The proposed plan is registered in the policy engine and paused awaiting human approval.
        """
        is_auth, resolved, reason = self.is_path_authorized(file_path)
        if not is_auth or not resolved:
            raise PermissionError(reason)

        old_content = ""
        diff_text = ""
        if resolved.exists() and action_type != "create":
            try:
                with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                    old_content = f.read()
            except Exception:
                old_content = ""

            old_lines = old_content.splitlines(keepends=True)
            new_lines = new_content.splitlines(keepends=True)
            diff_text = "".join(
                difflib.unified_diff(
                    old_lines,
                    new_lines,
                    fromfile=f"a/{resolved.name}",
                    tofile=f"b/{resolved.name}",
                )
            )
        else:
            diff_text = f"--- /dev/null\n+++ b/{resolved.name}\n@@ -0,0 +1 @@\n+ [New File: {len(new_content)} characters]"

        category = ActionCategory.DESTRUCTIVE if action_type == "delete" else ActionCategory.MODIFY
        plan_id = f"plan_{uuid.uuid4().hex[:8]}"

        plan = DesktopActionPlan(
            plan_id=plan_id,
            tool_name="modify_workspace_file",
            category=category,
            description=explanation or f"Propose to {action_type} '{resolved.name}'",
            affected_resource=str(resolved),
            diff=diff_text,
            parameters={
                "file_path": str(resolved),
                "new_content": new_content,
                "action_type": action_type,
            },
            status="pending_approval",
        )

        self.active_plans[plan_id] = plan

        # Register in central policy decision engine
        if self.policy_engine:
            self.policy_engine.register_approval_request(
                approval_id=plan_id,
                tool_name="modify_workspace_file",
                parameters=plan.parameters,
                reason=plan.description,
                risk_level="HIGH" if category == ActionCategory.MODIFY else "CRITICAL",
            )

        return plan

    def propose_app_launch(self, app_name: str) -> DesktopActionPlan:
        """Constructs an action plan to launch an approved macOS application."""
        normalized = app_name.strip().lower()
        if normalized not in self.APPROVED_APPLICATIONS:
            available_list = ", ".join(sorted(set(self.APPROVED_APPLICATIONS.values())))
            raise ValueError(
                f"Application '{app_name}' is not in the approved whitelist. "
                f"Approved applications: {available_list}"
            )

        canonical_name = self.APPROVED_APPLICATIONS[normalized]
        plan_id = f"plan_{uuid.uuid4().hex[:8]}"

        plan = DesktopActionPlan(
            plan_id=plan_id,
            tool_name="open_application",
            category=ActionCategory.MODIFY,
            description=f"Launch application '{canonical_name}'",
            affected_resource=canonical_name,
            command=f"/usr/bin/open -a '{canonical_name}'",
            parameters={"app_name": canonical_name},
            status="pending_approval",
        )

        self.active_plans[plan_id] = plan

        if self.policy_engine:
            self.policy_engine.register_approval_request(
                approval_id=plan_id,
                tool_name="open_application",
                parameters=plan.parameters,
                reason=plan.description,
                risk_level="MEDIUM",
            )

        return plan

    def build_youtube_search_url(self, query: str) -> str:
        """Instance method helper to build a YouTube search URL."""
        return build_youtube_search_url(query)

    def propose_open_url(self, url: str, browser: str = "Safari") -> DesktopActionProposal:
        """Constructs an action plan to open a verified public URL in an approved browser."""
        from src.security.network import validate_url_security

        is_safe, reason = validate_url_security(url)
        if not is_safe:
            raise PermissionError(f"URL violates security policy: {reason}")

        normalized_browser = browser.strip().lower()
        if normalized_browser in self.APPROVED_APPLICATIONS:
            canonical_browser = self.APPROVED_APPLICATIONS[normalized_browser]
        else:
            canonical_browser = browser.strip() or "Safari"

        plan_id = f"plan_{uuid.uuid4().hex[:8]}"
        plan = DesktopActionPlan(
            plan_id=plan_id,
            tool_name="open_url",
            category=ActionCategory.OPEN_URL,
            description=f"Open URL '{url}' in {canonical_browser}",
            affected_resource=url,
            command=f"/usr/bin/open -a '{canonical_browser}' '{url}'",
            parameters={"url": url, "browser": canonical_browser},
            status="pending_approval",
        )

        self.active_plans[plan_id] = plan

        if self.policy_engine:
            self.policy_engine.register_approval_request(
                approval_id=plan_id,
                tool_name="open_url",
                parameters=plan.parameters,
                reason=plan.description,
                risk_level="MEDIUM",
            )

        return plan

    def propose_workspace_test(self, command: str, cwd: Optional[str] = None) -> DesktopActionPlan:
        """Constructs an action plan to run a diagnostic/test command in an authorized workspace."""
        target_cwd = cwd or str(self.authorized_roots[0])
        is_auth, resolved, reason = self.is_path_authorized(target_cwd)
        if not is_auth or not resolved:
            raise PermissionError(reason)

        # Disallow arbitrary bash chaining (&&, ;, |, rm, sudo)
        clean_cmd = command.strip()
        blocked_tokens = [";", "&&", "||", "|", "rm -", "sudo", "chmod", "curl", "wget"]
        for token in blocked_tokens:
            if token in clean_cmd:
                raise ValueError(f"Command contains prohibited operator or keyword: '{token}'")

        plan_id = f"plan_{uuid.uuid4().hex[:8]}"
        plan = DesktopActionPlan(
            plan_id=plan_id,
            tool_name="run_workspace_test",
            category=ActionCategory.MODIFY,
            description=f"Execute diagnostic test in '{resolved.name}': `{clean_cmd}`",
            affected_resource=str(resolved),
            command=clean_cmd,
            parameters={"command": clean_cmd, "cwd": str(resolved)},
            status="pending_approval",
        )

        self.active_plans[plan_id] = plan

        if self.policy_engine:
            self.policy_engine.register_approval_request(
                approval_id=plan_id,
                tool_name="run_workspace_test",
                parameters=plan.parameters,
                reason=plan.description,
                risk_level="HIGH",
            )

        return plan

    def execute_approved_plan(self, plan_id: str) -> Dict[str, Any]:
        """Executes ONLY a plan that has been explicitly approved by the user."""
        if plan_id not in self.active_plans:
            # Check policy engine
            if self.policy_engine and plan_id in self.policy_engine.pending_approvals:
                rec = self.policy_engine.pending_approvals[plan_id]
                if rec.get("status") == "approved":
                    pass
                else:
                    return {"success": False, "error": f"Plan '{plan_id}' has not been approved."}
            else:
                return {"success": False, "error": f"Plan '{plan_id}' not found."}

        plan = self.active_plans[plan_id]

        # Verify policy engine approval
        if self.policy_engine and plan_id in self.policy_engine.pending_approvals:
            approval_rec = self.policy_engine.pending_approvals[plan_id]
            if approval_rec.get("status") != "approved":
                return {
                    "success": False,
                    "error": f"Execution rejected: Plan '{plan_id}' is not in approved state (status: {approval_rec.get('status')})."
                }

        try:
            if plan.tool_name == "modify_workspace_file":
                file_path = plan.parameters["file_path"]
                new_content = plan.parameters["new_content"]
                action_type = plan.parameters.get("action_type", "edit")

                target = Path(file_path)
                if action_type == "delete":
                    if target.exists():
                        target.unlink()
                    outcome = f"File '{target.name}' successfully deleted."
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with open(target, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    outcome = f"File '{target.name}' successfully updated ({len(new_content)} characters)."

                plan.status = "executed"
                plan.executed_at = time.time()
                plan.verified_outcome = outcome
                plan.execution_result = {"outcome": outcome, "verified": target.exists() if action_type != "delete" else not target.exists()}

                if self.audit:
                    self.audit.record_event(
                        action_type="WORKSPACE_MODIFY",
                        tool_name="modify_workspace_file",
                        target_resource=file_path,
                        risk_level="HIGH",
                        policy_decision="ALLOW",
                        reason="Executed with explicit user approval.",
                        user_approved=True,
                        details={"plan_id": plan_id},
                    )

                return {"success": True, "plan_id": plan_id, "outcome": outcome}

            elif plan.tool_name == "open_application":
                app_name = plan.parameters["app_name"]
                cmd = ["/usr/bin/open", "-a", app_name]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if proc.returncode != 0:
                    raise RuntimeError(f"Failed opening app: {proc.stderr}")

                outcome = f"Application '{app_name}' launched successfully."
                plan.status = "executed"
                plan.executed_at = time.time()
                plan.verified_outcome = outcome
                plan.execution_result = {"outcome": outcome, "returncode": 0}

                return {"success": True, "plan_id": plan_id, "outcome": outcome}

            elif plan.tool_name == "open_url":
                url = plan.parameters["url"]
                browser = plan.parameters.get("browser", "Safari")
                cmd = ["open", "-a", browser, url]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if proc.returncode != 0:
                    raise RuntimeError(f"Failed opening URL in browser: {proc.stderr}")

                # Verification on macOS: poll for up to 3 seconds with osascript or pgrep
                verified = False
                verification_detail = ""
                deadline = time.time() + 3.0
                while time.time() < deadline:
                    v_proc = subprocess.run(
                        ["pgrep", "-x", browser],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    if v_proc.returncode == 0:
                        verified = True
                        verification_detail = f"Process '{browser}' is running (PID: {v_proc.stdout.strip().split()[0]})."
                        break
                    time.sleep(0.5)

                if not verified:
                    # Fallback check using AppleScript osascript
                    osa_proc = subprocess.run(
                        ["osascript", "-e", f'application "{browser}" is running'],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    if osa_proc.returncode == 0 and "true" in osa_proc.stdout.lower():
                        verified = True
                        verification_detail = f"Browser '{browser}' confirmed running via System Events."
                    else:
                        verified = False
                        verification_detail = f"Could not verify browser window or process '{browser}' launched within timeout."

                outcome = f"URL '{url}' launched in {browser}. Verified: {verified}"
                plan.status = "executed"
                plan.executed_at = time.time()
                plan.verified = verified
                plan.verification_detail = verification_detail
                plan.verified_outcome = outcome
                plan.execution_result = {
                    "outcome": outcome,
                    "returncode": 0,
                    "verified": verified,
                    "verification_detail": verification_detail,
                }

                if self.audit:
                    self.audit.record_event(
                        action_type="DESKTOP_ACTION",
                        tool_name="open_url",
                        target_resource=url,
                        risk_level="MEDIUM",
                        policy_decision="ALLOW",
                        reason="Executed with explicit user approval.",
                        user_approved=True,
                        details={"plan_id": plan_id, "browser": browser, "verified": verified},
                    )

                return {
                    "success": True,
                    "plan_id": plan_id,
                    "outcome": outcome,
                    "verified": verified,
                    "verification_detail": verification_detail,
                }

            elif plan.tool_name == "run_workspace_test":
                command = plan.parameters["command"]
                cwd = plan.parameters["cwd"]
                proc = subprocess.run(
                    command,
                    shell=True,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                outcome = f"Test command executed (exit {proc.returncode}). Output: {proc.stdout[:400]}"
                plan.status = "executed"
                plan.executed_at = time.time()
                plan.verified_outcome = outcome
                plan.execution_result = {
                    "returncode": proc.returncode,
                    "stdout": proc.stdout[:1500],
                    "stderr": proc.stderr[:1000],
                }
                return {
                    "success": proc.returncode == 0,
                    "plan_id": plan_id,
                    "returncode": proc.returncode,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                }
            else:
                return {"success": False, "error": f"Unknown tool in plan: {plan.tool_name}"}

        except Exception as e:
            plan.status = "failed"
            plan.execution_result = {"error": str(e)}
            return {"success": False, "plan_id": plan_id, "error": str(e)}

    def reject_plan(self, plan_id: str, reason: str = "User declined change") -> Dict[str, Any]:
        """Marks an action plan rejected. Guarantees zero computer modifications."""
        if plan_id in self.active_plans:
            plan = self.active_plans[plan_id]
            plan.status = "rejected"
            plan.rejection_reason = reason

        if self.policy_engine:
            self.policy_engine.resolve_approval(plan_id, approved=False)

        if self.audit:
            self.audit.record_event(
                action_type="WORKSPACE_MODIFY",
                tool_name="plan_rejected",
                risk_level="LOW",
                policy_decision="DENY",
                reason=reason,
                user_approved=False,
                details={"plan_id": plan_id},
            )

        return {"success": True, "plan_id": plan_id, "status": "rejected", "reason": reason}


# Global desktop service singleton
_desktop_service_instance: Optional[DesktopControlService] = None

def get_desktop_service() -> DesktopControlService:
    global _desktop_service_instance
    if _desktop_service_instance is None:
        from src.security.audit import AuditService
        from src.security.policy import PolicyDecisionEngine
        from src.memory.repository import MemoryRepository, get_db_manager

        repo = MemoryRepository(get_db_manager())
        audit = AuditService(repo)
        policy = PolicyDecisionEngine(audit)
        _desktop_service_instance = DesktopControlService(
            policy_engine=policy,
            audit_service=audit,
        )
    return _desktop_service_instance
