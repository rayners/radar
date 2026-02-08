"""JSONL-based conversation memory.

Each conversation is stored as a separate .jsonl file in:
    $RADAR_DATA_DIR/conversations/{uuid}.jsonl (default: ~/.local/share/radar/conversations/)

Each line in the file is a JSON object representing a message.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from radar.config import get_data_paths


def _get_conversation_path(conversation_id: str) -> Path:
    """Get the path to a conversation's JSONL file."""
    return get_data_paths().conversations / f"{conversation_id}.jsonl"


def create_conversation() -> str:
    """Create a new conversation and return its ID."""
    conversation_id = str(uuid.uuid4())
    conv_path = _get_conversation_path(conversation_id)
    conv_path.touch()
    return conversation_id


def add_message(
    conversation_id: str,
    role: str,
    content: str | None = None,
    tool_calls: list[dict] | None = None,
    tool_call_id: str | None = None,
) -> int:
    """Add a message to a conversation.

    Returns the line number (1-indexed) of the added message.
    """
    conv_path = _get_conversation_path(conversation_id)

    message = {
        "timestamp": datetime.now().isoformat(),
        "role": role,
        "content": content,
        "tool_calls": tool_calls,
        "tool_call_id": tool_call_id,
    }

    with open(conv_path, "a") as f:
        f.write(json.dumps(message) + "\n")

    # Return line number (count lines in file)
    with open(conv_path) as f:
        return sum(1 for _ in f)


