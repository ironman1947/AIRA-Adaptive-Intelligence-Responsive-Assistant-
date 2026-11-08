"""AIRA 2.0 Unified Context Management Subsystem."""

from .user_profile import UserProfileManager
from .project_context import ProjectContextManager
from .session_continuity import SessionContinuityEngine
from .context_models import (
    ContextPackage,
    MemoryItem,
    ConversationExcerpt,
    DocumentChunkExcerpt,
    WebResearchExcerpt,
)
from .memory_context import MemoryContextRetriever
from .conversation_context import ConversationContextRetriever
from .knowledge_context import KnowledgeContextRetriever
from .web_context import WebContextRetriever
from .manager import UnifiedContextManager
from .builder import ContextBuilder

__all__ = [
    "UserProfileManager",
    "ProjectContextManager",
    "SessionContinuityEngine",
    "ContextPackage",
    "MemoryItem",
    "ConversationExcerpt",
    "DocumentChunkExcerpt",
    "WebResearchExcerpt",
    "MemoryContextRetriever",
    "ConversationContextRetriever",
    "KnowledgeContextRetriever",
    "WebContextRetriever",
    "UnifiedContextManager",
    "ContextBuilder",
]
