"""Web Research and Browser Context Retriever for AIRA 2.0.

Provides real-time internet research, browser page reading, link extraction,
and factual grounding while enforcing strict local-only privacy policies.
"""

import re
import json
from typing import List, Dict, Any, Optional, Tuple
from src.tools.internet import search_web, fetch_webpage
from src.knowledge.research import InternetResearchEngine
from src.context.context_models import WebResearchExcerpt


class WebContextRetriever:
    """Coordinates web searches, webpage content extraction, and browser-based research."""

    CURRENT_TOPIC_PATTERNS = [
        re.compile(r"\b(latest|current|recent|today'?s|now|breaking|news|headline|updates?)\b", re.IGNORECASE),
        re.compile(r"\b(who\s+won|score\s+of|weather|stock\s+price|market\s+today|release\s+date)\b", re.IGNORECASE),
        re.compile(r"\b(search\s+(the\s+)?web|look\s+up\s+online|search\s+for|google|internet)\b", re.IGNORECASE),
        re.compile(r"\b(in\s+202[4-9]|released\s+in\s+202[4-9]|version\s+\d+|claude\s+3|gpt-?4|gemini\s+2|deepseek|llama\s+3)\b", re.IGNORECASE),
        re.compile(r"\b(vulnerabilit(y|ies)|cve-202[4-9]|security\s+advisory|zero-?day)\b", re.IGNORECASE),
    ]

    URL_PATTERN = re.compile(r"https?://[a-zA-Z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+", re.IGNORECASE)

    def __init__(self, research_engine: Optional[InternetResearchEngine] = None):
        self.research_engine = research_engine or InternetResearchEngine()

    def is_current_info_query(self, prompt: str) -> bool:
        """Determines if a user prompt requires up-to-date web information."""
        clean = prompt.lower().strip()
        # Avoid false positives for personal memory or general knowledge definitions
        if any(clean.startswith(prefix) for prefix in ["what is a ", "what is the concept of ", "explain how "]) and "latest" not in clean and "news" not in clean:
            return False
        return any(p.search(clean) for p in self.CURRENT_TOPIC_PATTERNS)

    def extract_url(self, prompt: str) -> Optional[str]:
        """Extracts the first HTTP/HTTPS URL from the prompt if present."""
        m = self.URL_PATTERN.search(prompt)
        return m.group(0) if m else None

    def retrieve_web_context(
        self,
        prompt: str,
        privacy_mode: str = "standard",
        max_results: int = 4,
    ) -> Tuple[List[WebResearchExcerpt], List[str]]:
        """Executes authorized web search or direct webpage fetch.

        Returns (excerpts, contradictions). Enforces local-only privacy.
        """
        # Strict local-only privacy check
        if privacy_mode == "local_only":
            return [], []

        excerpts: List[WebResearchExcerpt] = []
        contradictions: List[str] = []

        # 1. Direct Webpage URL Fetch / Browser Reading
        target_url = self.extract_url(prompt)
        if target_url:
            try:
                page_raw = fetch_webpage(target_url)
                page_data = json.loads(page_raw)
                if page_data.get("status") == "success":
                    title = page_data.get("title") or target_url
                    content = page_data.get("content", "")
                    excerpts.append(
                        WebResearchExcerpt(
                            title=title,
                            url=target_url,
                            snippet=content[:300],
                            full_content=content[:4000],
                            source_type="webpage_fetch",
                        )
                    )
                    return excerpts, []
            except Exception as e:
                print(f"⚠️ [WebContextRetriever] Direct page fetch error for {target_url}: {e}")

        # 2. General Current Information or Web Search
        clean_query = self._formulate_search_query(prompt)
        try:
            results = self.research_engine.search(
                query=clean_query,
                max_results=max_results,
                fetch_top_pages=1,
            )
            for r in results:
                excerpts.append(
                    WebResearchExcerpt(
                        title=r.get("title", "Web Source"),
                        url=r.get("url", ""),
                        snippet=r.get("snippet", ""),
                        full_content=r.get("full_content"),
                        source_type="web_search",
                    )
                )
        except Exception as e:
            print(f"⚠️ [WebContextRetriever] Web search error for query '{clean_query}': {e}")

        return excerpts, contradictions

    def _formulate_search_query(self, prompt: str) -> str:
        """Cleans conversational framing to generate clean search engine queries."""
        clean = re.sub(
            r"^(please\s+)?(can\s+you\s+)?(search(\s+the\s+web|\s+for|\s+online)?|find(\s+out)?|tell\s+me\s+about|look\s+up|what\s+are\s+the|what\s+is\s+the|summarize\s+the\s+latest|what\s+happened\s+in)\s*",
            "",
            prompt,
            flags=re.IGNORECASE,
        ).strip("?.!, ")

        # Remove trailing conversational fluff
        clean = re.sub(r"\s+(please|thanks|thank\s+you)$", "", clean, flags=re.IGNORECASE).strip()

        if len(clean) < 3:
            return prompt.strip()
        return clean
