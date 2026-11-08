"""Unified Context Manager for AIRA 2.0.

Provides a unified, centralized context retrieval pipeline across Personal Memory,
Cross-Session Conversations, Project Workspaces, Knowledge Base (RAG), and Live Web Research.
"""

import time
import logging
from typing import Dict, Any, Optional, List

from src.memory.repository import MemoryRepository
from src.context.context_models import ContextPackage, utc_now_iso
from src.context.memory_context import MemoryContextRetriever
from src.context.conversation_context import ConversationContextRetriever
from src.context.project_context import ProjectContextManager
from src.context.session_continuity import SessionContinuityEngine
from src.context.knowledge_context import KnowledgeContextRetriever
from src.context.web_context import WebContextRetriever

logger = logging.getLogger("aira.context")


class UnifiedContextManager:
    """Central orchestrator for all authorized context retrieval in AIRA."""

    def __init__(
        self,
        memory_repo: MemoryRepository,
        project_mgr: Optional[ProjectContextManager] = None,
        session_mgr: Optional[SessionContinuityEngine] = None,
        knowledge_retriever: Optional[KnowledgeContextRetriever] = None,
        web_retriever: Optional[WebContextRetriever] = None,
    ):
        self.repo = memory_repo
        self.memory_retriever = MemoryContextRetriever(memory_repo)
        self.conversation_retriever = ConversationContextRetriever(memory_repo)
        self.project_mgr = project_mgr or ProjectContextManager(memory_repo)
        self.session_mgr = session_mgr or SessionContinuityEngine(memory_repo)
        self.knowledge_retriever = knowledge_retriever or KnowledgeContextRetriever()
        self.web_retriever = web_retriever or WebContextRetriever()

    def assemble_context(
        self,
        prompt: str,
        user_id: str = "default_user",
        session_id: Optional[str] = None,
        project_id: Optional[str] = None,
        privacy_mode: str = "standard",
        intent: Optional[Any] = None,
    ) -> ContextPackage:
        """Executes targeted context retrieval and constructs a unified ContextPackage."""
        overall_start = time.perf_counter()
        clean_lower = prompt.lower().strip()

        package = ContextPackage(
            user_request=prompt,
            session_id=session_id,
            user_id=user_id,
            project_id=project_id,
            privacy_mode=privacy_mode,
        )

        intent_cat = getattr(intent, "category", None) if intent else None
        is_greeting_or_intro = intent_cat in ("greeting", "user_introduction", "time_date_query")

        # 1. Personal Memory Retrieval (skip for greetings/introductions/clock queries)
        t_start = time.perf_counter()
        if not is_greeting_or_intro:
            try:
                memories = self.memory_retriever.retrieve_relevant_memories(
                    prompt=prompt,
                    user_id=user_id,
                    project_id=project_id,
                    max_items=6,
                )
                package.personal_memories = memories
                if memories:
                    package.sources_used.append(f"Personal Memory ({len(memories)} items)")
            except Exception as e:
                logger.warning("Error retrieving personal memory: %s", e)
        package.latencies_ms["memory"] = round((time.perf_counter() - t_start) * 1000, 2)

        # 2. Previous Conversation Retrieval (Cross-session Continuity, skip for greetings)
        t_start = time.perf_counter()
        if not is_greeting_or_intro:
            try:
                conv_excerpts = self.conversation_retriever.retrieve_previous_conversations(
                    prompt=prompt,
                    current_session_id=session_id,
                    project_id=project_id,
                    max_excerpts=5,
                )
                package.conversation_excerpts = conv_excerpts
                if conv_excerpts:
                    package.sources_used.append(f"Previous Conversations ({len(conv_excerpts)} turns)")
            except Exception as e:
                logger.warning("Error retrieving previous conversations: %s", e)
        package.latencies_ms["conversations"] = round((time.perf_counter() - t_start) * 1000, 2)

        # 3. Project Workspace Context & Session Continuity
        t_start = time.perf_counter()
        active_proj = project_id
        if not active_proj:
            # Auto-detect if user refers to an existing project name
            all_projs = self.project_mgr.list_projects()
            for p in all_projs:
                if p.name.lower() in clean_lower or (p.id and p.id.lower() in clean_lower):
                    active_proj = p.id
                    break

        if active_proj:
            try:
                proj_summary = self.project_mgr.get_project_prompt_summary(active_proj)
                session_summary = self.session_mgr.get_latest_session_prompt_context(active_proj)
                package.project_summary = proj_summary
                package.session_continuity = session_summary
                if proj_summary:
                    package.sources_used.append(f"Project Context ({active_proj})")
            except Exception as e:
                logger.warning("Error retrieving project context: %s", e)
        package.latencies_ms["project"] = round((time.perf_counter() - t_start) * 1000, 2)

        # 4. Knowledge Base (RAG) Document Retrieval
        t_start = time.perf_counter()
        if self.knowledge_retriever.is_document_query(prompt):
            try:
                doc_excerpts = self.knowledge_retriever.retrieve_document_context(
                    prompt=prompt,
                    project_id=project_id,
                    top_k=5,
                )
                package.document_excerpts = doc_excerpts
                if doc_excerpts:
                    package.sources_used.append(f"Knowledge Base Documents ({len(doc_excerpts)} passages)")
                    for d in doc_excerpts:
                        package.citations.append(d.citation)
            except Exception as e:
                logger.warning("Error retrieving document context: %s", e)
        package.latencies_ms["rag"] = round((time.perf_counter() - t_start) * 1000, 2)

        # 5. Live Web Research & Browser Reading
        t_start = time.perf_counter()
        should_search_web = (
            self.web_retriever.is_current_info_query(prompt)
            or self.web_retriever.extract_url(prompt) is not None
            or (intent and getattr(intent, "needs_web_search", False))
        )
        if should_search_web:
            if privacy_mode == "local_only":
                package.sources_used.append("Web Research (Blocked by Local-Only Privacy Mode)")
            else:
                try:
                    web_results, contradictions = self.web_retriever.retrieve_web_context(
                        prompt=prompt,
                        privacy_mode=privacy_mode,
                        max_results=4,
                    )
                    package.web_research_results = web_results
                    package.contradictions = contradictions
                    if web_results:
                        package.sources_used.append(f"Live Web Research ({len(web_results)} sources)")
                        for w in web_results:
                            package.citations.append(f"[{w.title}]({w.url})")
                except Exception as e:
                    logger.warning("Error executing web research: %s", e)
        package.latencies_ms["web"] = round((time.perf_counter() - t_start) * 1000, 2)

        # Total latency & timestamps
        package.latencies_ms["total_context"] = round((time.perf_counter() - overall_start) * 1000, 2)
        package.retrieval_timestamps["assembled_at"] = utc_now_iso()
        package.citations = list(dict.fromkeys(package.citations))

        return package
