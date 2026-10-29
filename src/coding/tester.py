"""Coding coworker: Automated test execution and result parsing."""

import subprocess
import json
import re
from pathlib import Path
from typing import Dict, Any, Optional

def run_project_pytest(
    root_dir: str,
    test_path: Optional[str] = None,
    timeout_seconds: int = 45
) -> str:
    """Executes pytest inside the authorized project workspace and parses test results.

    AIRA never reports passing tests unless the test execution was actually run.
    """
    root = Path(root_dir).resolve()
    if not root.is_dir():
        return json.dumps({
            "status": "error",
            "error": f"Invalid workspace directory: {root_dir}"
        })

    cmd = ["pytest", "-v"]
    if test_path:
        target = Path(test_path).resolve()
        if not target.is_relative_to(root):
            return json.dumps({
                "status": "error",
                "error": f"Test path '{test_path}' is outside authorized workspace '{root_dir}'."
            })
        cmd.append(str(target))

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )

        stdout = proc.stdout
        stderr = proc.stderr
        exit_code = proc.returncode

        # Parse test outcomes from stdout
        passed = 0
        failed = 0
        errors = 0
        skipped = 0

        # Match e.g. "5 passed, 1 failed, 2 errors in 0.45s"
        summary_match = re.search(r"=+\s*(.*?)\s*in\s*[\d\.]+s\s*=+", stdout)
        summary_line = summary_match.group(1) if summary_match else stdout.strip().split("\n")[-1]

        passed_m = re.search(r"(\d+)\s+passed", stdout)
        if passed_m:
            passed = int(passed_m.group(1))

        failed_m = re.search(r"(\d+)\s+failed", stdout)
        if failed_m:
            failed = int(failed_m.group(1))

        errors_m = re.search(r"(\d+)\s+error", stdout)
        if errors_m:
            errors = int(errors_m.group(1))

        skipped_m = re.search(r"(\d+)\s+skipped", stdout)
        if skipped_m:
            skipped = int(skipped_m.group(1))

        success = (exit_code == 0) and (passed > 0 or "passed" in summary_line)

        return json.dumps({
            "status": "completed",
            "exit_code": exit_code,
            "success": success,
            "summary": summary_line,
            "counts": {
                "passed": passed,
                "failed": failed,
                "errors": errors,
                "skipped": skipped
            },
            "output_sample": stdout[-2000:] if len(stdout) > 2000 else stdout,
            "stderr": stderr[:500] if stderr else ""
        })

    except subprocess.TimeoutExpired:
        return json.dumps({
            "status": "error",
            "error": f"Pytest execution timed out after {timeout_seconds} seconds."
        })
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error": f"Failed to execute pytest: {str(e)}"
        })
