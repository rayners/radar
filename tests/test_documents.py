"""Tests for document indexing and search."""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# --- Fixtures ---


@pytest.fixture
def docs_dir(tmp_path):
    """Create a temporary directory with markdown files."""
    d = tmp_path / "docs"
    d.mkdir()

    (d / "readme.md").write_text("# Project README\n\nThis is the main project documentation.\n\n## Getting Started\n\nInstall with pip.")
    (d / "notes.md").write_text("# Notes\n\nSome important notes about the project.\n\n## Architecture\n\nUses SQLite for storage.")
    (d / "deep").mkdir()
    (d / "deep" / "nested.md").write_text("# Nested Document\n\nThis is deeply nested content.")
    (d / "ignore.txt").write_text("This should not be indexed with *.md pattern.")

    return d


@pytest.fixture
def doc_conn(isolated_data_dir):
    """Get a database connection with document tables initialized."""
    from radar.documents import _get_connection

    conn = _get_connection()
    yield conn
    conn.close()


# --- Chunking Tests ---


class TestChunking:
    def test_chunk_basic(self):
        from radar.documents import chunk_markdown

        text = "# Heading\n\nParagraph one.\n\n## Subheading\n\nParagraph two."
        chunks = chunk_markdown(text, chunk_size=1000)
        assert len(chunks) >= 1
        assert "Heading" in chunks[0]

    def test_chunk_empty_text(self):
        from radar.documents import chunk_markdown

        assert chunk_markdown("") == []
        assert chunk_markdown("   ") == []

    def test_chunk_respects_headings(self):
        from radar.documents import chunk_markdown

        text = "# Section 1\n\nContent 1.\n\n# Section 2\n\nContent 2."
        chunks = chunk_markdown(text, chunk_size=30)
        # With small chunk size, headings should create natural boundaries
        assert len(chunks) >= 2

    def test_chunk_with_overlap(self):
        from radar.documents import chunk_markdown

        text = "# A\n\n" + "word " * 200 + "\n\n# B\n\n" + "word " * 200
        chunks = chunk_markdown(text, chunk_size=500, overlap_pct=0.2)
        assert len(chunks) >= 2

    def test_chunk_single_large_section(self):
        from radar.documents import chunk_markdown

        text = "# Title\n\n" + ("paragraph. " * 100 + "\n\n") * 5
        chunks = chunk_markdown(text, chunk_size=200)
        assert len(chunks) >= 2

    def test_chunk_no_headings(self):
        from radar.documents import chunk_markdown

        text = "Just some plain text without headings."
        chunks = chunk_markdown(text, chunk_size=1000)
        assert len(chunks) == 1
        assert chunks[0] == text


# --- Collection CRUD Tests ---


class TestCollectionCRUD:
    def test_create_collection(self, doc_conn, isolated_data_dir):
        from radar.documents import create_collection, get_collection

        coll_id = create_collection("test-notes", "/tmp/notes", "*.md", "My notes")
        assert coll_id > 0

        coll = get_collection("test-notes")
        assert coll is not None
        assert coll["name"] == "test-notes"
        assert coll["base_path"] == "/tmp/notes"

    def test_create_duplicate_collection_fails(self, doc_conn, isolated_data_dir):
        from radar.documents import create_collection

        create_collection("test-notes", "/tmp/notes")
        with pytest.raises(Exception):
            create_collection("test-notes", "/tmp/other")

    def test_list_collections(self, doc_conn, isolated_data_dir):
        from radar.documents import create_collection, list_collections

        create_collection("alpha", "/tmp/a")
        create_collection("beta", "/tmp/b")

        colls = list_collections()
        assert len(colls) == 2
        names = [c["name"] for c in colls]
        assert "alpha" in names
        assert "beta" in names

    def test_list_collections_includes_counts(self, doc_conn, isolated_data_dir):
        from radar.documents import create_collection, list_collections

        create_collection("empty", "/tmp/empty")
        colls = list_collections()
        assert colls[0]["file_count"] == 0
        assert colls[0]["chunk_count"] == 0

    def test_delete_collection(self, doc_conn, isolated_data_dir):
        from radar.documents import create_collection, delete_collection, get_collection

        create_collection("to-delete", "/tmp/del")
        assert delete_collection("to-delete")
        assert get_collection("to-delete") is None

    def test_delete_nonexistent_collection(self, doc_conn, isolated_data_dir):
        from radar.documents import delete_collection

        assert not delete_collection("nonexistent")

    def test_delete_cascade_removes_files_and_chunks(self, docs_dir, doc_conn, isolated_data_dir):
        from radar.documents import (
            create_collection,
            delete_collection,
            index_file,
        )

        coll_id = create_collection("cascading", str(docs_dir), "*.md")

        conn = doc_conn
        index_file(conn, coll_id, docs_dir / "readme.md", generate_embeddings=False)
        conn.commit()

        # Verify data exists
        assert conn.execute("SELECT COUNT(*) FROM document_files WHERE collection_id = ?", (coll_id,)).fetchone()[0] > 0
        assert conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0] > 0

        conn.close()

        delete_collection("cascading")

        from radar.documents import _get_connection
        conn2 = _get_connection()
        assert conn2.execute("SELECT COUNT(*) FROM document_files WHERE collection_id = ?", (coll_id,)).fetchone()[0] == 0
        conn2.close()


