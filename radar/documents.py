"""Document indexing with hybrid search (FTS5 + semantic).

Provides markdown-aware chunking, collection management, and search
across indexed documents using BM25 (FTS5) and cosine similarity.
"""

import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Any

from radar.config import get_config, get_data_paths
from radar.semantic import _get_connection as _get_base_connection


def _init_document_tables(conn: sqlite3.Connection) -> None:
    """Initialize document indexing tables."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS document_collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            base_path TEXT NOT NULL,
            patterns TEXT NOT NULL DEFAULT '*.md',
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_indexed TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS document_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            collection_id INTEGER NOT NULL,
            file_path TEXT NOT NULL UNIQUE,
            file_hash TEXT NOT NULL,
            last_indexed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (collection_id) REFERENCES document_collections(id) ON DELETE CASCADE
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS document_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            embedding BLOB,
            FOREIGN KEY (file_id) REFERENCES document_files(id) ON DELETE CASCADE
        )
    """)

    # FTS5 virtual table for full-text search
    # Check if FTS table exists before creating (can't use IF NOT EXISTS with virtual tables)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='document_chunks_fts'"
    )
    if not cursor.fetchone():
        conn.execute("""
            CREATE VIRTUAL TABLE document_chunks_fts USING fts5(
                content,
                content='document_chunks',
                content_rowid='id',
                tokenize='porter unicode61'
            )
        """)

        # Triggers to keep FTS in sync
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS document_chunks_ai AFTER INSERT ON document_chunks BEGIN
                INSERT INTO document_chunks_fts(rowid, content) VALUES (new.id, new.content);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS document_chunks_ad AFTER DELETE ON document_chunks BEGIN
                INSERT INTO document_chunks_fts(document_chunks_fts, rowid, content)
                VALUES ('delete', old.id, old.content);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS document_chunks_au AFTER UPDATE ON document_chunks BEGIN
                INSERT INTO document_chunks_fts(document_chunks_fts, rowid, content)
                VALUES ('delete', old.id, old.content);
                INSERT INTO document_chunks_fts(rowid, content) VALUES (new.id, new.content);
            END
        """)

    conn.commit()


def _get_connection() -> sqlite3.Connection:
    """Get a database connection with document tables initialized."""
    conn = _get_base_connection()
    _init_document_tables(conn)
    return conn


# --- Chunking ---


def chunk_markdown(
    text: str,
    chunk_size: int = 800,
    overlap_pct: float = 0.1,
) -> list[str]:
    """Split markdown text into chunks respecting heading boundaries.

    Args:
        text: Markdown text to chunk
        chunk_size: Target chunk size in characters
        overlap_pct: Overlap percentage between chunks (0.0 to 1.0)

    Returns:
        List of text chunks
    """
    if not text.strip():
        return []

    # Split on headings (keep heading with its content)
    sections = re.split(r"(?=^#{1,6}\s)", text, flags=re.MULTILINE)
    sections = [s for s in sections if s.strip()]

    if not sections:
        return [text.strip()]

    chunks = []
    current_chunk = ""
    overlap_size = int(chunk_size * overlap_pct)

    for section in sections:
        if len(current_chunk) + len(section) <= chunk_size:
            current_chunk += section
        else:
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            # Start new chunk with overlap from end of previous
            if overlap_size > 0 and current_chunk:
                overlap_text = current_chunk[-overlap_size:]
                current_chunk = overlap_text + section
            else:
                current_chunk = section

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    # Handle case where a single section is larger than chunk_size
    final_chunks = []
    for chunk in chunks:
        if len(chunk) <= chunk_size * 1.5:  # Allow some overflow
            final_chunks.append(chunk)
        else:
            # Split oversized chunks by paragraphs
            paragraphs = chunk.split("\n\n")
            sub_chunk = ""
            for para in paragraphs:
                if len(sub_chunk) + len(para) + 2 <= chunk_size:
                    sub_chunk += ("\n\n" if sub_chunk else "") + para
                else:
                    if sub_chunk.strip():
                        final_chunks.append(sub_chunk.strip())
                    sub_chunk = para
            if sub_chunk.strip():
                final_chunks.append(sub_chunk.strip())

    return final_chunks


# --- Collection CRUD ---


def create_collection(
    name: str,
    base_path: str,
    patterns: str = "*.md",
    description: str = "",
) -> int:
    """Create a document collection.

    Args:
        name: Unique collection name
        base_path: Root directory for the collection
        patterns: Comma-separated glob patterns (e.g., "*.md,*.txt")
        description: Human-readable description

    Returns:
        Collection ID

    Raises:
        sqlite3.IntegrityError: If name already exists
    """
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO document_collections (name, base_path, patterns, description) "
            "VALUES (?, ?, ?, ?)",
            (name, base_path, patterns, description),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def list_collections() -> list[dict[str, Any]]:
    """List all document collections."""
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "SELECT id, name, base_path, patterns, description, created_at, last_indexed "
            "FROM document_collections ORDER BY name"
        )
        rows = cursor.fetchall()
        results = []
        for row in rows:
            # Count files and chunks
            file_count = conn.execute(
                "SELECT COUNT(*) FROM document_files WHERE collection_id = ?",
                (row["id"],),
            ).fetchone()[0]
            chunk_count = conn.execute(
                "SELECT COUNT(*) FROM document_chunks dc "
                "JOIN document_files df ON dc.file_id = df.id "
                "WHERE df.collection_id = ?",
                (row["id"],),
            ).fetchone()[0]
            results.append({
                "id": row["id"],
                "name": row["name"],
                "base_path": row["base_path"],
                "patterns": row["patterns"],
                "description": row["description"],
                "created_at": row["created_at"],
                "last_indexed": row["last_indexed"],
                "file_count": file_count,
                "chunk_count": chunk_count,
            })
        return results
    finally:
        conn.close()


def get_collection(name: str) -> dict[str, Any] | None:
    """Get a collection by name."""
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "SELECT id, name, base_path, patterns, description, created_at, last_indexed "
            "FROM document_collections WHERE name = ?",
            (name,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        conn.close()


def delete_collection(name: str) -> bool:
    """Delete a collection and all its indexed data."""
    conn = _get_connection()
    try:
        # Get collection ID
        cursor = conn.execute(
            "SELECT id FROM document_collections WHERE name = ?", (name,)
        )
        row = cursor.fetchone()
        if not row:
            return False

        collection_id = row["id"]

        # Delete chunks (via cascade from files)
        conn.execute(
            "DELETE FROM document_chunks WHERE file_id IN "
            "(SELECT id FROM document_files WHERE collection_id = ?)",
            (collection_id,),
        )
        conn.execute(
            "DELETE FROM document_files WHERE collection_id = ?",
            (collection_id,),
        )
        conn.execute(
            "DELETE FROM document_collections WHERE id = ?",
            (collection_id,),
        )
        conn.commit()
        return True
    finally:
        conn.close()


# --- Indexing ---


def _file_hash(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def index_file(
    conn: sqlite3.Connection,
    collection_id: int,
    file_path: Path,
    chunk_size: int = 800,
    overlap_pct: float = 0.1,
    generate_embeddings: bool = True,
    text_override: str | None = None,
) -> int:
    """Index a single file, skipping if unchanged.

    Args:
        conn: Database connection
        collection_id: Collection to index into
        file_path: Path to the file
        chunk_size: Chunk size for splitting
        overlap_pct: Overlap percentage
        generate_embeddings: Whether to generate embeddings
        text_override: Pre-converted text to index instead of reading from file.
            The file hash is still computed from the actual file for change detection.

    Returns:
        Number of chunks created (0 if skipped)
    """
    file_path = Path(file_path).resolve()
    current_hash = _file_hash(file_path)

    # Check if already indexed with same hash
    cursor = conn.execute(
        "SELECT id, file_hash FROM document_files WHERE file_path = ?",
        (str(file_path),),
    )
    existing = cursor.fetchone()

    if existing and existing["file_hash"] == current_hash:
        return 0  # Unchanged, skip

    # Remove old chunks if re-indexing
    if existing:
        conn.execute(
            "DELETE FROM document_chunks WHERE file_id = ?",
            (existing["id"],),
        )
        conn.execute(
            "UPDATE document_files SET file_hash = ?, last_indexed = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (current_hash, existing["id"]),
        )
        file_id = existing["id"]
    else:
        cursor = conn.execute(
            "INSERT INTO document_files (collection_id, file_path, file_hash) VALUES (?, ?, ?)",
            (collection_id, str(file_path), current_hash),
        )
        file_id = cursor.lastrowid

    # Read and chunk the file
    text = text_override if text_override is not None else file_path.read_text(errors="replace")
    chunks = chunk_markdown(text, chunk_size=chunk_size, overlap_pct=overlap_pct)

    for idx, chunk_text in enumerate(chunks):
        embedding_bytes = None
        if generate_embeddings:
            try:
                from radar.semantic import _serialize_embedding, get_embedding

                embedding = get_embedding(chunk_text)
                embedding_bytes = _serialize_embedding(embedding)
            except Exception:
                pass  # Skip embedding on failure

        conn.execute(
            "INSERT INTO document_chunks (file_id, chunk_index, content, embedding) "
            "VALUES (?, ?, ?, ?)",
            (file_id, idx, chunk_text, embedding_bytes),
        )

    return len(chunks)


def index_collection(name: str) -> dict[str, int]:
    """Index all files in a collection.

    Returns:
        Dict with 'files_indexed', 'files_skipped', 'chunks_created', 'files_removed'
    """
    config = get_config()
    docs_config = config.documents

    collection = get_collection(name)
    if not collection:
        raise ValueError(f"Collection not found: {name}")

    base_path = Path(collection["base_path"]).expanduser().resolve()
    if not base_path.exists():
        raise ValueError(f"Collection base path does not exist: {base_path}")

    patterns = [p.strip() for p in collection["patterns"].split(",")]

    conn = _get_connection()
    try:
        files_indexed = 0
        files_skipped = 0
        chunks_created = 0

        # Collect all matching files
        matched_files = set()
        for pattern in patterns:
            for file_path in base_path.rglob(pattern):
                if file_path.is_file():
                    matched_files.add(file_path.resolve())

        # Index each file
        for file_path in sorted(matched_files):
            chunks = index_file(
                conn,
                collection["id"],
                file_path,
                chunk_size=docs_config.chunk_size,
                overlap_pct=docs_config.chunk_overlap_pct,
                generate_embeddings=docs_config.generate_embeddings,
            )
            if chunks > 0:
                files_indexed += 1
                chunks_created += chunks
            else:
                files_skipped += 1

        # Remove stale files
        files_removed = _remove_stale_files(conn, collection["id"], matched_files)

        # Update last_indexed timestamp
        conn.execute(
            "UPDATE document_collections SET last_indexed = CURRENT_TIMESTAMP WHERE id = ?",
            (collection["id"],),
        )
        conn.commit()

        return {
            "files_indexed": files_indexed,
            "files_skipped": files_skipped,
            "chunks_created": chunks_created,
            "files_removed": files_removed,
        }
    finally:
        conn.close()


def _remove_stale_files(
    conn: sqlite3.Connection,
    collection_id: int,
    current_files: set[Path],
) -> int:
    """Remove indexed files that no longer exist on disk."""
    cursor = conn.execute(
        "SELECT id, file_path FROM document_files WHERE collection_id = ?",
        (collection_id,),
    )
    removed = 0
    for row in cursor.fetchall():
        if Path(row["file_path"]) not in current_files:
            conn.execute(
                "DELETE FROM document_chunks WHERE file_id = ?",
                (row["id"],),
            )
            conn.execute(
                "DELETE FROM document_files WHERE id = ?",
                (row["id"],),
            )
            removed += 1
    return removed


# --- Search ---


def search_fts(
    query: str,
    collection: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search documents using FTS5 (BM25 ranking).

    Args:
        query: Search query
        collection: Optional collection name filter
        limit: Maximum results

    Returns:
        List of result dicts with content, rank, file_path, collection
    """
    conn = _get_connection()
    try:
        collection_filter = "AND dcol.name = ?" if collection else ""
        params = (query, collection, limit) if collection else (query, limit)
        cursor = conn.execute(
            f"""
            SELECT dc.content, dc.id AS chunk_id,
                   rank AS bm25_rank,
                   df.file_path,
                   dcol.name AS collection_name
            FROM document_chunks_fts fts
            JOIN document_chunks dc ON fts.rowid = dc.id
            JOIN document_files df ON dc.file_id = df.id
            JOIN document_collections dcol ON df.collection_id = dcol.id
            WHERE document_chunks_fts MATCH ?
            {collection_filter}
            ORDER BY rank
            LIMIT ?
            """,
            params,
        )

        return [
            {
                "content": row["content"],
                "chunk_id": row["chunk_id"],
                "bm25_rank": row["bm25_rank"],
                "file_path": row["file_path"],
                "collection": row["collection_name"],
                "search_type": "fts",
            }
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()


def search_semantic(
    query: str,
    collection: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search documents using semantic similarity.

    Args:
        query: Search query
        collection: Optional collection name filter
        limit: Maximum results

    Returns:
        List of result dicts with content, similarity, file_path, collection
    """
    from radar.semantic import (
        _deserialize_embedding,
        cosine_similarity,
        get_embedding,
    )

    query_embedding = get_embedding(query)

    conn = _get_connection()
    try:
        collection_filter = "AND dcol.name = ?" if collection else ""
        params = (collection,) if collection else ()
        cursor = conn.execute(
            f"""
            SELECT dc.id AS chunk_id, dc.content, dc.embedding,
                   df.file_path,
                   dcol.name AS collection_name
            FROM document_chunks dc
            JOIN document_files df ON dc.file_id = df.id
            JOIN document_collections dcol ON df.collection_id = dcol.id
            WHERE dc.embedding IS NOT NULL
            {collection_filter}
            """,
            params,
        )

        results = []
        for row in cursor.fetchall():
            chunk_embedding = _deserialize_embedding(row["embedding"])
            similarity = cosine_similarity(query_embedding, chunk_embedding)
            results.append({
                "content": row["content"],
                "chunk_id": row["chunk_id"],
                "similarity": similarity,
                "file_path": row["file_path"],
                "collection": row["collection_name"],
                "search_type": "semantic",
            })

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]
    finally:
        conn.close()


def search_hybrid(
    query: str,
    collection: str | None = None,
    limit: int = 10,
    fts_weight: float = 0.4,
    semantic_weight: float = 0.6,
) -> list[dict[str, Any]]:
    """Search documents using reciprocal rank fusion of FTS5 and semantic results.

    Args:
        query: Search query
        collection: Optional collection name filter
        limit: Maximum results
        fts_weight: Weight for FTS results in fusion
        semantic_weight: Weight for semantic results in fusion

    Returns:
        Merged and ranked results
    """
    k = 60  # RRF constant

    # Get FTS results
    fts_results = search_fts(query, collection=collection, limit=limit * 2)

    # Try semantic search
    semantic_results = []
    try:
        from radar.semantic import is_embedding_available

        if is_embedding_available():
            semantic_results = search_semantic(
                query, collection=collection, limit=limit * 2
            )
    except Exception:
        pass

    # Reciprocal Rank Fusion
    scores: dict[int, dict[str, Any]] = {}

    for rank, result in enumerate(fts_results):
        chunk_id = result["chunk_id"]
        rrf_score = fts_weight * (1.0 / (k + rank + 1))
        if chunk_id in scores:
            scores[chunk_id]["score"] += rrf_score
        else:
            scores[chunk_id] = {**result, "score": rrf_score, "search_type": "hybrid"}

    for rank, result in enumerate(semantic_results):
        chunk_id = result["chunk_id"]
        rrf_score = semantic_weight * (1.0 / (k + rank + 1))
        if chunk_id in scores:
            scores[chunk_id]["score"] += rrf_score
        else:
            scores[chunk_id] = {**result, "score": rrf_score, "search_type": "hybrid"}

    # Sort by combined score
    merged = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
    return merged[:limit]


def ensure_summaries_collection() -> None:
    """Ensure the summaries directory is registered as a document collection."""
    summaries_dir = get_data_paths().base / "summaries"
    if not summaries_dir.exists():
        return

    existing = get_collection("summaries")
    if existing:
        return

    try:
        create_collection(
            name="summaries",
            base_path=str(summaries_dir),
            patterns="*.md",
            description="Conversation summaries (auto-registered)",
        )
    except Exception:
        pass  # Already exists or other error
