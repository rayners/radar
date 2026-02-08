"""Tool for storing a conversation summary as a markdown file + semantic memory."""

from radar.tools import tool


@tool(
    name="store_conversation_summary",
    description=(
        "Store a conversation summary as a markdown file and in semantic memory. "
        "Call this after summarizing conversations to persist the digest."
    ),
    parameters={
        "period_type": {
            "type": "string",
            "description": 'Summary period type: "daily", "weekly", or "monthly"',
        },
        "label": {
            "type": "string",
            "description": 'Period label, e.g. "2025-01-07", "2025-W02", "2025-01"',
        },
        "summary": {
            "type": "string",
            "description": "The summary text (markdown formatted)",
        },
        "topics": {
            "type": "string",
            "description": "Comma-separated list of topics discussed (e.g., 'weather, github, meal-planning')",
        },
        "conversations_count": {
            "type": "integer",
            "description": "Number of conversations included in the summary",
        },
        "notify": {
            "type": "boolean",
            "description": "Whether to send a notification about the summary (default: false)",
        },
    },
)
def store_conversation_summary(
    period_type: str,
    label: str,
    summary: str,
    topics: str = "",
    conversations_count: int = 0,
    notify: bool = False,
) -> str:
    """Store a conversation summary as a file and in semantic memory."""
    try:
        from radar.summaries import write_summary

        # Parse topics list
        topic_list = [t.strip() for t in topics.split(",") if t.strip()] if topics else []

        metadata = {
            "conversations": conversations_count,
            "topics": topic_list,
        }

        # Write the markdown file
        path = write_summary(period_type, label, summary, metadata)
        result_parts = [f"Summary saved to {path}"]

        # Store in semantic memory for recall access
        try:
            from radar.semantic import is_embedding_available, store_memory

            if is_embedding_available():
                memory_content = (
                    f"{period_type.title()} summary ({label}): {summary[:500]}"
                )
                store_memory(memory_content, source=f"summary:{period_type}")
                result_parts.append("Stored in semantic memory")
        except Exception as e:
            result_parts.append(f"Warning: Could not store in semantic memory: {e}")

        # Send notification if requested
        if notify:
            try:
                from radar.tools.notify import notify as send_notify

                notify_msg = f"{period_type.title()} Summary ({label})\n\n"
                if topic_list:
                    notify_msg += f"Topics: {', '.join(topic_list)}\n\n"
                notify_msg += summary[:500]
                send_notify(notify_msg)
                result_parts.append("Notification sent")
            except Exception as e:
                result_parts.append(f"Warning: Notification failed: {e}")

        return ". ".join(result_parts)

    except Exception as e:
        return f"Error storing summary: {e}"
