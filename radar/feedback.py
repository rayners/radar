"""Feedback and personality suggestion management."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from radar.semantic import _get_connection


def _preserve_front_matter(original: str, new_body: str) -> str:
    """Re-prepend original front matter if new_body doesn't have its own.

    Args:
        original: Original personality file content (may have front matter).
        new_body: New content to write (from a suggestion).

    Returns:
        new_body with original front matter prepended if needed.
    """
    if not original.startswith("---"):
        return new_body

    end = original.find("---", 3)
    if end == -1:
        return new_body

    # Original has front matter
    front_matter_block = original[:end + 3]

    # If new body already starts with front matter, leave it alone
    if new_body.startswith("---"):
        return new_body

    return front_matter_block + "\n" + new_body


def store_feedback(
    conversation_id: str,
    message_index: int,
    sentiment: str,
    response_content: str | None = None,
    user_comment: str | None = None,
) -> int:
    """Store user feedback on a response.

    Args:
        conversation_id: The conversation ID
        message_index: Index of the message in the conversation
        sentiment: 'positive' or 'negative'
        response_content: Optional response text for context
        user_comment: Optional user comment

    Returns:
        The ID of the stored feedback
    """
    if sentiment not in ("positive", "negative"):
        raise ValueError("sentiment must be 'positive' or 'negative'")

    conn = _get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO feedback (conversation_id, message_index, sentiment, response_content, user_comment)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conversation_id, message_index, sentiment, response_content, user_comment),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_unprocessed_feedback(limit: int = 50) -> list[dict[str, Any]]:
    """Get feedback that hasn't been processed yet.

    Args:
        limit: Maximum number of records to return

    Returns:
        List of feedback records
    """
    conn = _get_connection()
    try:
        cursor = conn.execute(
            """
            SELECT id, conversation_id, message_index, sentiment, response_content,
                   user_comment, created_at
            FROM feedback
            WHERE processed = FALSE
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_all_feedback(limit: int = 100) -> list[dict[str, Any]]:
    """Get all feedback records.

    Args:
        limit: Maximum number of records to return

    Returns:
        List of feedback records
    """
    conn = _get_connection()
    try:
        cursor = conn.execute(
            """
            SELECT id, conversation_id, message_index, sentiment, response_content,
                   user_comment, created_at, processed
            FROM feedback
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def mark_feedback_processed(feedback_ids: list[int]) -> int:
    """Mark feedback records as processed.

    Args:
        feedback_ids: List of feedback IDs to mark

    Returns:
        Number of records updated
    """
    if not feedback_ids:
        return 0

    conn = _get_connection()
    try:
        placeholders = ",".join("?" * len(feedback_ids))
        cursor = conn.execute(
            f"UPDATE feedback SET processed = TRUE WHERE id IN ({placeholders})",
            feedback_ids,
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def store_suggestion(
    personality_name: str,
    suggestion_type: str,
    content: str,
    reason: str | None = None,
    source: str = "llm_tool",
) -> int:
    """Store a personality change suggestion.

    Args:
        personality_name: Name of the personality to modify
        suggestion_type: 'add', 'remove', or 'modify'
        content: The suggested change content
        reason: Optional reason for the suggestion
        source: Source of the suggestion (e.g., 'feedback_analysis', 'llm_tool', 'user')

    Returns:
        The ID of the stored suggestion
    """
    if suggestion_type not in ("add", "remove", "modify"):
        raise ValueError("suggestion_type must be 'add', 'remove', or 'modify'")

    conn = _get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO personality_suggestions
            (personality_name, suggestion_type, content, reason, source)
            VALUES (?, ?, ?, ?, ?)
            """,
            (personality_name, suggestion_type, content, reason, source),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_pending_suggestions() -> list[dict[str, Any]]:
    """Get all pending personality suggestions.

    Returns:
        List of pending suggestion records
    """
    conn = _get_connection()
    try:
        cursor = conn.execute(
            """
            SELECT id, personality_name, suggestion_type, content, reason, source, created_at
            FROM personality_suggestions
            WHERE status = 'pending'
            ORDER BY created_at DESC
            """
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_suggestion(suggestion_id: int) -> dict[str, Any] | None:
    """Get a specific suggestion by ID.

    Args:
        suggestion_id: The suggestion ID

    Returns:
        Suggestion record or None if not found
    """
    conn = _get_connection()
    try:
        cursor = conn.execute(
            """
            SELECT id, personality_name, suggestion_type, content, reason, source,
                   status, created_at, applied_at
            FROM personality_suggestions
            WHERE id = ?
            """,
            (suggestion_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def approve_suggestion(suggestion_id: int) -> tuple[bool, str]:
    """Approve and apply a personality suggestion.

    Args:
        suggestion_id: The suggestion ID to approve

    Returns:
        Tuple of (success, message)
    """
    from radar.agent import get_personalities_dir

    suggestion = get_suggestion(suggestion_id)
    if not suggestion:
        return False, "Suggestion not found"

    if suggestion["status"] != "pending":
        return False, f"Suggestion is already {suggestion['status']}"

    personality_name = suggestion["personality_name"]
    suggestion_type = suggestion["suggestion_type"]
    content = suggestion["content"]

    # Get the personality file
    personalities_dir = get_personalities_dir()
    personality_file = personalities_dir / f"{personality_name}.md"

    if not personality_file.exists():
        # Create new personality if it doesn't exist
        if suggestion_type == "add":
            personality_file.write_text(f"# {personality_name.title()}\n\n{content}\n")
        else:
            return False, f"Personality '{personality_name}' not found"
    else:
        # Read existing content
        existing_content = personality_file.read_text()

        if suggestion_type == "add":
            # Append new content
            new_content = existing_content.rstrip() + "\n\n" + content + "\n"
        elif suggestion_type == "remove":
            # Remove the specified content
            new_content = existing_content.replace(content, "")
        elif suggestion_type == "modify":
            # For modify, the content is the full replacement body.
            # Preserve any existing front matter from the original file.
            new_content = _preserve_front_matter(existing_content, content)
        else:
            return False, f"Unknown suggestion type: {suggestion_type}"

        personality_file.write_text(new_content)

    # Update suggestion status
    conn = _get_connection()
    try:
        conn.execute(
            """
            UPDATE personality_suggestions
            SET status = 'approved', applied_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (suggestion_id,),
        )
        conn.commit()
    finally:
        conn.close()

    return True, f"Applied {suggestion_type} to personality '{personality_name}'"


def reject_suggestion(suggestion_id: int, reason: str | None = None) -> tuple[bool, str]:
    """Reject a personality suggestion.

    Args:
        suggestion_id: The suggestion ID to reject
        reason: Optional reason for rejection

    Returns:
        Tuple of (success, message)
    """
    suggestion = get_suggestion(suggestion_id)
    if not suggestion:
        return False, "Suggestion not found"

    if suggestion["status"] != "pending":
        return False, f"Suggestion is already {suggestion['status']}"

    conn = _get_connection()
    try:
        # Update status and optionally append reason
        if reason:
            new_reason = f"{suggestion.get('reason') or ''}\nRejected: {reason}".strip()
            conn.execute(
                """
                UPDATE personality_suggestions
                SET status = 'rejected', reason = ?
                WHERE id = ?
                """,
                (new_reason, suggestion_id),
            )
        else:
            conn.execute(
                "UPDATE personality_suggestions SET status = 'rejected' WHERE id = ?",
                (suggestion_id,),
            )
        conn.commit()
    finally:
        conn.close()

    return True, "Suggestion rejected"


def get_feedback_summary() -> dict[str, Any]:
    """Get a summary of feedback statistics.

    Returns:
        Dictionary with feedback statistics
    """
    conn = _get_connection()
    try:
        cursor = conn.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN sentiment = 'positive' THEN 1 ELSE 0 END) as positive,
                SUM(CASE WHEN sentiment = 'negative' THEN 1 ELSE 0 END) as negative,
                SUM(CASE WHEN processed = FALSE THEN 1 ELSE 0 END) as unprocessed
            FROM feedback
            """
        )
        row = cursor.fetchone()
        return {
            "total": row["total"] or 0,
            "positive": row["positive"] or 0,
            "negative": row["negative"] or 0,
            "unprocessed": row["unprocessed"] or 0,
        }
    finally:
        conn.close()


def delete_feedback(feedback_id: int) -> bool:
    """Delete a feedback record.

    Args:
        feedback_id: ID of the feedback to delete

    Returns:
        True if deleted, False if not found
    """
    conn = _get_connection()
    try:
        cursor = conn.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
