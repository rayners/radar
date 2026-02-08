"""Tool for searching indexed documents."""

from radar.tools import tool


@tool(
    name="search_documents",
    description=(
        "Search indexed document collections using keyword, semantic, or hybrid search. "
        "Returns ranked results from markdown files that have been indexed."
    ),
    parameters={
        "query": {
            "type": "string",
            "description": "Search query text",
        },
        "collection": {
            "type": "string",
            "description": "Optional collection name to search within (omit for all collections)",
        },
        "search_type": {
            "type": "string",
            "description": 'Search method: "hybrid" (default), "keyword", or "semantic"',
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of results (default: 5)",
        },
    },
)
def search_documents(
    query: str,
    collection: str = "",
    search_type: str = "hybrid",
    limit: int = 5,
) -> str:
    """Search indexed documents."""
    try:
        from radar.config import get_config

        config = get_config()
        if not config.documents.enabled:
            return "Document indexing is disabled in configuration."

        from radar.documents import search_fts, search_hybrid, search_semantic

        coll = collection if collection else None

        if search_type == "keyword":
            results = search_fts(query, collection=coll, limit=limit)
        elif search_type == "semantic":
            from radar.semantic import is_embedding_available

            if not is_embedding_available():
                return "Semantic search requires an embedding provider."
            results = search_semantic(query, collection=coll, limit=limit)
        else:
            results = search_hybrid(query, collection=coll, limit=limit)

        if not results:
            return f"No results found for '{query}'."

        lines = [f"Found {len(results)} result(s) for '{query}':\n"]
        for i, r in enumerate(results, 1):
            content = r["content"][:300]
            if len(r["content"]) > 300:
                content += "..."
            file_path = r.get("file_path", "unknown")
            coll_name = r.get("collection", "")

            score_info = ""
            if "similarity" in r:
                score_info = f" (similarity: {r['similarity']:.3f})"
            elif "score" in r:
                score_info = f" (score: {r['score']:.4f})"

            lines.append(
                f"**{i}. [{coll_name}] {file_path}**{score_info}\n{content}\n"
            )

        return "\n".join(lines)

    except Exception as e:
        return f"Error searching documents: {e}"
