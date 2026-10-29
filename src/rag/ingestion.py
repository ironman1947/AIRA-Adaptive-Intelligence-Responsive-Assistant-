"""Document ingestion pipeline for AIRA RAG knowledge base.

Supports TXT, Markdown, text-based PDF (pypdf), and DOCX (python-docx).
Extracts text, preserves page/section metadata, normalizes text, chunks with overlap,
and computes content hashes for deduplication.
"""

import os
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Tuple
import pypdf
import docx

def compute_file_hash(file_path: str) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()

def extract_text_from_file(file_path: str) -> List[Tuple[str, str]]:
    """Extracts text sections from a file.

    Returns a list of (section_or_page_name, text_content).
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext in (".txt", ".md", ".markdown", ".json", ".py", ".yaml", ".yml"):
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return [("Full Document", content)]

    elif ext == ".pdf":
        sections = []
        reader = pypdf.PdfReader(file_path)
        for idx, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                sections.append((f"Page {idx + 1}", text))
        return sections

    elif ext in (".docx", ".doc"):
        doc = docx.Document(file_path)
        full_text = []
        for p in doc.paragraphs:
            if p.text.strip():
                full_text.append(p.text)
        return [("Document Body", "\n".join(full_text))]

    else:
        raise ValueError(f"Unsupported file format: '{ext}'. Supported: .txt, .md, .pdf, .docx")

def chunk_text(
    text: str,
    chunk_size: int = 700,
    chunk_overlap: int = 100
) -> List[str]:
    """Splits text into overlapping chunks, attempting to split on paragraphs or sentences."""
    if len(text) <= chunk_size:
        return [text.strip()] if text.strip() else []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunk = text[start:].strip()
            if chunk:
                chunks.append(chunk)
            break

        # Attempt to split at a clean boundary (newline or period)
        split_point = text.rfind("\n\n", start, end)
        if split_point == -1:
            split_point = text.rfind("\n", start, end)
        if split_point == -1:
            split_point = text.rfind(". ", start, end)
            if split_point != -1:
                split_point += 1  # Include the period

        if split_point == -1 or split_point <= start:
            split_point = end

        chunk = text[start:split_point].strip()
        if chunk:
            chunks.append(chunk)

        start = max(split_point, start + chunk_size - chunk_overlap)

    return chunks

def process_document(
    file_path: str,
    project_id: str = None,
    privacy_level: str = "standard",
    chunk_size: int = 700,
    chunk_overlap: int = 100
) -> Dict[str, Any]:
    """Validates, extracts, hashes, and chunks a document into indexed records."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    content_hash = compute_file_hash(file_path)
    file_size = path.stat().st_size
    filename = path.name
    file_type = path.suffix.lower()

    sections = extract_text_from_file(file_path)
    chunks_data = []
    chunk_idx = 0

    for section_name, section_text in sections:
        section_chunks = chunk_text(section_text, chunk_size, chunk_overlap)
        for ch in section_chunks:
            chunk_id = f"{content_hash[:12]}_{chunk_idx}"
            chunks_data.append({
                "id": chunk_id,
                "chunk_index": chunk_idx,
                "content": ch,
                "page_or_section": section_name,
                "metadata": {
                    "filename": filename,
                    "file_type": file_type,
                    "project_id": project_id,
                    "privacy_level": privacy_level,
                }
            })
            chunk_idx += 1

    return {
        "id": content_hash[:16],
        "filename": filename,
        "file_type": file_type,
        "file_size": file_size,
        "content_hash": content_hash,
        "project_id": project_id,
        "privacy_level": privacy_level,
        "chunk_count": len(chunks_data),
        "chunks": chunks_data,
    }
