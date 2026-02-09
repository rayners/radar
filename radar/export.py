"""Conversation export in JSON and Markdown formats."""

import json

from radar.memory import _get_conversation_path, get_messages, get_messages_for_display


def _require_conversation(conversation_id: str) -> None:
    """Raise ValueError if conversation does not exist."""
    if not _get_conversation_path(conversation_id).exists():
        raise ValueError(f"Conversation not found: {conversation_id}")


def export_json(conversation_id: str) -> str:
    """Export conversation as a JSON array string.

    Raises ValueError if the conversation does not exist.
    """
    _require_conversation(conversation_id)

    messages = get_messages(conversation_id)
    # Strip internal 'id' field added by get_messages
    cleaned = [{k: v for k, v in msg.items() if k != "id"} for msg in messages]
    return json.dumps(cleaned, indent=2)


def export_markdown(conversation_id: str) -> str:
    """Export conversation as a Markdown string.

    Raises ValueError if the conversation does not exist.
    """
    _require_conversation(conversation_id)

    # Build a {line_id: timestamp} map from raw messages
    raw_messages = get_messages(conversation_id)
    timestamps = {msg["id"]: msg.get("timestamp", "") for msg in raw_messages}

    # Use display messages for merged tool results
    display_messages = get_messages_for_display(conversation_id)

    lines = [f"# Conversation {conversation_id[:8]}"]

    for msg in display_messages:
        role = msg.get("role", "unknown")
        heading = role.capitalize()
        msg_id = msg.get("id")
        timestamp = timestamps.get(msg_id, "")

        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(f"## {heading}")

        if timestamp:
            display_ts = timestamp[:19].replace("T", " ")
            lines.append(f"_{display_ts}_")

        # Tool calls
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                name = tc.get("name", "unknown")
                args = tc.get("args", {})
                result = tc.get("result", "")

                lines.append("")
                lines.append(f"**Tool call: {name}**")
                lines.append("```json")
                lines.append(json.dumps(args, indent=2))
                lines.append("```")

                if result:
                    # Indent each line of the result as a blockquote
                    for result_line in result.split("\n"):
                        lines.append(f"> {result_line}")

        # Message content
        content = msg.get("content", "")
        if content:
            lines.append("")
            lines.append(content)

    return "\n".join(lines) + "\n"
