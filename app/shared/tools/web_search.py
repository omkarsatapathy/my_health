from typing import Any

import httpx
from crewai.tools import tool

from app.config import settings

_ENDPOINT = "https://www.googleapis.com/customsearch/v1"


def _web_search(query: str, num: int = 5) -> dict[str, Any]:
    """Run Google Custom Search; return top results or error."""
    if not settings.google_search_api_key or not settings.google_search_engine_id:
        return {"error": "google search not configured", "results": []}

    num = max(1, min(int(num), 10))
    params = {
        "key": settings.google_search_api_key,
        "cx": settings.google_search_engine_id,
        "q": query,
        "num": num,
    }
    try:
        resp = httpx.get(_ENDPOINT, params=params, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as e:
        return {"error": f"search failed: {e}", "results": []}

    results = [
        {"title": it.get("title", ""), "snippet": it.get("snippet", ""), "link": it.get("link", "")}
        for it in data.get("items", [])
    ]
    return {"query": query, "results": results}


@tool("web_search")
def web_search(query: str, num: int = 5) -> dict[str, Any]:
    """Google web search for live facts (nutrition info, supplements). Returns top results."""
    return _web_search(query, num)
