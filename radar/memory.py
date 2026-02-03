"""SQLite-based conversation memory."""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


def _get_db_path() -> Path:
    """Get the database file path."""
    db_dir = Path.home() / ".local" / "share" / "radar"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "conversations.db"


def _get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize the database schema."""
    conn = _get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            role TEXT NOT NULL,
            content TEXT,
            tool_calls TEXT,
            tool_call_id TEXT,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_conversation
        ON messages(conversation_id, timestamp)
    """)

    conn.commit()
    conn.close()


def create_conversation() -> str:
    """Create a new conversation and return its ID."""
    init_db()
    conn = _get_connection()
    cursor = conn.cursor()

    conversation_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO conversations (id) VALUES (?)",
        (conversation_id,),
    )

    conn.commit()
    conn.close()
    return conversation_id


def add_message(
    conversation_id: str,
    role: str,
    content: str | None = None,
    tool_calls: list[dict] | None = None,
    tool_call_id: str | None = None,
) -> int:
    """Add a message to a conversation.

    Returns the message ID.
    """
    conn = _get_connection()
    cursor = conn.cursor()

    tool_calls_json = json.dumps(tool_calls) if tool_calls else None

    cursor.execute(
        """
        INSERT INTO messages (conversation_id, role, content, tool_calls, tool_call_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (conversation_id, role, content, tool_calls_json, tool_call_id),
    )

    message_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return message_id


def get_messages(conversation_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    """Get messages for a conversation.

    Args:
        conversation_id: The conversation ID
        limit: Optional limit on number of messages (most recent)

    Returns:
        List of message dicts with role, content, tool_calls, etc.
    """
    conn = _get_connection()
    cursor = conn.cursor()

    if limit:
        cursor.execute(
            """
            SELECT * FROM (
                SELECT * FROM messages
                WHERE conversation_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            ) ORDER BY timestamp ASC
            """,
            (conversation_id, limit),
        )
    else:
        cursor.execute(
            """
            SELECT * FROM messages
            WHERE conversation_id = ?
            ORDER BY timestamp ASC
            """,
            (conversation_id,),
        )

    rows = cursor.fetchall()
    conn.close()

    messages = []
    for row in rows:
        msg = {
            "id": row["id"],
            "role": row["role"],
            "content": row["content"],
            "timestamp": row["timestamp"],
        }
        if row["tool_calls"]:
            msg["tool_calls"] = json.loads(row["tool_calls"])
        if row["tool_call_id"]:
            msg["tool_call_id"] = row["tool_call_id"]
        messages.append(msg)

    return messages


def get_recent_conversations(limit: int = 5) -> list[dict[str, Any]]:
    """Get recent conversations with their first message preview.

    Returns list of dicts with id, created_at, preview.
    """
    init_db()
    conn = _get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT c.id, c.created_at,
               (SELECT content FROM messages
                WHERE conversation_id = c.id AND role = 'user'
                ORDER BY timestamp ASC LIMIT 1) as preview
        FROM conversations c
        ORDER BY c.created_at DESC
        LIMIT ?
        """,
        (limit,),
    )

    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "preview": (row["preview"] or "")[:100],
        }
        for row in rows
    ]


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
