"""Controlled Internet Access and Web Research Tools for AIRA.

Provides DuckDuckGo web search and safe webpage retrieval with SSRF protection,
timeouts, content size limits, and HTML-to-text extraction.
"""

import json
import re
import warnings
from datetime import datetime
from typing import Dict, Any, List
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from src.config import WEB_FETCH_TIMEOUT_SECONDS, WEB_MAX_RESPONSE_BYTES
from src.security.network import validate_url_security

warnings.filterwarnings("ignore", category=RuntimeWarning, module="duckduckgo_search")

def search_web(query: str, max_results: int = 5) -> str:
    """Searches the live web using DuckDuckGo with resilient open scholarly/encyclopedic fallbacks."""
    clean_query = query.strip()
    if not clean_query:
        return json.dumps({"error": "Empty search query provided."})

    results: List[Dict[str, Any]] = []

    # 1. Primary: DuckDuckGo live search
    try:
        with DDGS() as ddgs:
            for item in ddgs.text(clean_query, max_results=max_results):
                url = item.get("href", "")
                is_safe, _ = validate_url_security(url)
                if not is_safe:
                    continue
                results.append({
                    "title": item.get("title", "No Title"),
                    "snippet": item.get("body", ""),
                    "url": url,
                    "retrieved_at": datetime.now().isoformat(),
                    "source_type": "duckduckgo",
                })
    except Exception as e:
        print(f"⚠️ [SearchTool] DDG search exception: {e}")

    # 2. Resilient Open Research Fallback: Wikipedia & arXiv open APIs
    # When DuckDuckGo encounters public rate limits (403/202) or returns 0 results,
    # Wikipedia and arXiv open APIs provide authentic, verified sources with real titles and URLs.
    if not results:
        headers = {
            "User-Agent": "AIRA-Research-Agent/1.0 (academic; research)"
        }
        try:
            wiki_resp = requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": clean_query,
                    "format": "json",
                    "utf8": 1,
                },
                headers=headers,
                timeout=min(WEB_FETCH_TIMEOUT_SECONDS, 5),
            )
            if wiki_resp.status_code == 200:
                wiki_data = wiki_resp.json()
                for item in wiki_data.get("query", {}).get("search", [])[:3]:
                    title = item.get("title", "")
                    clean_snip = re.sub(r"<[^>]+>", "", item.get("snippet", ""))
                    wiki_url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
                    results.append({
                        "title": title,
                        "snippet": clean_snip,
                        "url": wiki_url,
                        "retrieved_at": datetime.now().isoformat(),
                        "source_type": "wikipedia",
                    })
        except Exception as e:
            print(f"⚠️ [SearchTool] Wikipedia fallback error: {e}")

        # Also query arXiv if fewer than max_results
        if len(results) < max_results:
            try:
                import xml.etree.ElementTree as ET
                arxiv_resp = requests.get(
                    "http://export.arxiv.org/api/query",
                    params={
                        "search_query": f"all:\"{clean_query}\"",
                        "max_results": max_results - len(results),
                    },
                    timeout=min(WEB_FETCH_TIMEOUT_SECONDS, 5),
                )
                if arxiv_resp.status_code == 200:
                    root = ET.fromstring(arxiv_resp.text)
                    for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
                        t = entry.find("{http://www.w3.org/2005/Atom}title")
                        s = entry.find("{http://www.w3.org/2005/Atom}summary")
                        link = entry.find("{http://www.w3.org/2005/Atom}id")
                        if t is not None and link is not None:
                            results.append({
                                "title": t.text.strip(),
                                "snippet": (s.text.strip()[:300] if s is not None else ""),
                                "url": link.text.strip(),
                                "retrieved_at": datetime.now().isoformat(),
                                "source_type": "arxiv",
                            })
            except Exception as e:
                print(f"⚠️ [SearchTool] arXiv fallback error: {e}")

    return json.dumps({
        "query": clean_query,
        "status": "success" if results else "no_results",
        "result_count": len(results),
        "timestamp": datetime.now().isoformat(),
        "results": results
    })

def fetch_webpage(url: str) -> str:
    """Safely retrieves a webpage's textual content, enforcing SSRF protections,

    timeouts, and maximum content byte limits.
    """
    clean_url = url.strip()
    is_safe, error_msg = validate_url_security(clean_url)
    if not is_safe:
        return json.dumps({
            "url": clean_url,
            "status": "blocked_by_security_policy",
            "error": error_msg
        })

    headers = {
        "User-Agent": "AIRA-Agent/1.0 (Adaptive Intelligence & Responsive Assistant; Research & Education)"
    }

    try:
        with requests.get(
            clean_url,
            headers=headers,
            timeout=WEB_FETCH_TIMEOUT_SECONDS,
            stream=True
        ) as resp:
            resp.raise_for_status()

            # Check content length header if present
            cl = resp.headers.get("Content-Length")
            if cl and int(cl) > WEB_MAX_RESPONSE_BYTES:
                return json.dumps({
                    "url": clean_url,
                    "status": "error",
                    "error": f"Response exceeds size limit ({cl} bytes > {WEB_MAX_RESPONSE_BYTES} bytes)"
                })

            content_bytes = bytearray()
            for chunk in resp.iter_content(chunk_size=8192):
                content_bytes.extend(chunk)
                if len(content_bytes) > WEB_MAX_RESPONSE_BYTES:
                    return json.dumps({
                        "url": clean_url,
                        "status": "error",
                        "error": f"Response exceeded maximum limit of {WEB_MAX_RESPONSE_BYTES} bytes during download."
                    })

            encoding = resp.encoding or "utf-8"
            html_text = content_bytes.decode(encoding, errors="replace")

        # Parse HTML and extract clean text
        soup = BeautifulSoup(html_text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()

        page_title = soup.title.string.strip() if soup.title and soup.title.string else "No Title"
        text = soup.get_text(separator="\n", strip=True)

        # Truncate text to a reasonable length for model consumption
        max_chars = 8000
        truncated = len(text) > max_chars
        extracted_text = text[:max_chars]

        return json.dumps({
            "url": clean_url,
            "status": "success",
            "title": page_title,
            "content": extracted_text,
            "truncated": truncated,
            "retrieved_at": datetime.now().isoformat()
        })
    except requests.RequestException as e:
        return json.dumps({
            "url": clean_url,
            "status": "error",
            "error": f"Network error during fetch: {str(e)}"
        })
    except Exception as e:
        return json.dumps({
            "url": clean_url,
            "status": "error",
            "error": f"Failed to extract content: {str(e)}"
        })

# OpenAI Function Calling Schemas
SEARCH_WEB_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "Searches the live internet using DuckDuckGo for up-to-date facts, news, documentation, or technical information.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The exact search query to look up on the web."
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of results to retrieve (default: 5, max: 10).",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    }
}

FETCH_WEBPAGE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_webpage",
        "description": "Safely retrieves and extracts clean readable text from an authorized public HTTP/HTTPS URL.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The public web URL to retrieve."
                }
            },
            "required": ["url"]
        }
    }
}
