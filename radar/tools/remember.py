"""Remember tool for storing facts in semantic memory."""

from radar.semantic import is_embedding_available, store_memory
from radar.tools import tool


@tool(
    name="remember",
    description="Store a fact or piece of information for later recall. Use this to remember user preferences, important details, or anything the user wants you to remember.",
    parameters={
        "content": {
            "type": "string",
            "description": "The fact or information to remember",
        },
    },
)
def remember(content: str) -> str:
    """Store a fact in semantic memory."""
    if not is_embedding_available():
        return "Semantic memory is disabled (no embedding provider configured)"

    try:
        memory_id = store_memory(content, source="user")
        return f"Remembered: {content}"
    except Exception as e:
        return f"Error storing memory: {e}"
