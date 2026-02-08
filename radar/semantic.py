"""Semantic memory storage with embeddings."""

import sqlite3
import struct
from datetime import datetime
from pathlib import Path

import httpx

from radar.config import get_config, get_data_paths

# Cache for local embedding model
_local_model = None


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

    # Feedback table for tracking user sentiment on responses
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            message_index INTEGER NOT NULL,
            sentiment TEXT NOT NULL CHECK(sentiment IN ('positive', 'negative')),
            response_content TEXT,
            user_comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed BOOLEAN DEFAULT FALSE
        )
    """)

    # Scheduled tasks
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            schedule_type TEXT NOT NULL CHECK(schedule_type IN ('once', 'daily', 'weekly', 'interval')),
            time_of_day TEXT,
            day_of_week TEXT,
            interval_minutes INTEGER,
            run_at TEXT,
            message TEXT NOT NULL,
            enabled BOOLEAN DEFAULT TRUE,
            last_run TIMESTAMP,
            next_run TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT DEFAULT 'chat'
        )
    """)

    # URL monitors
    conn.execute("""
        CREATE TABLE IF NOT EXISTS url_monitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            check_interval_minutes INTEGER NOT NULL DEFAULT 60,
            css_selector TEXT,
            min_change_threshold INTEGER DEFAULT 0,
            headers TEXT,
            enabled BOOLEAN DEFAULT TRUE,
            last_check TIMESTAMP,
            next_check TIMESTAMP,
            last_hash TEXT,
            last_content BLOB,
            last_etag TEXT,
            last_modified TEXT,
            error_count INTEGER DEFAULT 0,
            last_error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT DEFAULT 'chat'
        )
    """)

    # URL change history
    conn.execute("""
        CREATE TABLE IF NOT EXISTS url_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            monitor_id INTEGER NOT NULL,
            detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            old_hash TEXT,
            new_hash TEXT,
            diff_summary TEXT,
            change_size INTEGER,
            FOREIGN KEY (monitor_id) REFERENCES url_monitors(id)
        )
    """)

    # Personality change suggestions
    conn.execute("""
        CREATE TABLE IF NOT EXISTS personality_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            personality_name TEXT NOT NULL,
            suggestion_type TEXT NOT NULL,
            content TEXT NOT NULL,
            reason TEXT,
            source TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            applied_at TIMESTAMP
        )
    """)

    conn.commit()


def _get_connection() -> sqlite3.Connection:
    """Get a database connection, initializing if needed."""
    db_path = get_data_paths().db
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


def is_embedding_available() -> bool:
    """Check if embedding functionality is available.

    Returns:
        True if embeddings are configured and available, False otherwise.
    """
    config = get_config()
    return config.embedding.provider != "none"


def get_embedding(text: str) -> list[float]:
    """Get embedding for text.

    Args:
        text: Text to embed

    Returns:
        List of floats representing the embedding

    Raises:
        RuntimeError: If embedding provider is 'none' or embedding fails
    """
    config = get_config()
    provider = config.embedding.provider

    if provider == "none":
        raise RuntimeError("Embeddings disabled (provider=none)")
    elif provider == "openai":
        return _get_embedding_openai(text, config)
    elif provider == "local":
        return _get_embedding_local(text, config)
    else:  # ollama (default)
        return _get_embedding_ollama(text, config)


def _get_embedding_ollama(text: str, config) -> list[float]:
    """Get embedding using Ollama's /api/embed endpoint."""
    # Use embedding base_url if set, otherwise fall back to LLM base_url
    base_url = config.embedding.base_url or config.llm.base_url
    url = f"{base_url.rstrip('/')}/api/embed"

    response = httpx.post(
        url,
        json={
            "model": config.embedding.model,
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


def _get_embedding_openai(text: str, config) -> list[float]:
    """Get embedding using OpenAI-compatible API."""
    from openai import OpenAI

    # Use embedding-specific settings if provided, otherwise fall back to LLM settings
    base_url = config.embedding.base_url or config.llm.base_url
    api_key = config.embedding.api_key or config.llm.api_key or "not-needed"

    client = OpenAI(base_url=base_url, api_key=api_key)
    response = client.embeddings.create(
        model=config.embedding.model,
        input=[text],
    )
    return response.data[0].embedding


def _get_embedding_local(text: str, config) -> list[float]:
    """Get embedding using sentence-transformers locally."""
    global _local_model

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise RuntimeError(
            "sentence-transformers not installed. "
            "Install with: pip install sentence-transformers"
        )

    # Cache model instance for reuse
    if _local_model is None:
        _local_model = SentenceTransformer(config.embedding.model)

    embedding = _local_model.encode(text)
    return embedding.tolist()


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

    Raises:
        RuntimeError: If embeddings are disabled or storage is blocked by a hook
    """
    # --- PRE hook ---
    from radar.hooks import run_pre_memory_store_hooks
    hook_result = run_pre_memory_store_hooks(content, source)
    if hook_result.blocked:
        raise RuntimeError(hook_result.message or "Memory storage blocked by hook")

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

    Raises:
        RuntimeError: If embeddings are disabled
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
        results = results[:limit]

        # --- POST hook (can filter/rerank) ---
        from radar.hooks import run_post_memory_search_hooks
        results = run_post_memory_search_hooks(query, results)

        return results
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
