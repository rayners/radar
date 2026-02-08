"""Semantic conversation search using the document indexing infrastructure.

Converts JSONL conversations to structured markdown, indexes them as a
document collection, and provides hybrid search (FTS5 + semantic embeddings).
"""

import json
from pathlib import Path
from typing import Any

from radar.config import get_data_paths

COLLECTION_NAME = "_conversations"


def conversation_to_text(conversation_id: str) -> str:
    """Convert a JSONL conversation to structured markdown for indexing.

    Rules:
    - user messages → ``## User`` heading + content
    - assistant messages → ``## Assistant`` heading + content + compact
      tool call summaries ``[Tool: name(args)]``
    - tool role messages → skipped (raw output is noisy)
    - Header includes short conversation ID + date from first message

    Returns empty string for empty or missing conversations.
    """
    conv_path = get_data_paths().conversations / f"{conversation_id}.jsonl"
    if not conv_path.exists():
        return ""

    messages = []
    with open(conv_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not messages:
        return ""

    # Extract date from first message timestamp
    first_ts = messages[0].get("timestamp", "")
    date_str = first_ts[:10] if first_ts else "unknown"
    short_id = conversation_id[:8]

    parts = [f"# Conversation {short_id} - {date_str}\n"]

    for msg in messages:
        role = msg.get("role", "")

        if role == "tool":
            continue

        if role == "user":
            content = msg.get("content") or ""
            parts.append(f"## User\n{content}\n")

        elif role == "assistant":
            content = msg.get("content") or ""

            # Append compact tool call summaries
            tool_summaries = []
            for tc in msg.get("tool_calls") or []:
                func = tc.get("function", {})
                name = func.get("name", "unknown")
                args = func.get("arguments", {})
                if isinstance(args, dict):
                    args_str = ", ".join(
                        f'{k}="{v}"' if isinstance(v, str) else f"{k}={v}"
                        for k, v in args.items()
                    )
                else:
                    args_str = str(args)
                tool_summaries.append(f"[Tool: {name}({args_str})]")

            tool_text = "\n".join(tool_summaries)
            if content and tool_text:
                parts.append(f"## Assistant\n{tool_text}\n{content}\n")
            elif content:
                parts.append(f"## Assistant\n{content}\n")
            elif tool_text:
                parts.append(f"## Assistant\n{tool_text}\n")

    return "\n".join(parts)


def ensure_conversations_collection() -> None:
    """Ensure the conversations directory is registered as a document collection."""
    conversations_dir = get_data_paths().conversations
    if not conversations_dir.exists():
        return

    from radar.documents import get_collection, create_collection

    existing = get_collection(COLLECTION_NAME)
    if existing:
        return

    try:
        create_collection(
            name=COLLECTION_NAME,
            base_path=str(conversations_dir),
            patterns="*.jsonl",
            description="Conversation history (auto-registered)",
        )
    except Exception:
        pass


def index_conversations() -> dict[str, int]:
    """Index all conversations for semantic search.

    Uses the document indexing infrastructure with text_override to pass
    pre-converted markdown text. File hashes are computed from the actual
    JSONL files for change detection.

    Returns dict with 'indexed', 'skipped', 'removed' counts.
    """
    from radar.config import get_config
    from radar.documents import (
        _get_connection,
        _remove_stale_files,
        get_collection,
        index_file,
    )

    ensure_conversations_collection()

    collection = get_collection(COLLECTION_NAME)
    if not collection:
        return {"indexed": 0, "skipped": 0, "removed": 0}

    conversations_dir = get_data_paths().conversations
    docs_config = get_config().documents

    conn = _get_connection()
    try:
        indexed = 0
        skipped = 0

        matched_files = set()
        for file_path in conversations_dir.glob("*.jsonl"):
            if file_path.is_file():
                matched_files.add(file_path.resolve())

        for file_path in sorted(matched_files):
            conversation_id = file_path.stem
            text = conversation_to_text(conversation_id)
            if not text:
                skipped += 1
                continue

            chunks = index_file(
                conn,
                collection["id"],
                file_path,
                chunk_size=docs_config.chunk_size,
                overlap_pct=docs_config.chunk_overlap_pct,
                generate_embeddings=docs_config.generate_embeddings,
                text_override=text,
            )
            if chunks > 0:
                indexed += 1
            else:
                skipped += 1

        removed = _remove_stale_files(conn, collection["id"], matched_files)

        conn.execute(
            "UPDATE document_collections SET last_indexed = CURRENT_TIMESTAMP WHERE id = ?",
            (collection["id"],),
        )
        conn.commit()

        return {"indexed": indexed, "skipped": skipped, "removed": removed}
    finally:
        conn.close()


def search_conversations(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search conversations using hybrid search (FTS5 + semantic).

    Returns list of dicts with conversation_id, content, and score.
    """
    from radar.documents import search_hybrid

    results = search_hybrid(query, collection=COLLECTION_NAME, limit=limit)

    conversation_results = []
    for r in results:
        file_path = r.get("file_path", "")
        conversation_id = Path(file_path).stem
        conversation_results.append({
            "conversation_id": conversation_id,
            "content": r["content"],
            "score": r.get("score", 0),
        })

    return conversation_results


def remove_conversation_index(conversation_id: str) -> None:
    """Remove index entries for a deleted conversation."""
    from radar.documents import _get_connection

    conv_path = get_data_paths().conversations / f"{conversation_id}.jsonl"
    resolved = str(conv_path.resolve())

    conn = _get_connection()
    try:
        cursor = conn.execute(
            "SELECT id FROM document_files WHERE file_path = ?",
            (resolved,),
        )
        row = cursor.fetchone()
        if not row:
            return

        conn.execute("DELETE FROM document_chunks WHERE file_id = ?", (row["id"],))
        conn.execute("DELETE FROM document_files WHERE id = ?", (row["id"],))
        conn.commit()
    finally:
        conn.close()
