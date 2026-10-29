from .workspace import get_workspace_tree, read_workspace_file
from .editor import generate_diff, apply_workspace_edit
from .tester import run_project_pytest

INSPECT_WORKSPACE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "inspect_workspace",
        "description": "Inspects the authorized workspace directory structure, listing files, subdirectories, and sizes.",
        "parameters": {
            "type": "object",
            "properties": {
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum directory traversal depth (default: 3).",
                    "default": 3
                }
            }
        }
    }
}

READ_PROJECT_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_project_file",
        "description": "Reads the lines of a code or documentation file within the authorized project workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Relative or absolute path to the file inside the project workspace."
                },
                "start_line": {
                    "type": "integer",
                    "description": "Optional starting line number (1-indexed)."
                },
                "end_line": {
                    "type": "integer",
                    "description": "Optional ending line number (1-indexed)."
                }
            },
            "required": ["file_path"]
        }
    }
}

APPLY_CODE_EDIT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "apply_code_edit",
        "description": "Applies a code edit to a file or creates a new file in the project workspace, showing a unified diff. High-risk: requires user confirmation unless pre-approved.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to create or edit."
                },
                "new_content": {
                    "type": "string",
                    "description": "Complete new content for the file."
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "If true, only returns a unified diff preview without modifying disk.",
                    "default": False
                }
            },
            "required": ["file_path", "new_content"]
        }
    }
}

RUN_PROJECT_TESTS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "run_project_tests",
        "description": "Runs pytest across the authorized project workspace to verify changes. Reports exact passing, failing, and error counts.",
        "parameters": {
            "type": "object",
            "properties": {
                "test_path": {
                    "type": "string",
                    "description": "Optional specific test file or directory to execute."
                }
            }
        }
    }
}

__all__ = [
    "get_workspace_tree",
    "read_workspace_file",
    "generate_diff",
    "apply_workspace_edit",
    "run_project_pytest",
    "INSPECT_WORKSPACE_SCHEMA",
    "READ_PROJECT_FILE_SCHEMA",
    "APPLY_CODE_EDIT_SCHEMA",
    "RUN_PROJECT_TESTS_SCHEMA",
]
