"""Central Tool Registry for AIRA.

Each tool declares its execution handler, JSON schema, permission level,
risk level, and parameter validation.
"""

from dataclasses import dataclass
from typing import Callable, Dict, Any, List, Optional
import json

from src.tools.internet import (
    search_web,
    fetch_webpage,
    SEARCH_WEB_SCHEMA,
    FETCH_WEBPAGE_SCHEMA,
)
from src.tools.logic_eval import evaluate_logic, EVALUATE_LOGIC_SCHEMA
from src.coding import (
    get_workspace_tree,
    read_workspace_file,
    apply_workspace_edit,
    run_project_pytest,
    INSPECT_WORKSPACE_SCHEMA,
    READ_PROJECT_FILE_SCHEMA,
    APPLY_CODE_EDIT_SCHEMA,
    RUN_PROJECT_TESTS_SCHEMA,
)
from src.rag.store import get_rag_store
from src.memory.repository import MemoryRepository
from src.memory.models import EpisodicMemory, SemanticMemory

RAG_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "rag_search",
        "description": "Searches AIRA's indexed documents and technical knowledge base for relevant passages and citations.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to find in the document knowledge base."
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of relevant chunks to retrieve (default: 4).",
                    "default": 4
                }
            },
            "required": ["query"]
        }
    }
}

MANAGE_MEMORY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "manage_memory",
        "description": "Stores a notable event, user preference, or verified fact into AIRA's persistent memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "memory_type": {
                    "type": "string",
                    "enum": ["episodic", "semantic"],
                    "description": "Type of memory: episodic (event/decision) or semantic (factual knowledge)."
                },
                "title": {
                    "type": "string",
                    "description": "Short title or subject of the memory."
                },
                "content": {
                    "type": "string",
                    "description": "Detailed description or factual statement."
                }
            },
            "required": ["memory_type", "title", "content"]
        }
    }
}

@dataclass
class ToolDefinition:
    name: str
    description: str
    schema: Dict[str, Any]
    handler: Callable[..., Any]
    risk_level: str  # LOW, MEDIUM, HIGH, CRITICAL
    action_type: str

