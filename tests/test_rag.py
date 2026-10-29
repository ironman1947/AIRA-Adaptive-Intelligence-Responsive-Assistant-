"""Tests for AIRA RAG Knowledge Pipeline, Chunking, Retrieval, and Citations."""

import pytest
from src.rag.ingestion import chunk_text, process_document
from src.rag.store import RAGKnowledgeStore
from src.memory.database import DatabaseManager

@pytest.fixture
def rag_store(tmp_path):
    db_file = tmp_path / "test_rag.db"
    mgr = DatabaseManager(str(db_file))
    return RAGKnowledgeStore(mgr)

def test_chunking_with_overlap():
    text = "Sentence one. Sentence two. Sentence three. Sentence four. Sentence five. Sentence six."
    chunks = chunk_text(text, chunk_size=35, chunk_overlap=10)
    assert len(chunks) > 1
    # Check that chunks cover the text
    reconstructed = " ".join(chunks)
    assert "Sentence one" in reconstructed
    assert "Sentence six" in reconstructed

def test_document_ingestion_and_indexing(rag_store, tmp_path):
    test_file = tmp_path / "guide.md"
    test_file.write_text(
        "# FastApi Deployment Guide\n\n"
        "To deploy FastAPI with Uvicorn, use standard ASGI command line:\n"
        "uvicorn src.main:app --host 0.0.0.0 --port 8080.\n\n"
        "Ensure Dockerfile exposes port 8080."
    )

    res = rag_store.index_document(str(test_file), project_id="aira-core")
    assert res["status"] == "indexed"
    assert res["chunk_count"] >= 1

    docs = rag_store.list_documents(project_id="aira-core")
    assert len(docs) == 1
    assert docs[0]["filename"] == "guide.md"

def test_rag_semantic_search_and_citations(rag_store, tmp_path):
    f1 = tmp_path / "python_concurrency.txt"
    f1.write_text(
        "Python asyncio provides cooperative multitasking using an event loop. "
        "Tasks yield control using await expressions on awaitable coroutines."
    )
    f2 = tmp_path / "database_optimization.txt"
    f2.write_text(
        "SQLite Write-Ahead Logging (WAL) significantly improves concurrent read performance "
        "by separating write operations into a separate wal file."
    )

    rag_store.index_document(str(f1), project_id="proj1")
    rag_store.index_document(str(f2), project_id="proj1")

    # Search for asyncio query
    results = rag_store.search("How does asyncio event loop work?", top_k=2, project_id="proj1")
    assert len(results) > 0
    top = results[0]
    assert "python_concurrency.txt" in top["citation"]
    assert "asyncio" in top["content"].lower()

    # Search for sqlite WAL query
    db_results = rag_store.search("SQLite WAL concurrent read performance", top_k=2, project_id="proj1")
    assert len(db_results) > 0
    assert "database_optimization.txt" in db_results[0]["citation"]

def test_rag_project_boundary_isolation(rag_store, tmp_path):
    f_private = tmp_path / "private_secret.txt"
    f_private.write_text("Confidential cryptographic key management procedures for Project Alpha.")

    rag_store.index_document(str(f_private), project_id="project_alpha")

    # Querying from project_beta must not retrieve project_alpha's documents
    results = rag_store.search("cryptographic key", project_id="project_beta")
    assert len(results) == 0

    # Querying from project_alpha succeeds
    alpha_results = rag_store.search("cryptographic key", project_id="project_alpha")
    assert len(alpha_results) == 1

def test_document_deletion_cascades(rag_store, tmp_path):
    f = tmp_path / "temp_doc.txt"
    f.write_text("Temporary documentation content to be removed.")
    res = rag_store.index_document(str(f))
    doc_id = res["document_id"]

    assert len(rag_store.list_documents()) == 1
    assert len(rag_store.get_document_chunks(doc_id)) >= 1

    # Delete
    assert rag_store.delete_document(doc_id) is True
    assert len(rag_store.list_documents()) == 0
    assert len(rag_store.get_document_chunks(doc_id)) == 0
