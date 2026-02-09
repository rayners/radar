"""Web search tool supporting multiple providers."""

import httpx

from radar.config import get_config
from radar.tools import tool


def _search_brave(query: str, num_results: int, time_range: str | None) -> list[dict]:
    """Search using Brave Search API.

    Args:
        query: Search query
        num_results: Number of results to return
        time_range: Time filter (day, week, month, year)

    Returns:
        List of result dicts with title, url, description
    """
    config = get_config()
    api_key = config.search.brave_api_key

    if not api_key:
        raise ValueError("Brave API key not configured. Set RADAR_BRAVE_API_KEY.")

    params = {
        "q": query,
        "count": num_results,
    }

    # Map time_range to Brave's freshness parameter
    if time_range:
        freshness_map = {
            "day": "pd",
            "week": "pw",
            "month": "pm",
            "year": "py",
        }
        if time_range in freshness_map:
            params["freshness"] = freshness_map[time_range]

    response = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        params=params,
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        },
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()

    return [
        {"title": item.get("title", ""), "url": item.get("url", ""), "description": item.get("description", "")}
        for item in data.get("web", {}).get("results", [])
    ][:num_results]


def _search_duckduckgo(query: str, num_results: int, time_range: str | None) -> list[dict]:
    """Search using DuckDuckGo (via duckduckgo-search package).

    Args:
        query: Search query
        num_results: Number of results to return
        time_range: Time filter (day, week, month, year)

    Returns:
        List of result dicts with title, url, description
    """
    try:
        from ddgs import DDGS
    except ImportError:
        raise ImportError(
            "ddgs package not installed. Install with: pip install ddgs"
        )

    # Map time_range to DuckDuckGo's timelimit parameter
    timelimit = None
    if time_range:
        timelimit_map = {
            "day": "d",
            "week": "w",
            "month": "m",
            "year": "y",
        }
        timelimit = timelimit_map.get(time_range)

    # Try backends in order until we get results
    backends = ["auto", "lite", "html"]
    raw_results = []

    with DDGS() as ddgs:
        for backend in backends:
            try:
                raw_results = list(ddgs.text(
                    query,
                    max_results=num_results,
                    timelimit=timelimit,
                    backend=backend,
                ))
                if raw_results:
                    break
            except Exception:
                continue

    return [
        {"title": item.get("title", ""), "url": item.get("href", ""), "description": item.get("body", "")}
        for item in raw_results
    ]


def _search_searxng(query: str, num_results: int, time_range: str | None) -> list[dict]:
    """Search using SearXNG instance.

    Args:
        query: Search query
        num_results: Number of results to return
        time_range: Time filter (day, week, month, year)

    Returns:
        List of result dicts with title, url, description
    """
    config = get_config()
    base_url = config.search.searxng_url

    if not base_url:
        raise ValueError("SearXNG URL not configured. Set RADAR_SEARXNG_URL.")

    # Ensure URL ends without trailing slash
    base_url = base_url.rstrip("/")

    params = {
        "q": query,
        "format": "json",
        "pageno": 1,
    }

    # SearXNG uses the same time_range values as our API
    if time_range:
        params["time_range"] = time_range

    response = httpx.get(
        f"{base_url}/search",
        params=params,
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()

    return [
        {"title": item.get("title", ""), "url": item.get("url", ""), "description": item.get("content", "")}
        for item in data.get("results", [])
    ][:num_results]


def _format_results(query: str, results: list[dict], provider: str) -> str:
    """Format search results for display.

    Args:
        query: Original search query
        results: List of result dicts
        provider: Provider name for attribution

    Returns:
        Formatted string with results
    """
    if not results:
        return f"No results found for: {query}"

    lines = [f"**Web Search Results for \"{query}\"**", ""]

    for i, result in enumerate(results, 1):
        title = result.get("title", "Untitled")
        url = result.get("url", "")
        description = result.get("description", "")

        lines.append(f"{i}. **{title}**")
        lines.append(f"   {url}")
        if description:
            # Truncate long descriptions
            if len(description) > 200:
                description = description[:197] + "..."
            lines.append(f"   {description}")
        lines.append("")

    lines.append("---")
    lines.append(f"Found {len(results)} results via {provider.capitalize()}.")

    return "\n".join(lines)


@tool(
    name="web_search",
    description="Search the web for current information. Useful for finding recent news, documentation, or any web content.",
    parameters={
        "query": {
            "type": "string",
            "description": "The search query",
        },
        "num_results": {
            "type": "integer",
            "description": "Number of results to return (default 5, max 10)",
            "optional": True,
        },
        "time_range": {
            "type": "string",
            "description": "Filter results by time: day, week, month, or year",
            "optional": True,
        },
    },
)
def web_search(
    query: str,
    num_results: int = 5,
    time_range: str | None = None,
) -> str:
    """Search the web for information.

    Args:
        query: Search query
        num_results: Number of results to return (default 5, max 10)
        time_range: Time filter (day, week, month, year)

    Returns:
        Formatted search results or error message
    """
    config = get_config()
    provider = config.search.provider
    max_results = config.search.max_results

    # Clamp num_results
    num_results = max(1, min(num_results, max_results))

    # Validate time_range
    valid_ranges = {"day", "week", "month", "year"}
    if time_range and time_range not in valid_ranges:
        return f"Invalid time_range: {time_range}. Use: day, week, month, or year."

    try:
        if provider == "brave":
            results = _search_brave(query, num_results, time_range)
        elif provider == "duckduckgo":
            results = _search_duckduckgo(query, num_results, time_range)
        elif provider == "searxng":
            results = _search_searxng(query, num_results, time_range)
        else:
            return f"Unknown search provider: {provider}. Use: brave, duckduckgo, or searxng."

        return _format_results(query, results, provider)

    except ImportError as e:
        return f"Error: {e}"
    except ValueError as e:
        return f"Configuration error: {e}"
    except httpx.HTTPStatusError as e:
        return f"Search API error: {e.response.status_code} - {e.response.text[:200]}"
    except Exception as e:
        return f"Search failed: {e}"
