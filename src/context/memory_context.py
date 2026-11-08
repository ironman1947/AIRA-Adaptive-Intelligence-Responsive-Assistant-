"""Personal Memory Context Retriever and Extractor for AIRA 2.0.

Retrieves relevant profile items, preferences, semantic facts, and episodic events
across persistent storage without leaking credentials or cross-user data.
"""

import re
from typing import List, Dict, Any, Optional, Set
from src.memory.repository import MemoryRepository
from src.memory.models import EpisodicMemory, SemanticMemory, UserPreference
from src.context.context_models import MemoryItem


# Stopwords to filter during memory keyword matching
STOP_WORDS = {
    "what", "which", "where", "when", "who", "whom", "whose", "why", "how",
    "is", "am", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "doing",
    "a", "an", "the", "and", "but", "if", "or", "because", "as", "until", "while",
    "of", "at", "by", "for", "with", "about", "against", "between", "into", "through",
    "during", "before", "after", "above", "below", "to", "from", "up", "down", "in", "out",
    "on", "off", "over", "under", "again", "further", "then", "once",
    "here", "there", "all", "any", "both", "each", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too",
    "very", "s", "t", "can", "will", "just", "don", "should", "now",
    "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you", "your",
    "tell", "know", "recall", "remember", "think", "please", "discuss", "discussed"
}

# Secret detection regex to prevent saving credentials into memory
SECRET_PATTERN = re.compile(
    r"(?:api[_-]?key|token|password|secret|bearer\s+[a-zA-Z0-9_\-\.]{15,}|ghp_[a-zA-Z0-9]{20,}|sk-[a-zA-Z0-9]{20,})",
    re.IGNORECASE
)