def get_messages(conversation_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    """Get messages for a conversation.

    Args:
        conversation_id: The conversation ID
        limit: Optional limit on number of messages (most recent)

    Returns:
        List of message dicts with role, content, tool_calls, etc.
    """
    conv_path = _get_conversation_path(conversation_id)

    if not conv_path.exists():
        return []

    messages = []
    with open(conv_path) as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            msg = json.loads(line)
            msg["id"] = line_num
            messages.append(msg)

    if limit and len(messages) > limit:
        messages = messages[-limit:]

    return messages


def _get_heartbeat_conversation_id() -> str | None:
    """Read the heartbeat conversation ID from the data directory."""
    heartbeat_file = get_data_paths().base / "heartbeat_conversation"
    if heartbeat_file.exists():
        return heartbeat_file.read_text().strip()
    return None


def delete_conversation(conversation_id: str) -> tuple[bool, str]:
    """Delete a conversation and clean up associated data.

    Args:
        conversation_id: The conversation ID to delete.

    Returns:
        (success, message) tuple.
    """
    # Protect heartbeat conversation
    heartbeat_id = _get_heartbeat_conversation_id()
    if heartbeat_id and conversation_id == heartbeat_id:
        return False, "Cannot delete the heartbeat conversation"

    conv_path = _get_conversation_path(conversation_id)
    if not conv_path.exists():
        return False, f"Conversation {conversation_id} not found"

    conv_path.unlink()

    # Best-effort cleanup of feedback records
    try:
        from radar.semantic import _get_connection

        conn = _get_connection()
        conn.execute("DELETE FROM feedback WHERE conversation_id = ?", (conversation_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass

    # Best-effort cleanup of conversation search index
    try:
        from radar.conversation_search import remove_conversation_index
        remove_conversation_index(conversation_id)
    except Exception:
        pass

    return True, f"Conversation {conversation_id} deleted"


def get_recent_conversations(
    limit: int = 20,
    offset: int = 0,
    type_filter: str | None = None,
    search: str | None = None,
) -> list[dict[str, Any]]:
    """Get recent conversations with enriched metadata.

    Args:
        limit: Maximum number of conversations to return.
        offset: Number of conversations to skip (for pagination).
        type_filter: Filter by type ("chat" or "heartbeat").
        search: Case-insensitive substring search across message content.

    Returns list of dicts with id, created_at, preview, timestamp, type,
    summary, and tool_count.
    """
    conv_dir = get_data_paths().conversations

    # Get all .jsonl files sorted by modification time (most recent first)
    conv_files = sorted(
        conv_dir.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    heartbeat_id = _get_heartbeat_conversation_id()

    conversations = []
    for conv_path in conv_files:
        conversation_id = conv_path.stem
        preview = ""
        created_at = None
        tool_count = 0
        search_matched = search is None

        # Determine type
        conv_type = "heartbeat" if conversation_id == heartbeat_id else "chat"

        # Apply type filter early
        if type_filter and conv_type != type_filter:
            continue

        # Scan all messages
        with open(conv_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if created_at is None:
                    created_at = msg.get("timestamp")

                if not preview and msg.get("role") == "user" and msg.get("content"):
                    preview = msg["content"][:100]

                if msg.get("role") == "assistant" and msg.get("tool_calls"):
                    tool_count += len(msg["tool_calls"])

                if search and not search_matched:
                    content = msg.get("content") or ""
                    if search.lower() in content.lower():
                        search_matched = True

        if not search_matched:
            continue

        # Format timestamp for display
        timestamp = ""
        if created_at:
            timestamp = created_at[:16].replace("T", " ")

        conversations.append({
            "id": conversation_id,
            "created_at": created_at,
            "timestamp": timestamp,
            "type": conv_type,
            "summary": preview,
            "tool_count": tool_count,
            "preview": preview,  # backward compat
        })

    # Apply offset and limit
    return conversations[offset:offset + limit]


def messages_to_api_format(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert stored messages to Ollama API format."""
    api_messages = []
    for msg in messages:
        api_msg = {"role": msg["role"]}
        if msg.get("content"):
            api_msg["content"] = msg["content"]
        if msg.get("tool_calls"):
            api_msg["tool_calls"] = msg["tool_calls"]
        api_messages.append(api_msg)
    return api_messages


def count_tool_calls_today() -> int:
    """Count tool calls made today across all conversations.

    Scans JSONL files modified today and counts assistant messages
    with non-empty tool_calls where the timestamp starts with today's date.
    """
    conv_dir = get_data_paths().conversations
    today = datetime.now().strftime("%Y-%m-%d")
    count = 0

    for conv_path in conv_dir.glob("*.jsonl"):
        # Only scan files modified today (optimization)
        mtime = datetime.fromtimestamp(conv_path.stat().st_mtime)
        if mtime.strftime("%Y-%m-%d") != today:
            continue

        with open(conv_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    msg.get("role") == "assistant"
                    and msg.get("tool_calls")
                    and msg.get("timestamp", "").startswith(today)
                ):
                    count += len(msg["tool_calls"])

    return count


def get_recent_activity(limit: int = 10) -> list[dict[str, Any]]:
    """Get recent activity across conversations.

    Extracts user messages and tool calls into a unified timeline.

    Returns list of dicts with time, message, type fields.
    Types: "chat" for user messages, "tool" for tool calls.
    Sorted by time descending.
    """
    conv_dir = get_data_paths().conversations

    # Get recent conversation files by modification time
    conv_files = sorted(
        conv_dir.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:20]  # Scan at most 20 recent files

    activity: list[dict[str, Any]] = []

    for conv_path in conv_files:
        with open(conv_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                timestamp = msg.get("timestamp", "")

                if msg.get("role") == "user" and msg.get("content"):
                    activity.append({
                        "time": timestamp[:16] if timestamp else "",
                        "message": msg["content"][:50],
                        "type": "chat",
                    })
                elif msg.get("role") == "assistant" and msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        func = tc.get("function", {})
                        name = func.get("name", "unknown")
                        activity.append({
                            "time": timestamp[:16] if timestamp else "",
                            "message": f"Called {name}",
                            "type": "tool",
                        })

    # Sort by time descending
    activity.sort(key=lambda a: a["time"], reverse=True)

    return activity[:limit]


def get_messages_for_display(conversation_id: str) -> list[dict[str, Any]]:
    """Get messages formatted for web UI display.

    Transforms tool_calls format and associates results with their calls.
    Skips "tool" role messages as they are merged into assistant messages.

    Args:
        conversation_id: The conversation ID

    Returns:
        List of messages with tool_calls in display format:
        {"role": "user"|"assistant", "content": "...", "tool_calls": [{"name": ..., "args": ..., "result": ...}]}
    """
    raw_messages = get_messages(conversation_id)

    # Build a map of tool_call_id -> result from tool role messages
    tool_results: dict[str, str] = {}
    for msg in raw_messages:
        if msg.get("role") == "tool" and msg.get("tool_call_id"):
            tool_results[msg["tool_call_id"]] = msg.get("content", "")

    display_messages: list[dict[str, Any]] = []

    for i, msg in enumerate(raw_messages):
        role = msg.get("role")

        # Skip tool role messages - their results are merged into assistant messages
        if role == "tool":
            continue

        display_msg: dict[str, Any] = {
            "role": role,
            "content": msg.get("content") or "",
            "id": msg.get("id"),
        }

        # Transform tool_calls to display format
        if msg.get("tool_calls"):
            display_tool_calls = []

            # Collect tool results that follow this message (for positional matching)
            following_tool_results = []
            for j in range(i + 1, len(raw_messages)):
                if raw_messages[j].get("role") == "tool":
                    following_tool_results.append(raw_messages[j].get("content", ""))
                else:
                    break

            for idx, tc in enumerate(msg["tool_calls"]):
                # Extract from stored format: {"function": {"name": ..., "arguments": {...}}, "id": ...}
                func = tc.get("function", {})
                tool_call_id = tc.get("id", "")

                # Try to get result by tool_call_id first, then by position
                result = tool_results.get(tool_call_id, "")
                if not result and idx < len(following_tool_results):
                    result = following_tool_results[idx]

                display_tool_calls.append({
                    "name": func.get("name", "unknown"),
                    "args": func.get("arguments", {}),
                    "result": result,
                })

            if display_tool_calls:
                display_msg["tool_calls"] = display_tool_calls

        display_messages.append(display_msg)

    return display_messages
