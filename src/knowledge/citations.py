"""Citation validation and formatting for AIRA.

Ensures that citations in assistant responses strictly reference actually
retrieved documents or live web search results, preventing hallucinated URLs
or fabricated source attributions.
"""

import re
from typing import List, Dict, Any, Set, Tuple

class CitationValidator:
    """Validates and formats grounded source citations."""

    @staticmethod
    def extract_urls_from_text(text: str) -> List[str]:
        """Extracts markdown links and plain URLs from text."""
        md_urls = re.findall(r'\[([^\]]+)\]\((https?://[^\s\)]+)\)', text)
        plain_urls = re.findall(r'(?<!\()(https?://[^\s\)]+)', text)
        return [url for _, url in md_urls] + plain_urls

    @staticmethod
    def validate_citations(
        response_text: str,
        valid_sources: List[Dict[str, Any]]
    ) -> Tuple[bool, List[str], List[str]]:
        """Verifies that all citations mentioned in the response match actual retrieved evidence.

        Returns:
            (is_valid, verified_citations, unverified_citations)
        """
        valid_urls: Set[str] = set()
        valid_doc_references: Set[str] = set()

        for src in valid_sources:
            if "url" in src and src["url"]:
                valid_urls.add(src["url"].strip().lower())
            if "filename" in src and src["filename"]:
                valid_doc_references.add(src["filename"].strip().lower())
            if "citation" in src and src["citation"]:
                valid_doc_references.add(src["citation"].strip().lower())

        verified: List[str] = []
        unverified: List[str] = []

        # Check URLs in markdown links
        md_matches = re.findall(r'\[([^\]]+)\]\((https?://[^\s\)]+)\)', response_text)
        for label, url in md_matches:
            clean_url = url.strip().lower()
            if any(clean_url.startswith(v) or v.startswith(clean_url) for v in valid_urls):
                verified.append(f"[{label}]({url})")
            else:
                unverified.append(f"[{label}]({url})")

        # Check bracketed document citations like [report.pdf | Page 2]
        doc_matches = re.findall(r'\[([A-Za-z0-9_\-\.\s]+\.(?:pdf|txt|md|docx)[^\]]*)\]', response_text, re.IGNORECASE)
        for doc_ref in doc_matches:
            clean_ref = doc_ref.strip().lower()
            matched = False
            for vdoc in valid_doc_references:
                if clean_ref in vdoc or vdoc in clean_ref:
                    verified.append(f"[{doc_ref}]")
                    matched = True
                    break
            if not matched:
                unverified.append(f"[{doc_ref}]")

        is_valid = len(unverified) == 0
        return is_valid, list(set(verified)), list(set(unverified))

    @staticmethod
    def format_citation(title: str, url: str) -> str:
        """Formats a clean markdown citation."""
        clean_title = title.strip() or "Source"
        clean_url = url.strip()
        return f"[{clean_title}]({clean_url})"

    @staticmethod
    def format_rag_citation(filename: str, page_or_section: str) -> str:
        """Formats an internal RAG document citation."""
        return f"[{filename} | {page_or_section}]"
