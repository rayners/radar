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
        if not memories:
            return "No relevant memories found."

        result = "Found memories:\n"
        for m in memories:
            result += f"- {m['content']} (stored: {m['created_at']})\n"
        return result
    except Exception as e:
        return f"Error searching memory: {e}"
