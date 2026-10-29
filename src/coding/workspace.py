"""Coding coworker: Authorized workspace inspection and file reading."""

import os
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

IGNORED_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", ".idea", ".vscode"}

def get_workspace_tree(root_dir: str, max_depth: int = 3) -> Dict[str, Any]:
    """Generates a tree summary of the authorized workspace."""
    root = Path(root_dir).resolve()
    if not root.is_dir():
        return {"error": f"Workspace directory not found: {root_dir}"}

    def _scan(current: Path, depth: int) -> List[Dict[str, Any]]:
        if depth > max_depth:
            return []
        items = []
        try:
            for entry in sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if entry.name in IGNORED_DIRS or entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    items.append({
                        "name": entry.name,
                        "type": "directory",
                        "children": _scan(entry, depth + 1)
                    })
                else:
                    items.append({
                        "name": entry.name,
                        "type": "file",
                        "size_bytes": entry.stat().st_size
                    })
        except PermissionError:
            pass
        return items

    return {
        "workspace_root": str(root),
        "structure": _scan(root, 1)
    }

def read_workspace_file(
    file_path: str,
    root_dir: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None
) -> str:
    """Safely reads a file within the authorized workspace."""
    root = Path(root_dir).resolve()
    target = Path(file_path).resolve()

    if not target.is_relative_to(root):
        return json.dumps({
            "status": "error",
            "error": f"Access denied: path '{file_path}' is outside authorized workspace '{root_dir}'."
        })

    if not target.is_file():
        return json.dumps({
            "status": "error",
            "error": f"File not found: '{file_path}'."
        })

    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total_lines = len(lines)
        s = max(1, start_line) if start_line else 1
        e = min(total_lines, end_line) if end_line else total_lines

        selected_lines = lines[s - 1:e]
        numbered_lines = [f"{idx}: {line}" for idx, line in enumerate(selected_lines, start=s)]

        return json.dumps({
            "status": "success",
            "file_path": str(target),
            "total_lines": total_lines,
            "start_line": s,
            "end_line": e,
            "content": "".join(numbered_lines)
        })
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error": f"Failed to read file: {str(e)}"
        })
