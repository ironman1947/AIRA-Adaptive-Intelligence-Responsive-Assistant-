from .internet import search_web, fetch_webpage, SEARCH_WEB_SCHEMA, FETCH_WEBPAGE_SCHEMA
from .logic_eval import evaluate_logic, EVALUATE_LOGIC_SCHEMA
from .registry import ToolRegistry, ToolDefinition

# Legacy backwards compatibility dictionaries
AVAILABLE_TOOLS = {
    "search_web": search_web,
    "fetch_webpage": fetch_webpage,
    "evaluate_logic": evaluate_logic,
}

TOOL_SCHEMAS = [
    SEARCH_WEB_SCHEMA,
    FETCH_WEBPAGE_SCHEMA,
    EVALUATE_LOGIC_SCHEMA,
]

__all__ = [
    "search_web",
    "fetch_webpage",
    "evaluate_logic",
    "ToolRegistry",
    "ToolDefinition",
    "AVAILABLE_TOOLS",
    "TOOL_SCHEMAS",
]