"""Context Package Builder and Prompt Formatter for AIRA 2.0."""

from typing import Dict, Any, List, Optional
from src.context.context_models import ContextPackage


class ContextBuilder:
    """Formats and optimizes context packages for LLM prompt ingestion."""

    @staticmethod
    def build_system_context(package: ContextPackage, token_budget_chars: int = 12000) -> str:
        """Constructs an integrated prompt context block enforcing token budgets."""
        return package.format_prompt_context(max_chars=token_budget_chars)

    @staticmethod
    def extract_diagnostic_summary(package: ContextPackage) -> Dict[str, Any]:
        """Extracts observability metrics and sources for debugging."""
        return {
            "has_evidence": package.has_evidence,
            "sources_used": package.sources_used,
            "citations_count": len(package.citations),
            "citations": package.citations,
            "personal_memories_count": len(package.personal_memories),
            "conversations_count": len(package.conversation_excerpts),
            "documents_count": len(package.document_excerpts),
            "web_sources_count": len(package.web_research_results),
            "latencies_ms": package.latencies_ms,
        }
