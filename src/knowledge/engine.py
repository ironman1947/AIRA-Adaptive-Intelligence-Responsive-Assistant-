"""Unified Knowledge Engine for AIRA.

Coordinates across:
1. General Model Knowledge
2. Persistent User Memory
3. Project Workspace Context
4. Uploaded Document RAG
5. Live Internet Research

Enforces source grounding, contradiction detection, citation verification,
and local-only privacy compliance.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

from src.knowledge.router import KnowledgeRouter, KnowledgeRouteDecision
from src.knowledge.research import InternetResearchEngine
from src.knowledge.citations import CitationValidator
from src.rag.store import RAGKnowledgeStore, get_rag_store
from src.memory.repository import MemoryRepository
from src.context.project_context import ProjectContextManager

@dataclass
class KnowledgeBundle:
    decision: KnowledgeRouteDecision
    rag_chunks: List[Dict[str, Any]] = field(default_factory=list)
    web_sources: List[Dict[str, Any]] = field(default_factory=list)
    semantic_memories: List[str] = field(default_factory=list)
    project_context: Optional[str] = None
    contradictions: List[str] = field(default_factory=list)
    citations: List[str] = field(default_factory=list)
    sources_used: List[str] = field(default_factory=list)
    prompt_context_text: str = ""

    def validate_answer_citations(self, answer_text: str) -> Tuple[bool, List[str], List[str]]:
        """Verifies that citations in the generated answer refer to real evidence."""
        all_sources = []
        for ch in self.rag_chunks:
            all_sources.append({
                "filename": ch.get("filename"),
                "citation": ch.get("citation"),
            })
        for ws in self.web_sources:
            all_sources.append({
                "title": ws.get("title"),
                "url": ws.get("url"),
            })
        return CitationValidator.validate_citations(answer_text, all_sources)

class UnifiedKnowledgeEngine:
    """Central engine orchestrating knowledge retrieval and verification."""

    def __init__(
        self,
        rag_store: Optional[RAGKnowledgeStore] = None,
        memory_repo: Optional[MemoryRepository] = None,
        project_mgr: Optional[ProjectContextManager] = None,
        research_engine: Optional[InternetResearchEngine] = None,
        router: Optional[KnowledgeRouter] = None,
    ):
        self.rag_store = rag_store or get_rag_store()
        self.memory_repo = memory_repo
        self.project_mgr = project_mgr
        self.research_engine = research_engine or InternetResearchEngine()
        self.router = router or KnowledgeRouter()

    async def gather_knowledge(
        self,
        prompt: str,
        project_id: Optional[str] = None,
        privacy_mode: str = "standard",
        intent: Optional[Any] = None,
    ) -> KnowledgeBundle:
        """Determines required knowledge sources, executes retrieval, and bundles verified context."""
        has_docs = False
        try:
            doc_list = self.rag_store.list_documents(project_id=project_id)
            has_docs = len(doc_list) > 0
        except Exception:
            pass

        decision = self.router.evaluate(
            prompt=prompt,
            intent=intent,
            project_id=project_id,
            privacy_mode=privacy_mode,
            has_indexed_docs=has_docs,
        )

        bundle = KnowledgeBundle(decision=decision)

        # 1. RAG Document Retrieval
        if decision.use_rag:
            try:
                chunks = self.rag_store.search(
                    query=prompt,
                    top_k=4,
                    project_id=project_id,
                    threshold=0.08
                )
                bundle.rag_chunks = chunks
                if chunks:
                    bundle.sources_used.append(f"RAG Documents ({len(chunks)} passages)")
                    for ch in chunks:
                        bundle.citations.append(ch["citation"])
            except Exception as e:
                print(f"⚠️ [KnowledgeEngine] RAG search error: {e}")

        # 2. Live Internet Research (Blocked in Local-Only mode)
        if decision.use_web_research and privacy_mode != "local_only":
            queries = decision.search_queries if decision.search_queries else [prompt]
            try:
                web_results, contradictions = self.research_engine.multi_query_research(
                    queries=queries,
                    max_per_query=3,
                    fetch_pages_per_query=1,
                )
                bundle.web_sources = web_results
                bundle.contradictions = contradictions
                if web_results:
                    bundle.sources_used.append(f"Live Web Research ({len(web_results)} sources)")
                    for w in web_results:
                        bundle.citations.append(f"[{w['title']}]({w['url']})")
            except Exception as e:
                print(f"⚠️ [KnowledgeEngine] Web research error: {e}")

        # 3. Project Context
        if decision.use_project_context and self.project_mgr and project_id:
            try:
                proj_ctx = self.project_mgr.get_project_prompt_summary(project_id)
                if proj_ctx:
                    bundle.project_context = proj_ctx
                    bundle.sources_used.append(f"Project Workspace Context ({project_id})")
            except Exception as e:
                print(f"⚠️ [KnowledgeEngine] Project context error: {e}")

        # 4. Compile Grounding Prompt Text
        context_parts = []
        if bundle.rag_chunks:
            context_parts.append("### Grounded Document Evidence (from your uploaded files):")
            for ch in bundle.rag_chunks:
                context_parts.append(f"- Source {ch['citation']}:\n  {ch['content']}")

        if bundle.web_sources:
            context_parts.append("\n### Grounded Internet Evidence (Live Web Research):")
            for ws in bundle.web_sources:
                body = ws.get("full_content") or ws.get("snippet", "")
                context_parts.append(f"- Source: [{ws['title']}]({ws['url']}) (Retrieved: {ws['retrieved_at'][:19]}):\n  {body[:500]}")

        if bundle.contradictions:
            context_parts.append("\n### Observed Discrepancies Across Sources:")
            for c in bundle.contradictions:
                context_parts.append(f"- ⚠️ {c}")

        if context_parts:
            context_parts.append(
                "\nINSTRUCTIONS FOR USING EVIDENCE:\n"
                "- Ground your factual statements in the evidence above.\n"
                "- Cite sources using standard Markdown links [Title](URL) for web or [Filename | Section] for internal documents.\n"
                "- Do NOT invent sources, URLs, or claims not present in the evidence.\n"
                "- If sources conflict or evidence is insufficient, explicitly state the uncertainty."
            )
            bundle.prompt_context_text = "\n".join(context_parts)

        bundle.citations = list(dict.fromkeys(bundle.citations))  # Deduplicate while preserving order
        return bundle
