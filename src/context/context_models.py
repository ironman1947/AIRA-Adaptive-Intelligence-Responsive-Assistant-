"""Context data models for AIRA 2.0 Unified Context Retrieval Architecture."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional


def utc_now_iso() -> str:
    """Returns current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MemoryItem:
    """Represents a retrieved persistent memory record."""
    category: str  # profile, preference, semantic, episodic, procedural
    title: str
    content: str
    importance: float = 0.5
    timestamp: Optional[str] = None
    project_id: Optional[str] = None
    source_id: Optional[str] = None


@dataclass
class ConversationExcerpt:
    """Represents an excerpt from a previous or current conversation."""
    conversation_id: str
    role: str
    content: str
    timestamp: str
    project_id: Optional[str] = None
    turn_index: Optional[int] = None


@dataclass
class DocumentChunkExcerpt:
    """Represents an excerpt from an indexed Knowledge Base / RAG document."""
    document_id: str
    filename: str
    page_or_section: str
    content: str
    citation: str
    score: float = 0.0
    project_id: Optional[str] = None


@dataclass
class WebResearchExcerpt:
    """Represents an excerpt or full page content retrieved from live web research."""
    title: str
    url: str
    snippet: str
    full_content: Optional[str] = None
    retrieved_at: str = field(default_factory=utc_now_iso)
    source_type: str = "web_search"  # web_search, documentation, article


@dataclass
class ContextPackage:
    """Structured context package combining all authorized retrieval sources."""
    user_request: str
    session_id: Optional[str] = None
    user_id: Optional[str] = "default_user"
    project_id: Optional[str] = None
    privacy_mode: str = "standard"

    # Retrieved components
    personal_memories: List[MemoryItem] = field(default_factory=list)
    conversation_excerpts: List[ConversationExcerpt] = field(default_factory=list)
    project_summary: Optional[str] = None
    session_continuity: Optional[str] = None
    document_excerpts: List[DocumentChunkExcerpt] = field(default_factory=list)
    web_research_results: List[WebResearchExcerpt] = field(default_factory=list)

    # Metadata & Observability
    sources_used: List[str] = field(default_factory=list)
    citations: List[str] = field(default_factory=list)
    contradictions: List[str] = field(default_factory=list)
    retrieval_timestamps: Dict[str, str] = field(default_factory=dict)
    confidence_scores: Dict[str, float] = field(default_factory=dict)
    latencies_ms: Dict[str, float] = field(default_factory=dict)

    @property
    def has_evidence(self) -> bool:
        """Indicates whether any authorized external or persistent evidence was retrieved."""
        return bool(
            self.personal_memories
            or self.conversation_excerpts
            or self.document_excerpts
            or self.web_research_results
            or self.project_summary
        )

    def get_all_citations(self) -> List[str]:
        """Returns deduplicated citations across documents and web sources."""
        cites = list(self.citations)
        for doc in self.document_excerpts:
            if doc.citation and doc.citation not in cites:
                cites.append(doc.citation)
        for web in self.web_research_results:
            c_tag = f"[{web.title}]({web.url})"
            if c_tag not in cites:
                cites.append(c_tag)
        return list(dict.fromkeys(cites))

    def format_prompt_context(self, max_chars: int = 12000) -> str:
        """Compiles retrieved context into structured Markdown sections for the LLM prompt."""
        sections = []

        # 1. Personal Memories & User Preferences
        if self.personal_memories:
            mem_lines = ["### Persistent User Context & Personal Memory:"]
            for m in self.personal_memories:
                mem_lines.append(f"- **[{m.category.upper()}] {m.title}:** {m.content}")
            sections.append("\n".join(mem_lines))

        # 2. Project Context
        if self.project_summary:
            sections.append(f"### Active Project Workspace Context:\n{self.project_summary}")

        # 3. Session Continuity & Prior Decisions
        if self.session_continuity:
            sections.append(f"### Prior Session Continuity & State:\n{self.session_continuity}")

        # 4. Previous Conversation Excerpts
        if self.conversation_excerpts:
            conv_lines = ["### Relevant Previous Conversation Excerpts:"]
            for c in self.conversation_excerpts:
                conv_lines.append(f"- **{c.role.title()}** ({c.conversation_id}): {c.content}")
            sections.append("\n".join(conv_lines))

        # 5. Grounded Document Evidence (RAG)
        if self.document_excerpts:
            doc_lines = ["### Grounded Knowledge Base Document Evidence (from uploaded files):"]
            for d in self.document_excerpts:
                doc_lines.append(f"- **Source {d.citation}:**\n  {d.content}")
            sections.append("\n".join(doc_lines))

        # 6. Live Web Research & Browser Evidence
        if self.web_research_results:
            web_lines = ["### Grounded Internet Evidence (Live Web Research & Browser):"]
            for w in self.web_research_results:
                body = w.full_content or w.snippet
                web_lines.append(f"- **Source: [{w.title}]({w.url})** (Retrieved: {w.retrieved_at[:19]}):\n  {body[:1000]}")
            sections.append("\n".join(web_lines))

        # 7. Contradictions or Discrepancies
        if self.contradictions:
            disc_lines = ["### Observed Discrepancies Across Sources:"]
            for disc in self.contradictions:
                disc_lines.append(f"- ⚠️ {disc}")
            sections.append("\n".join(disc_lines))

        # 8. Grounding Directives
        if sections:
            sections.append(
                "### INSTRUCTIONS FOR USING RETRIEVED CONTEXT:\n"
                "- Treat retrieved personal memories, project facts, and previous decisions as verified truth.\n"
                "- Never respond with 'I don't have access to that information' when the answer is present above.\n"
                "- Ground all claims about uploaded documents or web research directly in the cited passages.\n"
                "- Cite web sources with Markdown links `[Title](URL)` and document sources with `[Filename | Section]`.\n"
                "- If the retrieved evidence does not contain the answer, state clearly what could not be found."
            )

        full_text = "\n\n".join(sections)
        if len(full_text) > max_chars:
            return full_text[:max_chars] + "\n...[Additional context truncated for length]"
        return full_text
