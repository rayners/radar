"""Recall tool for searching semantic memory."""

from radar.semantic import is_embedding_available, search_memories
from radar.tools import tool


@tool(
    name="recall",
    description="Search your memory for relevant information. Use this when you need to remember something about the user or a previous topic.",
    parameters={
        "query": {
            "type": "string",
            "description": "What to search for in memory",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of memories to return (default 5)",
            "optional": True,
        },
    },
)
def recall(query: str, limit: int = 5) -> str:
    """Search semantic memory for relevant facts."""
    if not is_embedding_available():
        return "Semantic memory is disabled (no embedding provider configured)"

    try:
        memories = search_memories(query, limit)

        parts = []
        if memories:
            parts.append("Found memories:")
            for m in memories:
                parts.append(f"- {m['content']} (stored: {m['created_at']})")

        # Include document search results if enabled
        try:
            from radar.config import get_config

            config = get_config()
            if config.documents.enabled:
                from radar.documents import search_hybrid

                doc_results = search_hybrid(query, limit=3)
                if doc_results:
                    parts.append("\nRelevant documents:")
                    for r in doc_results:
                        content = r["content"][:200]
                        if len(r["content"]) > 200:
                            content += "..."
                        source = r.get("file_path", "unknown")
                        parts.append(f"- [{r.get('collection', '')}] {source}: {content}")
        except Exception:
            pass  # Don't let document search errors break recall

        # Include conversation search results
        try:
            from radar.conversation_search import search_conversations
            conv_results = search_conversations(query, limit=3)
            if conv_results:
                parts.append("\nRelevant conversations:")
                for r in conv_results:
                    content = r["content"][:200]
                    if len(r["content"]) > 200:
                        content += "..."
                    parts.append(f"- Conversation {r['conversation_id'][:8]}: {content}")
        except Exception:
            pass  # Don't let conversation search errors break recall

        if not parts:
            return "No relevant memories found."

        return "\n".join(parts)
    except Exception as e:
        return f"Error searching memory: {e}"
