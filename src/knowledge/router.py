"""Knowledge Router for AIRA.

Determines which knowledge sources (Model Knowledge, User Memory,
Project Context, RAG Documents, Live Internet Research) are relevant
for a given user request, enforcing privacy boundaries and avoiding
unnecessary retrieval overhead for simple or casual dialogue.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from src.agent.intent import IntentCategory, ConversationalIntent

@dataclass
class KnowledgeRouteDecision:
    use_model_knowledge: bool = True
    use_user_memory: bool = False
    use_project_context: bool = False
    use_rag: bool = False
    use_web_research: bool = False
    is_hybrid: bool = False
    reasons: List[str] = field(default_factory=list)
    search_queries: List[str] = field(default_factory=list)
    privacy_mode: str = "standard"

    @property
    def reasoning(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "Direct model knowledge."

class KnowledgeRouter:
    """Intelligently routes requests to appropriate knowledge sources."""

    RAG_TRIGGER_PATTERNS = [
        re.compile(r"\b(uploaded|document|doc|pdf|notes|manual|guide|report|file|knowledge\s+base|dataset|index)\b", re.IGNORECASE),
        re.compile(r"\b(according\s+to\s+the\s+(doc|file|report|notes|document))\b", re.IGNORECASE),
        re.compile(r"\b(what\s+does\s+the\s+(doc|file|report|notes|document)\s+say)\b", re.IGNORECASE),
        re.compile(r"\b(in\s+my\s+(notes|documents|files|specs))\b", re.IGNORECASE),
    ]

    WEB_SEARCH_PATTERNS = [
        re.compile(r"\b(search\s+(the\s+)?web|search\s+for|look\s+up\s+online|google|internet)\b", re.IGNORECASE),
        re.compile(r"\b(latest|current|recent|today'?s|breaking|news|headline|now|stock\s+price|weather|release\s+date)\b", re.IGNORECASE),
        re.compile(r"\b(who\s+won|score\s+of|election|market|price\s+of)\b", re.IGNORECASE),
        re.compile(r"\b(current\s+version|latest\s+version|released\s+in\s+202[4-9]|in\s+202[5-9])\b", re.IGNORECASE),
    ]

    NO_RETRIEVAL_CATEGORIES = {
        IntentCategory.GREETING,
        IntentCategory.CASUAL,
        IntentCategory.USER_INTRODUCTION,
        IntentCategory.EMOTIONAL_SUPPORT,
        IntentCategory.CREATIVE,
        IntentCategory.SYSTEM_INQUIRY,
        IntentCategory.TIME_DATE_QUERY,
        IntentCategory.DESKTOP_ACTION,
    }

    def evaluate(
        self,
        prompt: str,
        intent: Optional[ConversationalIntent] = None,
        project_id: Optional[str] = None,
        privacy_mode: str = "standard",
        has_indexed_docs: bool = False,
    ) -> KnowledgeRouteDecision:
        """Evaluates a user prompt to determine required knowledge sources."""
        text = prompt.strip()
        clean_lower = text.lower()
        decision = KnowledgeRouteDecision(privacy_mode=privacy_mode)

        # 1. Greetings, user introductions, casual chit-chat, or direct system identity queries
        # Skip external retrieval ONLY if prompt does not contain explicit document, memory, or web triggers
        if intent and intent.category in self.NO_RETRIEVAL_CATEGORIES:
            is_rag_candidate = any(p.search(clean_lower) for p in self.RAG_TRIGGER_PATTERNS)
            has_memory_trigger = any(w in clean_lower for w in ["my preference", "remember", "i like", "i prefer", "you recall", "my background", "my name", "what project", "who am i", "my role", "my tech stack"])
            has_web_trigger = (intent and intent.needs_web_search) or any(p.search(clean_lower) for p in self.WEB_SEARCH_PATTERNS) or bool(re.search(r"https?://\S+", text))

            if not is_rag_candidate and not has_memory_trigger and not has_web_trigger:
                decision.reasons.append(f"Casual/conversational intent ({intent.category}); direct response without external retrieval.")
                return decision

        # 2. Check for RAG Document triggers
        is_rag_candidate = any(p.search(clean_lower) for p in self.RAG_TRIGGER_PATTERNS)
        if is_rag_candidate and (has_indexed_docs or "document" in clean_lower or "pdf" in clean_lower or "notes" in clean_lower):
            decision.use_rag = True
            decision.reasons.append("Query references indexed documents, notes, or knowledge base.")

        # 3. Check for Project context
        if project_id and (intent and intent.needs_project_context or any(w in clean_lower for w in ["project", "code", "architecture", "task", "workspace", "objective"])):
            decision.use_project_context = True
            decision.reasons.append(f"Query pertains to active project workspace '{project_id}'.")

        # 4. Check for Persistent User Memory
        if any(w in clean_lower for w in ["my preference", "remember", "i like", "i prefer", "you recall", "my background", "my name"]):
            decision.use_user_memory = True
            decision.reasons.append("Query references user preferences or personal memory.")

        # 5. Check for Web Research (subject to privacy mode!)
        needs_search = False
        if intent and intent.needs_web_search:
            needs_search = True
        elif any(p.search(clean_lower) for p in self.WEB_SEARCH_PATTERNS):
            needs_search = True

        if needs_search:
            if privacy_mode == "local_only":
                decision.use_web_research = False
                decision.reasons.append("Web search requested but blocked: Local-Only Privacy Policy is active.")
            else:
                decision.use_web_research = True
                decision.reasons.append("Query requires current, live, or external web information.")
                # Construct clean, bounded search queries
                clean_q = re.sub(
                    r"^(please\s+)?(research(\s+a\s+topic(\s+for\s+me)?)?(\s*:|\s+on|\s+about)?|find(\s+the)?(\s+latest)?\s+information\s+(on|about)?|investigate|search(\s+the\s+web|\s+for)?|look\s+up\s+(online|for)?|summarize\s+current\s+technical\s+guidance\s+(on|about)?)\s*[:,-]?\s*",
                    "",
                    text,
                    flags=re.IGNORECASE
                ).strip("?.,! ")
                clean_core = re.sub(r"^(what\s+are\s+the|what\s+is\s+the|tell\s+me\s+about|how\s+do\s+we)\s+", "", clean_q, flags=re.IGNORECASE).strip("?.,! ")

                # Bounded query formulation: extract key topic phrases
                queries = []
                if " and " in clean_core.lower():
                    parts = re.split(r"\s+and\s+", clean_core, flags=re.IGNORECASE)
                    for p in parts[:2]:
                        words = [w for w in p.strip().split() if w.lower() not in ("the", "latest", "best", "practices", "in", "of", "for", "a", "an", "to", "on", "with")]
                        if words:
                            queries.append(" ".join(words[:4]))

                words = [w for w in clean_core.split() if w.lower() not in ("the", "latest", "best", "practices", "in", "of", "for", "a", "an", "to", "on", "with")]
                if words:
                    queries.append(" ".join(words[:5]))
                if clean_core and clean_core not in queries:
                    queries.append(clean_core)

                decision.search_queries = list(dict.fromkeys(queries))[:3]

        # 6. Hybrid determination
        active_sources = [decision.use_rag, decision.use_web_research, decision.use_project_context]
        if sum(active_sources) > 1:
            decision.is_hybrid = True
            decision.reasons.append("Multi-source hybrid synthesis required across documents, project, or live web.")

        return decision
