"""Coding coworker: Controlled implementation, diff generation, and safe file edits."""

import os
import json
import difflib
from pathlib import Path
from typing import Dict, Any, Optional

def generate_diff(original_text: str, modified_text: str, filename: str) -> str:
    """Generates a standard unified diff between original and modified text."""
    orig_lines = original_text.splitlines(keepends=True)
    mod_lines = modified_text.splitlines(keepends=True)
    diff = difflib.unified_diff(
        orig_lines,
        mod_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    )
    return "".join(diff)

def apply_workspace_edit(
    file_path: str,
    new_content: str,
    root_dir: str,
    dry_run: bool = False
) -> str:
    """Safely applies or previews a file edit within the authorized workspace.

    Returns JSON containing the unified diff and edit status.
    """
    root = Path(root_dir).resolve()
    target = Path(file_path).resolve()

    if not target.is_relative_to(root):
        return json.dumps({
            "status": "error",
            "error": f"Access denied: '{file_path}' is outside authorized workspace '{root_dir}'."
        })

    original_text = ""
    is_new_file = not target.exists()

    if not is_new_file:
        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                original_text = f.read()
        except Exception as e:
            return json.dumps({
                "status": "error",
                "error": f"Could not read existing file: {e}"
            })

    diff_str = generate_diff(original_text, new_content, target.name)

    if dry_run:
        return json.dumps({
            "status": "preview",
            "file_path": str(target),
            "is_new_file": is_new_file,
            "diff": diff_str
        })

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(new_content)

        return json.dumps({
            "status": "applied",
            "file_path": str(target),
            "is_new_file": is_new_file,
            "diff": diff_str,
            "bytes_written": len(new_content.encode("utf-8"))
        })
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error": f"Failed to write file: {str(e)}"
        })
