"""Knowledge and Research Subsystem for AIRA."""

from .citations import CitationValidator
from .router import KnowledgeRouter, KnowledgeRouteDecision
from .research import InternetResearchEngine
from .engine import UnifiedKnowledgeEngine, KnowledgeBundle

__all__ = [
    "CitationValidator",
    "KnowledgeRouter",
    "KnowledgeRouteDecision",
    "InternetResearchEngine",
    "UnifiedKnowledgeEngine",
    "KnowledgeBundle",
]