# --- Indexing Tests ---


class TestIndexing:
    def test_index_file_creates_chunks(self, docs_dir, doc_conn, isolated_data_dir):
        from radar.documents import create_collection, index_file

        coll_id = create_collection("test", str(docs_dir))
        chunks_created = index_file(
            doc_conn, coll_id, docs_dir / "readme.md", generate_embeddings=False
        )
        doc_conn.commit()

        assert chunks_created > 0

        # Check chunks exist in DB
        count = doc_conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]
        assert count == chunks_created

    def test_index_file_skips_unchanged(self, docs_dir, doc_conn, isolated_data_dir):
        from radar.documents import create_collection, index_file

        coll_id = create_collection("test", str(docs_dir))

        chunks1 = index_file(doc_conn, coll_id, docs_dir / "readme.md", generate_embeddings=False)
        doc_conn.commit()
        assert chunks1 > 0

        # Index again — should skip
        chunks2 = index_file(doc_conn, coll_id, docs_dir / "readme.md", generate_embeddings=False)
        assert chunks2 == 0

    def test_index_file_reindexes_on_change(self, docs_dir, doc_conn, isolated_data_dir):
        from radar.documents import create_collection, index_file

        coll_id = create_collection("test", str(docs_dir))

        chunks1 = index_file(doc_conn, coll_id, docs_dir / "readme.md", generate_embeddings=False)
        doc_conn.commit()
        assert chunks1 > 0

        # Modify file
        (docs_dir / "readme.md").write_text("# Updated Content\n\nNew text here.")

        chunks2 = index_file(doc_conn, coll_id, docs_dir / "readme.md", generate_embeddings=False)
        doc_conn.commit()
        assert chunks2 > 0

    def test_index_collection(self, docs_dir, isolated_data_dir):
        from radar.documents import create_collection, index_collection

        create_collection("full-test", str(docs_dir), "*.md")

        result = index_collection("full-test")
        assert result["files_indexed"] == 3  # readme.md, notes.md, deep/nested.md
        assert result["chunks_created"] > 0
        assert result["files_skipped"] == 0

    def test_index_collection_incremental(self, docs_dir, isolated_data_dir):
        from radar.documents import create_collection, index_collection

        create_collection("incr-test", str(docs_dir), "*.md")

        result1 = index_collection("incr-test")
        assert result1["files_indexed"] == 3

        # Re-index — should skip all
        result2 = index_collection("incr-test")
        assert result2["files_indexed"] == 0
        assert result2["files_skipped"] == 3

    def test_index_collection_removes_stale(self, docs_dir, isolated_data_dir):
        from radar.documents import create_collection, index_collection

        create_collection("stale-test", str(docs_dir), "*.md")
        index_collection("stale-test")

        # Remove a file
        (docs_dir / "notes.md").unlink()

        result = index_collection("stale-test")
        assert result["files_removed"] == 1

    def test_index_nonexistent_collection(self, isolated_data_dir):
        from radar.documents import index_collection

        with pytest.raises(ValueError, match="Collection not found"):
            index_collection("nonexistent")

    def test_index_nonexistent_path(self, isolated_data_dir):
        from radar.documents import create_collection, index_collection

        create_collection("bad-path", "/nonexistent/path", "*.md")
        with pytest.raises(ValueError, match="does not exist"):
            index_collection("bad-path")


# --- FTS Search Tests ---


