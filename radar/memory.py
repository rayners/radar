"""JSONL-based conversation memory.

Each conversation is stored as a separate .jsonl file in:
    ~/.local/share/radar/conversations/{uuid}.jsonl

Each line in the file is a JSON object representing a message.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


def _get_conversations_dir() -> Path:
    """Get the conversations directory path."""
    conv_dir = Path.home() / ".local" / "share" / "radar" / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)
    return conv_dir


def _get_conversation_path(conversation_id: str) -> Path:
    """Get the path to a conversation's JSONL file."""
    return _get_conversations_dir() / f"{conversation_id}.jsonl"


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


def get_recent_conversations(limit: int = 5) -> list[dict[str, Any]]:
    """Get recent conversations with their first message preview.

    Returns list of dicts with id, created_at, preview.
    """
    conv_dir = _get_conversations_dir()

    # Get all .jsonl files sorted by modification time (most recent first)
    conv_files = sorted(
        conv_dir.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:limit]

    conversations = []
    for conv_path in conv_files:
        conversation_id = conv_path.stem
        preview = ""
        created_at = None

        # Read first few lines to get created_at and first user message
        with open(conv_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                msg = json.loads(line)
                if created_at is None:
                    created_at = msg.get("timestamp")
                if msg.get("role") == "user" and msg.get("content"):
                    preview = msg["content"][:100]
                    break

        conversations.append({
            "id": conversation_id,
            "created_at": created_at,
            "preview": preview,
        })

    return conversations


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
