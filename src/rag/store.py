"""RAG Vector and Semantic Retrieval Store for AIRA.

Provides persistent SQLite-backed chunk storage, TF-IDF / semantic vector indexing,
scoped project isolation, similarity filtering, and citation generation.
"""

import json
from datetime import datetime
from typing import List, Dict, Any, Optional
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from src.memory.database import DatabaseManager, get_db_manager
from src.rag.ingestion import process_document

class RAGKnowledgeStore:
    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or get_db_manager()

    def index_document(
        self,
        file_path: str,
        project_id: Optional[str] = None,
        privacy_level: str = "standard"
    ) -> Dict[str, Any]:
        """Ingests a document, extracts text and chunks, and saves to SQLite."""
        doc_data = process_document(
            file_path,
            project_id=project_id,
            privacy_level=privacy_level
        )

        with self.db.connection() as conn:
            # Check if document already exists
            existing = conn.execute(
                "SELECT id FROM rag_documents WHERE content_hash = ?;",
                (doc_data["content_hash"],)
            ).fetchone()

            if existing:
                doc_id = existing["id"]
                # Clean existing chunks before re-indexing
                conn.execute("DELETE FROM rag_chunks WHERE document_id = ?;", (doc_id,))
                conn.execute(
                    """
                    UPDATE rag_documents SET
                        filename = ?, file_type = ?, file_size = ?,
                        project_id = ?, privacy_level = ?, chunk_count = ?,
                        created_at = ?
                    WHERE id = ?;
                    """,
                    (
                        doc_data["filename"],
                        doc_data["file_type"],
                        doc_data["file_size"],
                        doc_data["project_id"],
                        doc_data["privacy_level"],
                        doc_data["chunk_count"],
                        datetime.now().isoformat(),
                        doc_id,
                    ),
                )
            else:
                doc_id = doc_data["id"]
                conn.execute(
                    """
                    INSERT INTO rag_documents (id, filename, file_type, file_size, content_hash, project_id, privacy_level, chunk_count, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        doc_id,
                        doc_data["filename"],
                        doc_data["file_type"],
                        doc_data["file_size"],
                        doc_data["content_hash"],
                        doc_data["project_id"],
                        doc_data["privacy_level"],
                        doc_data["chunk_count"],
                        datetime.now().isoformat(),
                    ),
                )

            # Insert chunks
            for ch in doc_data["chunks"]:
                conn.execute(
                    """
                    INSERT INTO rag_chunks (id, document_id, chunk_index, content, page_or_section, metadata, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        ch["id"],
                        doc_id,
                        ch["chunk_index"],
                        ch["content"],
                        ch["page_or_section"],
                        json.dumps(ch["metadata"]),
                        datetime.now().isoformat(),
                    ),
                )

        return {
            "document_id": doc_id,
            "filename": doc_data["filename"],
            "chunk_count": doc_data["chunk_count"],
            "status": "indexed"
        }

    def search(
        self,
        query: str,
        top_k: int = 5,
        project_id: Optional[str] = None,
        threshold: float = 0.05
    ) -> List[Dict[str, Any]]:
        """Performs semantic similarity search across indexed chunks using TF-IDF vectorization.

        Enforces project boundary filtering and minimum relevance threshold.
        """
        clean_query = query.strip()
        if not clean_query:
            return []

        # Fetch relevant chunks
        sql = """
            SELECT c.id, c.document_id, c.chunk_index, c.content, c.page_or_section, c.metadata, d.filename, d.project_id
            FROM rag_chunks c
            JOIN rag_documents d ON c.document_id = d.id
        """
        params = []
        if project_id:
            sql += " WHERE (d.project_id = ? OR d.project_id IS NULL)"
            params.append(project_id)

        with self.db.connection() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()

        if not rows:
            return []

        corpus = [r["content"] for r in rows]
        vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            stop_words="english",
            sublinear_tf=True
        )

        try:
            tfidf_matrix = vectorizer.fit_transform(corpus)
            query_vec = vectorizer.transform([clean_query])
            similarities = cosine_similarity(query_vec, tfidf_matrix).flatten()
        except ValueError:
            similarities = np.zeros(len(corpus))

        # Hybrid keyword overlap boost
        query_words = set(w.lower() for w in clean_query.split() if len(w) > 2)
        hybrid_scores = []
        for i, text in enumerate(corpus):
            base_sim = float(similarities[i])
            text_lower = text.lower()
            if query_words:
                matched_words = sum(1 for w in query_words if w in text_lower)
                kw_ratio = matched_words / len(query_words)
            else:
                kw_ratio = 0.0
            # Blend: 70% TF-IDF cosine similarity + 30% keyword match
            combined = 0.7 * base_sim + 0.3 * kw_ratio
            hybrid_scores.append(combined)

        hybrid_scores = np.array(hybrid_scores)
        top_indices = np.argsort(hybrid_scores)[::-1]

        results = []
        for idx in top_indices:
            score = float(hybrid_scores[idx])
            if score < threshold and len(results) > 0:
                break

            r = rows[idx]
            citation = f"[{r['filename']} | {r['page_or_section']}]"
            results.append({
                "chunk_id": r["id"],
                "document_id": r["document_id"],
                "filename": r["filename"],
                "page_or_section": r["page_or_section"],
                "content": r["content"],
                "score": round(score, 4),
                "citation": citation,
                "project_id": r["project_id"]
            })

            if len(results) >= top_k:
                break

        return results

    def list_documents(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM rag_documents"
        params = []
        if project_id:
            sql += " WHERE (project_id = ? OR project_id IS NULL)"
            params.append(project_id)
        sql += " ORDER BY created_at DESC;"

        with self.db.connection() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [
                {
                    "id": r["id"],
                    "filename": r["filename"],
                    "file_type": r["file_type"],
                    "file_size": r["file_size"],
                    "content_hash": r["content_hash"],
                    "project_id": r["project_id"],
                    "privacy_level": r["privacy_level"],
                    "chunk_count": r["chunk_count"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

    def delete_document(self, document_id: str) -> bool:
        with self.db.connection() as conn:
            conn.execute("DELETE FROM rag_chunks WHERE document_id = ?;", (document_id,))
            cursor = conn.execute("DELETE FROM rag_documents WHERE id = ?;", (document_id,))
            return cursor.rowcount > 0

    def get_document_chunks(self, document_id: str) -> List[Dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM rag_chunks WHERE document_id = ? ORDER BY chunk_index ASC;",
                (document_id,)
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "chunk_index": r["chunk_index"],
                    "content": r["content"],
                    "page_or_section": r["page_or_section"],
                    "metadata": json.loads(r["metadata"] or "{}"),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

# Global store singleton
_rag_store = None

def get_rag_store(db_manager: Optional[DatabaseManager] = None) -> RAGKnowledgeStore:
    global _rag_store
    if _rag_store is None:
        _rag_store = RAGKnowledgeStore(db_manager)
    return _rag_store
