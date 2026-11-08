"""Previous Conversation Context Retriever for AIRA 2.0.

Provides cross-session conversation retrieval, topic-based chat search,
and conversational continuity across restarts and separate interfaces.
"""

import re
from typing import List, Dict, Any, Optional, Set
from src.memory.repository import MemoryRepository
from src.context.context_models import ConversationExcerpt


class ConversationContextRetriever:
    """Searches and retrieves relevant turns from past conversations."""

    def __init__(self, repo: MemoryRepository):
        self.repo = repo

    def retrieve_previous_conversations(
        self,
        prompt: str,
        current_session_id: Optional[str] = None,
        project_id: Optional[str] = None,
        max_excerpts: int = 6,
    ) -> List[ConversationExcerpt]:
        """Retrieves relevant conversation excerpts from previous sessions."""
        clean_lower = prompt.lower().strip()

        # Check if the prompt is asking about past discussions, decisions, or continuations
        is_continuation = any(
            w in clean_lower
            for w in [
                "yesterday", "last time", "we discussed", "we decided", "you said",
                "earlier", "previous conversation", "continue", "resume", "our discussion",
                "what did we", "do you remember", "as mentioned before"
            ]
        )

        # Extract search keywords
        raw_words = re.findall(r"\b[a-zA-Z0-9_-]{4,}\b", clean_lower)
        keywords = [
            w for w in raw_words
            if w not in ("what", "which", "where", "when", "about", "could", "would", "should", "there", "their")
        ]

        excerpts: List[ConversationExcerpt] = []

        # 1. Topic-matched message retrieval from previous conversations
        if keywords or is_continuation:
            sql = """
                SELECT id, conversation_id, role, content, created_at
                FROM messages
                WHERE conversation_id != ?
            """
            params: List[Any] = [current_session_id or ""]

            if keywords:
                # Build LIKE clauses for the top keywords
                like_clauses = ["content LIKE ?"] * min(len(keywords), 4)
                sql += f" AND ({' OR '.join(like_clauses)})"
                for kw in keywords[:4]:
                    params.append(f"%{kw}%")

            sql += " ORDER BY id DESC LIMIT 15;"

            try:
                with self.repo.db.connection() as conn:
                    rows = conn.execute(sql, tuple(params)).fetchall()
                    for r in rows:
                        excerpts.append(
                            ConversationExcerpt(
                                conversation_id=r["conversation_id"],
                                role=r["role"],
                                content=r["content"][:400],
                                timestamp=r["created_at"],
                            )
                        )
            except Exception:
                pass

        # 2. If continuation requested but no keyword hits, fetch the most recent prior conversation turns
        if is_continuation and not excerpts:
            try:
                # Find the most recent conversation before current_session_id
                with self.repo.db.connection() as conn:
                    recent_conv = conn.execute(
                        """
                        SELECT id FROM conversations
                        WHERE id != ?
                        ORDER BY updated_at DESC
                        LIMIT 1;
                        """,
                        (current_session_id or "",),
                    ).fetchone()

                    if recent_conv:
                        prior_cid = recent_conv["id"]
                        recent_msgs = conn.execute(
                            """
                            SELECT id, conversation_id, role, content, created_at
                            FROM messages
                            WHERE conversation_id = ?
                            ORDER BY id DESC
                            LIMIT ?;
                            """,
                            (prior_cid, max_excerpts),
                        ).fetchall()

                        for r in reversed(recent_msgs):
                            excerpts.append(
                                ConversationExcerpt(
                                    conversation_id=r["conversation_id"],
                                    role=r["role"],
                                    content=r["content"][:400],
                                    timestamp=r["created_at"],
                                )
                            )
            except Exception:
                pass

        # Deduplicate while preserving chronological order
        seen = set()
        unique_excerpts: List[ConversationExcerpt] = []
        for e in excerpts:
            key = (e.conversation_id, e.role, e.content[:100])
            if key not in seen:
                seen.add(key)
                unique_excerpts.append(e)

        return unique_excerpts[:max_excerpts]