class TestFTSSearch:
    @pytest.fixture(autouse=True)
    def indexed_docs(self, docs_dir, isolated_data_dir):
        from radar.documents import create_collection, index_collection

        create_collection("search-test", str(docs_dir), "*.md")
        index_collection("search-test")

    def test_fts_basic_search(self):
        from radar.documents import search_fts

        results = search_fts("README documentation")
        assert len(results) > 0
        assert any("README" in r["content"] for r in results)

    def test_fts_stemming(self):
        from radar.documents import search_fts

        # "installing" should match "Install" due to porter stemming
        results = search_fts("installing")
        assert len(results) > 0

    def test_fts_collection_filter(self, docs_dir, isolated_data_dir):
        from radar.documents import create_collection, index_collection, search_fts

        # Create a second collection
        other_dir = docs_dir.parent / "other"
        other_dir.mkdir()
        (other_dir / "file.md").write_text("# Unique Content\n\nSomething else entirely.")
        create_collection("other-test", str(other_dir), "*.md")
        index_collection("other-test")

        results = search_fts("unique", collection="other-test")
        assert len(results) > 0
        assert all(r["collection"] == "other-test" for r in results)

    def test_fts_no_results(self):
        from radar.documents import search_fts

        results = search_fts("xyzzyplugh")
        assert results == []


# --- Hybrid Search Tests ---


class TestHybridSearch:
    @pytest.fixture(autouse=True)
    def indexed_docs(self, docs_dir, isolated_data_dir):
        from radar.documents import create_collection, index_collection

        create_collection("hybrid-test", str(docs_dir), "*.md")
        index_collection("hybrid-test")

    def test_hybrid_fts_only(self):
        """Hybrid search works even without embeddings."""
        from radar.documents import search_hybrid

        with patch("radar.semantic.is_embedding_available", return_value=False):
            results = search_hybrid("documentation")
        assert len(results) > 0

    def test_hybrid_merges_results(self):
        from radar.documents import search_hybrid

        with patch("radar.semantic.is_embedding_available", return_value=False):
            results = search_hybrid("project architecture")
        assert len(results) > 0
        # All should have search_type "hybrid"
        assert all(r["search_type"] == "hybrid" for r in results)


# --- Tool Tests ---


class TestSearchDocumentsTool:
    def test_search_documents_basic(self, docs_dir, isolated_data_dir):
        from radar.documents import create_collection, index_collection

        create_collection("tool-test", str(docs_dir), "*.md")
        index_collection("tool-test")

        from radar.tools.search_documents import search_documents

        with patch("radar.semantic.is_embedding_available", return_value=False):
            result = search_documents("documentation", search_type="keyword")
        assert "result(s)" in result

    def test_search_documents_no_results(self, isolated_data_dir):
        from radar.tools.search_documents import search_documents

        with patch("radar.semantic.is_embedding_available", return_value=False):
            result = search_documents("xyzzyplugh", search_type="keyword")
        assert "No results" in result

    def test_search_documents_disabled(self, isolated_data_dir):
        from radar.config import get_config

        config = get_config()
        config.documents.enabled = False

        from radar.tools.search_documents import search_documents

        result = search_documents("test")
        assert "disabled" in result.lower()


class TestManageDocumentsTool:
    def test_manage_list_empty(self, isolated_data_dir):
        from radar.tools.manage_documents import manage_documents

        result = manage_documents(action="list")
        assert "No document collections" in result

    def test_manage_create_and_list(self, docs_dir, isolated_data_dir):
        from radar.tools.manage_documents import manage_documents

        result = manage_documents(
            action="create",
            name="test-coll",
            base_path=str(docs_dir),
            patterns="*.md",
        )
        assert "created" in result.lower()

        result = manage_documents(action="list")
        assert "test-coll" in result

    def test_manage_index(self, docs_dir, isolated_data_dir):
        from radar.tools.manage_documents import manage_documents

        manage_documents(action="create", name="idx-test", base_path=str(docs_dir))

        result = manage_documents(action="index", name="idx-test")
        assert "files indexed" in result.lower() or "indexed" in result.lower()

    def test_manage_delete(self, docs_dir, isolated_data_dir):
        from radar.tools.manage_documents import manage_documents

        manage_documents(action="create", name="del-test", base_path=str(docs_dir))
        result = manage_documents(action="delete", name="del-test")
        assert "deleted" in result.lower()

    def test_manage_status(self, docs_dir, isolated_data_dir):
        from radar.tools.manage_documents import manage_documents

        manage_documents(action="create", name="stat-test", base_path=str(docs_dir))
        result = manage_documents(action="status")
        assert "1 collections" in result

    def test_manage_disabled(self, isolated_data_dir):
        from radar.config import get_config

        config = get_config()
        config.documents.enabled = False

        from radar.tools.manage_documents import manage_documents

        result = manage_documents(action="list")
        assert "disabled" in result.lower()

    def test_manage_create_missing_name(self, isolated_data_dir):
        from radar.tools.manage_documents import manage_documents

        result = manage_documents(action="create", base_path="/tmp/test")
        assert "required" in result.lower()

    def test_manage_unknown_action(self, isolated_data_dir):
        from radar.tools.manage_documents import manage_documents

        result = manage_documents(action="bogus")
        assert "Unknown action" in result