class ToolRegistry:
    def __init__(self, workspace_root: str, memory_repo: Optional[MemoryRepository] = None):
        self.workspace_root = workspace_root
        self.memory_repo = memory_repo
        self.rag_store = get_rag_store()
        self.tools: Dict[str, ToolDefinition] = {}
        self._register_default_tools()

    def _register_default_tools(self):
        # 1. Web Search
        self.register(
            ToolDefinition(
                name="search_web",
                description="Live internet search via DuckDuckGo",
                schema=SEARCH_WEB_SCHEMA,
                handler=lambda query, max_results=5: search_web(query, max_results=max_results),
                risk_level="LOW",
                action_type="SEARCH",
            )
        )

        # 2. Webpage Fetch
        self.register(
            ToolDefinition(
                name="fetch_webpage",
                description="Safe webpage reader with SSRF protection",
                schema=FETCH_WEBPAGE_SCHEMA,
                handler=lambda url: fetch_webpage(url),
                risk_level="MEDIUM",
                action_type="NETWORK_FETCH",
            )
        )

        # 3. Logic & Math Evaluation
        self.register(
            ToolDefinition(
                name="evaluate_logic",
                description="AST-based safe math and logic evaluator",
                schema=EVALUATE_LOGIC_SCHEMA,
                handler=lambda expression: evaluate_logic(expression),
                risk_level="LOW",
                action_type="READ",
            )
        )

        # 4. RAG Knowledge Search
        self.register(
            ToolDefinition(
                name="rag_search",
                description="Search internal RAG document index",
                schema=RAG_SEARCH_SCHEMA,
                handler=self._handle_rag_search,
                risk_level="LOW",
                action_type="READ",
            )
        )

        # 5. Workspace Directory Inspection
        self.register(
            ToolDefinition(
                name="inspect_workspace",
                description="Scan project directory structure",
                schema=INSPECT_WORKSPACE_SCHEMA,
                handler=lambda max_depth=3: json.dumps(get_workspace_tree(self.workspace_root, max_depth=max_depth)),
                risk_level="LOW",
                action_type="READ",
            )
        )

        # 6. Read Project File
        self.register(
            ToolDefinition(
                name="read_project_file",
                description="Read lines of a file within authorized workspace",
                schema=READ_PROJECT_FILE_SCHEMA,
                handler=lambda file_path, start_line=None, end_line=None: read_workspace_file(
                    file_path, self.workspace_root, start_line, end_line
                ),
                risk_level="LOW",
                action_type="READ",
            )
        )

        # 7. Apply Code Edit (High risk)
        self.register(
            ToolDefinition(
                name="apply_code_edit",
                description="Modify or create file in workspace with unified diff",
                schema=APPLY_CODE_EDIT_SCHEMA,
                handler=lambda file_path, new_content, dry_run=False: apply_workspace_edit(
                    file_path, new_content, self.workspace_root, dry_run=dry_run
                ),
                risk_level="HIGH",
                action_type="WRITE",
            )
        )

        # 8. Run Project Tests (High risk)
        self.register(
            ToolDefinition(
                name="run_project_tests",
                description="Run pytest suite in workspace",
                schema=RUN_PROJECT_TESTS_SCHEMA,
                handler=lambda test_path=None: run_project_pytest(self.workspace_root, test_path=test_path),
                risk_level="HIGH",
                action_type="EXECUTE",
            )
        )

        # 9. Manage Persistent Memory
        self.register(
            ToolDefinition(
                name="manage_memory",
                description="Persist episodic or semantic memory",
                schema=MANAGE_MEMORY_SCHEMA,
                handler=self._handle_manage_memory,
                risk_level="MEDIUM",
                action_type="MODIFY_MEMORY",
            )
        )

        # ----------------------------------------------------------------------
        # Desktop Control Subsystem Tools (Mac Capabilities & Approvals)
        # ----------------------------------------------------------------------
        from src.desktop.service import get_desktop_service
        desktop_svc = get_desktop_service()

        # 10. Desktop Inspect Directory (Read-only)
        self.register(
            ToolDefinition(
                name="desktop_inspect_directory",
                description="Inspect files, directories, and sizes in authorized macOS workspace",
                schema={
                    "type": "function",
                    "function": {
                        "name": "desktop_inspect_directory",
                        "description": "Inspects directory contents and hierarchy in authorized workspaces.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "directory_path": {"type": "string", "description": "Workspace directory path (optional)."},
                                "max_depth": {"type": "integer", "description": "Scan depth (default: 2)."}
                            }
                        }
                    }
                },
                handler=lambda directory_path=None, max_depth=2: json.dumps(desktop_svc.inspect_directory(directory_path, max_depth)),
                risk_level="LOW",
                action_type="READ",
            )
        )

        # 11. Desktop Find Files (Read-only)
        self.register(
            ToolDefinition(
                name="desktop_find_files",
                description="Search for files by glob pattern in authorized workspaces",
                schema={
                    "type": "function",
                    "function": {
                        "name": "desktop_find_files",
                        "description": "Searches for files matching a glob pattern (e.g. *.py, *.toml).",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "pattern": {"type": "string", "description": "Glob pattern."},
                                "directory_path": {"type": "string", "description": "Directory to search in."}
                            },
                            "required": ["pattern"]
                        }
                    }
                },
                handler=lambda pattern, directory_path=None: json.dumps(desktop_svc.find_files(pattern, directory_path)),
                risk_level="LOW",
                action_type="READ",
            )
        )

        # 12. Desktop Read File (Read-only)
        self.register(
            ToolDefinition(
                name="desktop_read_file",
                description="Safely read file lines in authorized workspace",
                schema={
                    "type": "function",
                    "function": {
                        "name": "desktop_read_file",
                        "description": "Reads lines of a code or document file in authorized workspace.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "file_path": {"type": "string", "description": "Path to file."},
                                "start_line": {"type": "integer", "description": "Start line number."},
                                "end_line": {"type": "integer", "description": "End line number."}
                            },
                            "required": ["file_path"]
                        }
                    }
                },
                handler=lambda file_path, start_line=None, end_line=None: json.dumps(desktop_svc.read_file(file_path, start_line, end_line)),
                risk_level="LOW",
                action_type="READ",
            )
        )

        # 13. Desktop System Diagnostics (Read-only)
        self.register(
            ToolDefinition(
                name="desktop_system_diagnostics",
                description="Read non-destructive macOS system diagnostics (OS, chip, CPU, disk, uptime)",
                schema={
                    "type": "function",
                    "function": {
                        "name": "desktop_system_diagnostics",
                        "description": "Returns macOS product version, CPU brand, disk usage, and uptime.",
                        "parameters": {"type": "object", "properties": {}}
                    }
                },
                handler=lambda: json.dumps(desktop_svc.get_system_diagnostics()),
                risk_level="LOW",
                action_type="READ",
            )
        )

        # 14. Desktop List Running Apps (Read-only)
        self.register(
            ToolDefinition(
                name="desktop_list_running_apps",
                description="List visible running applications on macOS",
                schema={
                    "type": "function",
                    "function": {
                        "name": "desktop_list_running_apps",
                        "description": "Lists running GUI applications on macOS.",
                        "parameters": {"type": "object", "properties": {}}
                    }
                },
                handler=lambda: json.dumps(desktop_svc.list_running_apps()),
                risk_level="LOW",
                action_type="READ",
            )
        )

        # 15. Desktop Open Application (Modifying - Requires Approval)
        self.register(
            ToolDefinition(
                name="desktop_open_application",
                description="Open approved macOS application with human approval requirement",
                schema={
                    "type": "function",
                    "function": {
                        "name": "desktop_open_application",
                        "description": "Launches an approved application (e.g. Safari, Notes, VS Code). Always asks user approval first.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "app_name": {"type": "string", "description": "Name of approved app."}
                            },
                            "required": ["app_name"]
                        }
                    }
                },
                handler=lambda app_name: json.dumps(desktop_svc.propose_app_launch(app_name).to_dict()),
                risk_level="MEDIUM",
                action_type="MODIFY",
            )
        )

        # 15b. Desktop Open URL (Requires Approval)
        self.register(
            ToolDefinition(
                name="desktop_open_url",
                description="Open verified public URL in an approved browser with human approval requirement",
                schema={
                    "type": "function",
                    "function": {
                        "name": "desktop_open_url",
                        "description": "Opens a verified public URL in a macOS browser (default: Safari). Requires human confirmation.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "url": {"type": "string", "description": "Public HTTP/HTTPS URL to open."},
                                "browser": {"type": "string", "description": "Browser application name (default: Safari).", "default": "Safari"}
                            },
                            "required": ["url"]
                        }
                    }
                },
                handler=lambda url, browser="Safari": json.dumps(desktop_svc.propose_open_url(url, browser).to_dict()),
                risk_level="MEDIUM",
                action_type="MODIFY",
            )
        )

        # 15c. Desktop Search YouTube (Requires Approval)
        self.register(
            ToolDefinition(
                name="desktop_search_youtube",
                description="Search for videos or music on YouTube with human approval requirement",
                schema={
                    "type": "function",
                    "function": {
                        "name": "desktop_search_youtube",
                        "description": "Searches YouTube for a topic, artist, or query and opens results in the browser upon approval.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "Search term or song/video query."}
                            },
                            "required": ["query"]
                        }
                    }
                },
                handler=lambda query: json.dumps(
                    desktop_svc.propose_open_url(desktop_svc.build_youtube_search_url(query), "Safari").to_dict()
                ),
                risk_level="MEDIUM",
                action_type="MODIFY",
            )
        )

        # 16. Desktop Modify File (Modifying - Requires Approval & Unified Diff)
        self.register(
            ToolDefinition(
                name="desktop_modify_file",
                description="Propose creating, modifying, or deleting a file with diff and mandatory approval",
                schema={
                    "type": "function",
                    "function": {
                        "name": "desktop_modify_file",
                        "description": "Proposes modifying a workspace file. Generates a unified diff and halts for approval before applying.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "file_path": {"type": "string", "description": "Path to target file."},
                                "new_content": {"type": "string", "description": "New file content."},
                                "explanation": {"type": "string", "description": "Clear explanation of what will change."},
                                "action_type": {"type": "string", "enum": ["edit", "create", "delete"], "description": "Type of change."}
                            },
                            "required": ["file_path", "new_content", "explanation"]
                        }
                    }
                },
                handler=lambda file_path, new_content, explanation, action_type="edit": json.dumps(
                    desktop_svc.propose_file_change(file_path, new_content, explanation, action_type).to_dict()
                ),
                risk_level="HIGH",
                action_type="WRITE",
            )
        )

    def _handle_rag_search(self, query: str, top_k: int = 4) -> str:
        results = self.rag_store.search(query, top_k=top_k)
        return json.dumps({
            "query": query,
            "count": len(results),
            "results": results
        })

    def _handle_manage_memory(self, memory_type: str, title: str, content: str) -> str:
        if not self.memory_repo:
            return json.dumps({"status": "error", "error": "Memory repository unavailable."})

        if memory_type == "episodic":
            item = self.memory_repo.add_episodic(
                EpisodicMemory(
                    title=title,
                    content=content,
                    event_type="interaction",
                    importance=0.7
                )
            )
            return json.dumps({"status": "saved", "type": "episodic", "id": item.id, "title": title})
        else:
            item = self.memory_repo.add_semantic(
                SemanticMemory(
                    subject=title,
                    predicate="relates_to",
                    object_value=content[:100],
                    content=content,
                    verification_status="verified",
                )
            )
            return json.dumps({"status": "saved", "type": "semantic", "id": item.id, "subject": title})

    def register(self, tool: ToolDefinition):
        self.tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        return self.tools.get(name)

    def get_schemas(self) -> List[Dict[str, Any]]:
        return [t.schema for t in self.tools.values()]

    def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        if name not in self.tools:
            return json.dumps({"error": f"Tool '{name}' not found in registry."})
        tool = self.tools[name]
        try:
            return tool.handler(**arguments)
        except Exception as e:
            return json.dumps({"error": f"Tool execution failed: {str(e)}"})
