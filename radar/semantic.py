"""Semantic memory storage with embeddings."""

import sqlite3
import struct
from datetime import datetime
from pathlib import Path

import httpx

from radar.config import get_config


def _get_db_path() -> Path:
    """Get the path to the memory database."""
    data_dir = Path.home() / ".local" / "share" / "radar"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "memory.db"


def _init_db(conn: sqlite3.Connection) -> None:
    """Initialize the database schema."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            embedding BLOB NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            source TEXT
        )
    """)
    conn.commit()


def _get_connection() -> sqlite3.Connection:
    """Get a database connection, initializing if needed."""
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    return conn


def _serialize_embedding(embedding: list[float]) -> bytes:
    """Serialize embedding to bytes for storage."""
    return struct.pack(f"{len(embedding)}f", *embedding)


def _deserialize_embedding(data: bytes) -> list[float]:
    """Deserialize embedding from bytes."""
    count = len(data) // 4  # 4 bytes per float
    return list(struct.unpack(f"{count}f", data))


def get_embedding(text: str) -> list[float]:
    """Get embedding for text from Ollama.

    Args:
        text: Text to embed

    Returns:
        List of floats representing the embedding
    """
    config = get_config()
    url = f"{config.ollama.base_url.rstrip('/')}/api/embed"

    response = httpx.post(
        url,
        json={
            "model": config.embedding_model,
            "input": text,
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()

    # Ollama returns embeddings as a list (for batch support)
    embeddings = data.get("embeddings", [])
    if not embeddings:
        raise RuntimeError("No embedding returned from Ollama")

    return embeddings[0]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def store_memory(content: str, source: str | None = None) -> int:
    """Store a memory with its embedding.

    Args:
        content: The text content to remember
        source: Optional source tag (e.g., "user", "conversation")

    Returns:
        The ID of the stored memory
    """
    embedding = get_embedding(content)
    embedding_bytes = _serialize_embedding(embedding)

    conn = _get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO memories (content, embedding, source) VALUES (?, ?, ?)",
            (content, embedding_bytes, source),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def search_memories(query: str, limit: int = 5) -> list[dict]:
    """Search memories by semantic similarity.

    Args:
        query: Search query text
        limit: Maximum number of results to return

    Returns:
        List of memory dicts with content, created_at, and similarity score
    """
    query_embedding = get_embedding(query)

    conn = _get_connection()
    try:
        cursor = conn.execute("SELECT id, content, embedding, created_at, source FROM memories")
        rows = cursor.fetchall()

        # Compute similarities
        results = []
        for row in rows:
            memory_embedding = _deserialize_embedding(row["embedding"])
            similarity = cosine_similarity(query_embedding, memory_embedding)
            results.append({
                "id": row["id"],
                "content": row["content"],
                "created_at": row["created_at"],
                "source": row["source"],
                "similarity": similarity,
            })

        # Sort by similarity descending and limit
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]
    finally:
        conn.close()


def delete_memory(memory_id: int) -> bool:
    """Delete a memory by ID.

    Args:
        memory_id: ID of the memory to delete

    Returns:
        True if deleted, False if not found
    """
    conn = _get_connection()
    try:
        cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