# --- Recall Integration Tests ---


class TestRecallIntegration:
    def test_recall_includes_document_results(self, docs_dir, isolated_data_dir):
        from radar.documents import create_collection, index_collection

        create_collection("recall-test", str(docs_dir), "*.md")
        index_collection("recall-test")

        from radar.config import get_config

        config = get_config()
        config.documents.enabled = True

        # Patch at the import location in the recall module (top-level imports)
        with patch("radar.tools.recall.is_embedding_available", return_value=True), \
             patch("radar.tools.recall.search_memories", return_value=[
                 {"id": 1, "content": "Test memory", "created_at": "2025-01-01", "source": "user"}
             ]), \
             patch("radar.documents.search_hybrid", return_value=[
                 {"content": "Document result text", "file_path": "/tmp/test.md",
                  "collection": "recall-test", "search_type": "hybrid", "score": 0.5}
             ]):
            from radar.tools.recall import recall

            result = recall("project documentation")

        assert "Test memory" in result
        # Document results should be included
        assert "Document result text" in result

    def test_recall_works_without_documents(self, isolated_data_dir):
        from radar.config import get_config

        config = get_config()
        config.documents.enabled = False

        with patch("radar.tools.recall.is_embedding_available", return_value=True), \
             patch("radar.tools.recall.search_memories", return_value=[]):
            from radar.tools.recall import recall

            result = recall("test query")

        assert "No relevant memories" in result


# --- Web Route Tests ---


class TestDocumentWebRoutes:
    @pytest.fixture
    def client(self):
        from starlette.testclient import TestClient

        from radar.web import app

        return TestClient(app, raise_server_exceptions=False)

    @pytest.fixture(autouse=True)
    def mock_common_deps(self):
        from radar.config.schema import Config

        cfg = Config()
        with (
            patch("radar.web.get_common_context") as mock_ctx,
            patch("radar.config.load_config", return_value=cfg),
            patch("radar.config.get_config", return_value=cfg),
            patch("radar.scheduler.get_status", return_value={
                "running": True,
                "last_heartbeat": None,
                "next_heartbeat": "12:00:00",
                "pending_events": 0,
                "quiet_hours": False,
            }),
        ):
            def _ctx(request, active_page):
                return {
                    "request": request,
                    "active_page": active_page,
                    "model": "test",
                    "llm_provider": "ollama",
                    "llm_url": "localhost:11434",
                    "ntfy_configured": False,
                    "heartbeat_status": "ok",
                    "heartbeat_label": "Active",
                }

            mock_ctx.side_effect = _ctx
            yield

    def test_documents_page_returns_200(self, client):
        with patch("radar.documents.list_collections", return_value=[]):
            resp = client.get("/documents")
        assert resp.status_code == 200

    def test_api_documents_search_empty_query(self, client):
        resp = client.get("/api/documents/search")
        assert resp.status_code == 200
        assert "Enter a search query" in resp.text

    def test_api_documents_search_results(self, client):
        mock_results = [
            {
                "content": "Test document content",
                "chunk_id": 1,
                "file_path": "/tmp/test.md",
                "collection": "test",
                "search_type": "hybrid",
                "score": 0.5,
            }
        ]
        with patch("radar.documents.search_hybrid", return_value=mock_results), \
             patch("radar.semantic.is_embedding_available", return_value=False):
            resp = client.get("/api/documents/search?q=test")
        assert resp.status_code == 200
        assert "Test document content" in resp.text
