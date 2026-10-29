"""Structured Internet Research Engine for AIRA.

Provides multi-query search, safe page retrieval, content extraction,
publication and retrieval metadata preservation, contradiction detection,
and in-memory query caching.
"""

import json
import time
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from duckduckgo_search import DDGS

from src.tools.internet import search_web, fetch_webpage
from src.security.network import validate_url_security

class InternetResearchEngine:
    """Orchestrates safe, multi-source web investigations."""

    def __init__(self, cache_ttl_seconds: int = 300):
        self._cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
        self._cache_ttl = cache_ttl_seconds

    def search(
        self,
        query: str,
        max_results: int = 5,
        fetch_top_pages: int = 1
    ) -> List[Dict[str, Any]]:
        """Executes a structured search, optionally fetching full pages for depth."""
        clean_q = query.strip()
        if not clean_q:
            return []

        # Check cache
        now = time.time()
        if clean_q in self._cache:
            ts, cached_res = self._cache[clean_q]
            if now - ts < self._cache_ttl:
                return cached_res

        results = []
        try:
            raw_out = search_web(clean_q, max_results=max_results)
            data = json.loads(raw_out)
            for item in data.get("results", []):
                results.append({
                    "title": item.get("title", "No Title"),
                    "snippet": item.get("snippet", ""),
                    "url": item.get("url", ""),
                    "retrieved_at": item.get("retrieved_at", datetime.now().isoformat()),
                    "full_content": None,
                    "source_type": item.get("source_type", "web_search"),
                })
        except Exception as e:
            print(f"⚠️ [ResearchEngine] Search error for query '{clean_q}': {e}")
            return []

        # Fetch deep page content for top results if needed
        for i in range(min(fetch_top_pages, len(results))):
            target_url = results[i]["url"]
            try:
                page_raw = fetch_webpage(target_url)
                page_json = json.loads(page_raw)
                if page_json.get("status") == "success":
                    results[i]["full_content"] = page_json.get("content", "")[:2500]
                    if page_json.get("title"):
                        results[i]["title"] = page_json["title"]
            except Exception as e:
                print(f"⚠️ [ResearchEngine] Could not fetch deep page for {target_url}: {e}")

        # Store in cache
        self._cache[clean_q] = (now, results)
        return results

    def multi_query_research(
        self,
        queries: List[str],
        max_per_query: int = 3,
        fetch_pages_per_query: int = 1
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Performs multi-query research and checks for contradictions among sources."""
        all_results: List[Dict[str, Any]] = []
        seen_urls = set()

        for q in queries:
            q_res = self.search(q, max_results=max_per_query, fetch_top_pages=fetch_pages_per_query)
            for item in q_res:
                if item["url"] not in seen_urls:
                    seen_urls.add(item["url"])
                    all_results.append(item)

        contradictions = self.detect_contradictions(all_results)
        return all_results, contradictions

    def detect_contradictions(self, sources: List[Dict[str, Any]]) -> List[str]:
        """Detects apparent conflicts or divergent statements across retrieved sources."""
        if len(sources) < 2:
            return []

        contradictions = []
        # Check for year/date divergence in snippets
        dates_found = {}
        for idx, src in enumerate(sources):
            snippet = src.get("snippet", "") + " " + (src.get("full_content") or "")
            # Look for 4-digit years (2020-2029)
            years = re.findall(r"\b(202[0-9])\b", snippet)
            if years:
                dates_found[src.get("title", f"Source {idx+1}")] = set(years)

        # If different sources assert distinctly different years for similar topics
        if len(dates_found) >= 2:
            items = list(dates_found.items())
            first_title, first_years = items[0]
            second_title, second_years = items[1]
            if first_years and second_years and not (first_years & second_years):
                contradictions.append(
                    f"Discrepancy: '{first_title}' references timeline/dates {sorted(first_years)} while '{second_title}' references dates {sorted(second_years)}."
                )

        return contradictions
