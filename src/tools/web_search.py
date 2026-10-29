import json

from duckduckgo_search import DDGS

def search_web(query: str) -> str:
    """Searches the live web using DuckDuckGo."""
    print(f"🔧 Tool Executed: Searching the web for -> '{query}'")
    
    results = []
    try:
        with DDGS() as ddgs:
            # Fetch the top 3 live internet results
            for result in ddgs.text(query, max_results=3):
                results.append({
                    "title": result.get("title"),
                    "snippet": result.get("body"),
                    "url": result.get("href")
                })
    except Exception as e:
        return json.dumps({"error": str(e)})
        
    return json.dumps({"query": query, "results": results})

# This is the exact JSON schema OpenAI/Nemotron needs to understand how to use the tool
search_web_schema = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "Searches the web for live, up-to-date information. Use this when you don't know the answer to a current event.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The exact search query to look up."
                }
            },
            "required": ["query"]
        }
    }
}