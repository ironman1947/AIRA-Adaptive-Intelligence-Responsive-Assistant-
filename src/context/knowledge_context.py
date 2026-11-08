"""Knowledge Context Retriever for AIRA 2.0.

Provides intelligent RAG document retrieval supporting direct topic search,
document summarization, filename-specific lookups, and multi-document comparisons.
"""

import re
from typing import List, Dict, Any, Optional
from src.rag.store import RAGKnowledgeStore, get_rag_store
from src.context.context_models import DocumentChunkExcerpt


class KnowledgeContextRetriever:
    """Intelligently retrieves and aggregates relevant passages from uploaded documents."""

    def __init__(self, rag_store: Optional[RAGKnowledgeStore] = None):
        self.rag_store = rag_store or get_rag_store()

    def is_document_query(self, prompt: str, has_indexed_docs: bool = True) -> bool:
        """Determines if the prompt references uploaded documents or knowledge base."""
        clean_lower = prompt.lower()
        patterns = [
            r"\b(uploaded|document|doc|pdf|paper|report|manual|file|notes|specification|spec)\b",
            r"\b(knowledge\s+base|in\s+my\s+file|in\s+my\s+doc|according\s+to\s+the\s+doc)\b",
            r"\b(summarize\s+the\s+(document|file|paper|pdf|upload))\b",
            r"\b(what\s+does\s+the\s+(document|file|paper|pdf)\s+say)\b",
            r"\b(compare\s+(these|the)\s+(two\s+)?(documents|files|papers|reports))\b",
        ]
        return any(re.search(p, clean_lower) for p in patterns)

    def is_summarization_query(self, prompt: str) -> bool:
        """Checks if the user is asking for an overview or summary of an uploaded document."""
        clean_lower = prompt.lower()
        patterns = [
            r"\b(summarize|summary|overview|key\s+points|main\s+takeaways|what\s+is\s+it\s+about)\b",
            r"\b(what\s+does\s+my\s+(paper|document|file)\s+say)\b",
            r"\b(explain\s+my\s+(paper|document|file))\b",
        ]
        return any(re.search(p, clean_lower) for p in patterns)

    def extract_clean_search_terms(self, prompt: str) -> str:
        """Strips conversational boilerplate to isolate the core technical topic for RAG search."""
        clean = re.sub(
            r"^(what\s+does\s+my\s+(?:research\s+)?paper\s+say\s+about|what\s+does\s+the\s+document\s+say\s+about|find\s+the\s+information\s+about|summarize\s+what\s+is\s+written\s+about|tell\s+me\s+about|in\s+the\s+uploaded\s+document\s*,?\s*)\s*",
            "",
            prompt,
            flags=re.IGNORECASE,
        ).strip("?.!, ")

        # If stripping removed everything or query is too short, return the original
        if len(clean) < 3:
            return prompt
        return clean

    def retrieve_document_context(
        self,
        prompt: str,
        project_id: Optional[str] = None,
        top_k: int = 5,
    ) -> List[DocumentChunkExcerpt]:
        """Retrieves verified document excerpts using hybrid search, filename filtering, and summary aggregation."""
        docs = self.rag_store.list_documents(project_id=project_id)
        if not docs:
            return []

        clean_lower = prompt.lower()
        excerpts: List[DocumentChunkExcerpt] = []

        # 1. Check if a specific document is referenced by filename
        matched_doc = None
        for d in docs:
            fname = d["filename"].lower()
            base_name = fname.rsplit(".", 1)[0]
            if fname in clean_lower or (len(base_name) > 3 and base_name in clean_lower):
                matched_doc = d
                break

        # 2. If summarization is requested for a specific document or the only uploaded document
        if self.is_summarization_query(prompt) or (matched_doc and "summar" in clean_lower):
            target_doc_id = matched_doc["id"] if matched_doc else (docs[0]["id"] if len(docs) == 1 else None)
            if target_doc_id:
                chunks = self.rag_store.get_document_chunks(target_doc_id)
                # Take the first 3 chunks (introduction/overview) and last chunk (conclusion) if available
                summary_chunks = chunks[:3]
                if len(chunks) > 4:
                    summary_chunks.append(chunks[-1])

                for ch in summary_chunks:
                    excerpts.append(
                        DocumentChunkExcerpt(
                            document_id=target_doc_id,
                            filename=ch["filename"],
                            page_or_section=ch["page_or_section"],
                            content=ch["content"],
                            citation=f"[{ch['filename']} | {ch['page_or_section']}]",
                            score=1.0,
                            project_id=project_id,
                        )
                    )
                return excerpts[:top_k]

        # 3. Targeted semantic search using cleaned query terms
        search_query = self.extract_clean_search_terms(prompt)
        try:
            chunks = self.rag_store.search(
                query=search_query,
                top_k=top_k,
                project_id=project_id,
                threshold=0.03,  # Tolerant threshold for partial matches
            )
            for ch in chunks:
                excerpts.append(
                    DocumentChunkExcerpt(
                        document_id=ch["document_id"],
                        filename=ch["filename"],
                        page_or_section=ch["page_or_section"],
                        content=ch["content"],
                        citation=ch["citation"],
                        score=ch["score"],
                        project_id=ch.get("project_id"),
                    )
                )
        except Exception:
            pass

        # 4. Fallback: If 0 chunks found and document query was explicit, provide leading document passages
        if not excerpts and self.is_document_query(prompt):
            for d in docs[:2]:
                chunks = self.rag_store.get_document_chunks(d["id"])
                for ch in chunks[:2]:
                    excerpts.append(
                        DocumentChunkExcerpt(
                            document_id=d["id"],
                            filename=ch["filename"],
                            page_or_section=ch["page_or_section"],
                            content=ch["content"],
                            citation=f"[{ch['filename']} | {ch['page_or_section']}]",
                            score=0.5,
                            project_id=project_id,
                        )
                    )

        return excerpts[:top_k]