class MemoryContextRetriever:
    """Retrieves and ranks personal memories relevant to a user request."""

    def __init__(self, repo: MemoryRepository):
        self.repo = repo

    def extract_keywords(self, text: str) -> Set[str]:
        """Extracts normalized keywords from prompt, filtering punctuation and stopwords."""
        words = re.findall(r"\b[a-zA-Z0-9_-]{3,}\b", text.lower())
        return {w for w in words if w not in STOP_WORDS}

    def retrieve_relevant_memories(
        self,
        prompt: str,
        user_id: str = "default_user",
        project_id: Optional[str] = None,
        max_items: int = 6
    ) -> List[MemoryItem]:
        """Searches across user profile, preferences, semantic facts, and episodic events."""
        clean_lower = prompt.lower().strip()
        keywords = self.extract_keywords(prompt)

        candidates: List[MemoryItem] = []

        is_project_query = any(w in clean_lower for w in ["project", "working on", "current work", "repo", "architecture", "plan"])
        is_pref_query = any(w in clean_lower for w in ["preference", "prefer", "like", "favorite", "style", "setting"])
        is_identity_query = any(w in clean_lower for w in ["who am i", "my name", "my role", "my background", "my bio", "about me"])
        is_decision_query = any(w in clean_lower for w in ["decide", "decision", "discussed", "agreed", "yesterday", "earlier", "previously"])

        # 1. Search User Profile
        try:
            profile_items = self.repo.get_profile()
            for key, item in profile_items.items():
                if not item.value:
                    continue
                score = 0.0
                k_lower = key.lower()
                v_lower = str(item.value).lower()

                if is_identity_query or any(w in k_lower or w in v_lower for w in keywords):
                    score = 0.8
                elif any(w in k_lower for w in ["name", "role", "profession", "tech_stack", "preferred_language"]):
                    if is_project_query or is_identity_query:
                        score = 0.7

                if score > 0:
                    candidates.append(
                        MemoryItem(
                            category="profile",
                            title=key.replace("_", " ").title(),
                            content=str(item.value),
                            importance=score,
                            source_id=item.id,
                        )
                    )
        except Exception as e:
            pass

        # 2. Search User Preferences
        try:
            prefs = self.repo.list_preferences()
            for p in prefs:
                score = 0.0
                pk_lower = p.preference_key.lower()
                pv_lower = str(p.preference_value).lower()

                if is_pref_query or any(w in pk_lower or w in pv_lower for w in keywords):
                    score = 0.85
                elif is_project_query and any(tech in pv_lower for tech in ["python", "fastapi", "react", "sqlite", "git"]):
                    score = 0.65

                if score > 0:
                    candidates.append(
                        MemoryItem(
                            category="preference",
                            title=p.preference_key.replace("_", " ").title(),
                            content=str(p.preference_value),
                            importance=score,
                            source_id=p.id,
                        )
                    )
        except Exception:
            pass

        # 3. Search Semantic Memories (Verified facts & statements)
        try:
            semantic_list = self.repo.get_semantic_memories(project_id=project_id, limit=30)
            for sm in semantic_list:
                score = 0.0
                subj_lower = sm.subject.lower()
                content_lower = sm.content.lower()

                match_count = sum(1 for w in keywords if w in subj_lower or w in content_lower)
                if match_count > 0:
                    score = 0.5 + (0.15 * min(match_count, 3))
                elif is_project_query and ("project" in subj_lower or (sm.project_id and sm.project_id == project_id)):
                    score = 0.6

                if score > 0.4:
                    candidates.append(
                        MemoryItem(
                            category="semantic",
                            title=sm.subject,
                            content=sm.content,
                            importance=score,
                            project_id=sm.project_id,
                            source_id=sm.id,
                        )
                    )
        except Exception:
            pass

        # 4. Search Episodic Memories (Past discussions, decisions, milestones)
        try:
            episodic_list = self.repo.get_episodic_memories(project_id=project_id, limit=30)
            for ep in episodic_list:
                score = 0.0
                title_lower = ep.title.lower()
                content_lower = ep.content.lower()

                match_count = sum(1 for w in keywords if w in title_lower or w in content_lower)
                if match_count > 0:
                    score = 0.55 + (0.15 * min(match_count, 3))
                elif is_decision_query and any(dw in content_lower or dw in title_lower for dw in ["decid", "agreed", "plan", "chose", "architect"]):
                    score = 0.85
                elif is_project_query and ep.project_id:
                    score = 0.6

                if score > 0.45:
                    candidates.append(
                        MemoryItem(
                            category="episodic",
                            title=ep.title,
                            content=ep.content,
                            importance=score,
                            project_id=ep.project_id,
                            timestamp=ep.created_at,
                            source_id=ep.id,
                        )
                    )
        except Exception:
            pass

        # Deduplicate and sort by importance descending
        seen_contents = set()
        unique_candidates: List[MemoryItem] = []
        for c in sorted(candidates, key=lambda x: x.importance, reverse=True):
            clean_c = c.content.strip()
            if clean_c not in seen_contents:
                seen_contents.add(clean_c)
                unique_candidates.append(c)

        return unique_candidates[:max_items]

    def extract_and_persist_interaction_memory(
        self,
        prompt: str,
        response: str,
        session_id: str,
        project_id: Optional[str] = None,
    ) -> Optional[EpisodicMemory]:
        """Selectively extracts meaningful decisions or stated preferences into persistent memory."""
        # Check for credentials or secrets - never store secrets in memory
        if SECRET_PATTERN.search(prompt) or SECRET_PATTERN.search(response):
            return None

        # Do not save trivial queries or short banter
        if len(prompt.strip()) < 15 or len(response.strip()) < 25:
            return None

        clean_lower = prompt.lower()

        # 1. Explicit preference statement
        pref_match = re.search(r"\b(?:i\s+prefer|i\s+like|my\s+favorite|always\s+use)\s+([a-zA-Z0-9_\-\s]{3,30})", clean_lower)
        if pref_match:
            pref_val = pref_match.group(1).strip()
            try:
                self.repo.add_preference(
                    UserPreference(
                        preference_key="user_interest",
                        preference_value=pref_val,
                        is_explicit=True,
                        user_approved=True,
                    )
                )
            except Exception:
                pass

        # 2. Decision or architectural milestone
        is_decision = bool(re.search(r"\b(?:we\s+decided|i\s+decided|let'?s\s+go\s+with|the\s+plan\s+is|agreed\s+on)\b", clean_lower))
        if is_decision or len(prompt) > 40:
            title = prompt[:50].strip()
            content = f"User inquired: '{prompt[:150]}'\nOutcome: {response[:350]}"
            memory = EpisodicMemory(
                session_id=session_id,
                project_id=project_id,
                title=title,
                content=content,
                event_type="conversation_turn",
                importance=0.75 if is_decision else 0.5,
            )
            try:
                return self.repo.add_episodic(memory)
            except Exception:
                return None

        return None
