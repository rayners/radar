"""Tests for the RSS/Atom feed reader bundled plugin."""

import sqlite3
import types
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_feed_entry(
    title="Test Entry",
    link="https://example.com/1",
    entry_id=None,
    summary="A summary",
    published="Mon, 01 Jan 2024 00:00:00 GMT",
):
    """Create a mock feedparser entry."""
    entry = MagicMock()
    entry.title = title
    entry.link = link
    entry.id = entry_id or link
    entry.summary = summary
    entry.published = published
    entry.updated = None
    return entry


def _make_parsed_feed(entries=None, title="Test Feed"):
    """Create a mock feedparser result."""
    parsed = MagicMock()
    parsed.entries = entries or [_make_feed_entry()]
    parsed.bozo = False
    parsed.feed = MagicMock()
    parsed.feed.title = title
    return parsed


def _make_httpx_response(status_code=200, text="<rss></rss>", headers=None):
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.headers = headers or {}
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def rss_db(isolated_data_dir):
    """Set up the RSS feed tables and return the tool module."""
    from radar.bundled_plugins import __path__ as bp_path
    import importlib
    import importlib.util
    from pathlib import Path

    tool_path = Path(__file__).parent.parent / "radar" / "bundled_plugins" / "rss-reader" / "tool.py"
    spec = importlib.util.spec_from_file_location("rss_tool", tool_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Ensure tables exist
    mod._get_db()
    return mod


@pytest.fixture
def mock_feedparser():
    """Mock feedparser module in sys.modules."""
    fp = MagicMock()
    fp.parse = MagicMock(return_value=_make_parsed_feed())
    with patch.dict("sys.modules", {"feedparser": fp}):
        yield fp


# ---------------------------------------------------------------------------
# Import / feedparser guard
# ---------------------------------------------------------------------------


class TestFeedparserImport:
    """Test graceful ImportError when feedparser not installed."""

    def test_import_error_message(self, isolated_data_dir):
        """_import_feedparser raises ImportError with install instructions."""
        from radar.bundled_plugins import __path__ as bp_path
        import importlib.util
        from pathlib import Path

        tool_path = Path(__file__).parent.parent / "radar" / "bundled_plugins" / "rss-reader" / "tool.py"
        spec = importlib.util.spec_from_file_location("rss_tool_import", tool_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with patch.dict("sys.modules", {"feedparser": None}):
            # Reimport to get a fresh _import_feedparser
            with pytest.raises(ImportError, match="pip install radar\\[rss\\]"):
                mod._import_feedparser()


# ---------------------------------------------------------------------------
# subscribe_feed
# ---------------------------------------------------------------------------


class TestSubscribeFeed:
    """Test feed subscription."""

    def test_subscribe_success(self, rss_db):
        """Subscribe to a valid feed."""
        parsed = _make_parsed_feed(
            entries=[_make_feed_entry(title=f"Entry {i}") for i in range(3)],
            title="My Blog",
        )
        with (
            patch.object(rss_db, "_fetch_feed", return_value=(parsed, "etag1", "mod1", True)),
        ):
            result = rss_db.subscribe_feed("myblog", "https://example.com/feed.xml")

        assert "Subscribed to" in result
        assert "myblog" in result
        assert "3" in result  # baseline entries

    def test_subscribe_duplicate_url(self, rss_db):
        """Subscribing to same URL twice is rejected."""
        parsed = _make_parsed_feed()
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            rss_db.subscribe_feed("first", "https://example.com/feed.xml")
            result = rss_db.subscribe_feed("second", "https://example.com/feed.xml")

        assert "Already subscribed" in result

    def test_subscribe_fetch_error(self, rss_db):
        """Subscribe fails gracefully on fetch error."""
        with patch.object(rss_db, "_fetch_feed", side_effect=Exception("Connection refused")):
            result = rss_db.subscribe_feed("bad", "https://bad.example.com/feed")

        assert "Failed to fetch" in result

    def test_subscribe_import_error(self, rss_db):
        """Subscribe fails gracefully when feedparser missing."""
        with patch.object(rss_db, "_fetch_feed", side_effect=ImportError("pip install radar[rss]")):
            result = rss_db.subscribe_feed("bad", "https://bad.example.com/feed")

        assert "pip install" in result

    def test_subscribe_min_interval(self, rss_db):
        """Interval below minimum is clamped."""
        parsed = _make_parsed_feed()
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            result = rss_db.subscribe_feed("fast", "https://example.com/fast", check_interval_minutes=1)

        # Should succeed (clamped to MIN_INTERVAL_MINUTES)
        assert "Subscribed" in result
        conn = rss_db._get_db()
        row = conn.execute("SELECT check_interval_minutes FROM rss_feeds WHERE name = 'fast'").fetchone()
        assert row[0] == rss_db.MIN_INTERVAL_MINUTES

    def test_subscribe_stores_baseline_entries(self, rss_db):
        """Baseline entries are stored so they aren't reported as new."""
        entries = [_make_feed_entry(title=f"Entry {i}", link=f"https://example.com/{i}") for i in range(5)]
        parsed = _make_parsed_feed(entries=entries)
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            rss_db.subscribe_feed("baseline", "https://example.com/base")

        conn = rss_db._get_db()
        count = conn.execute(
            "SELECT COUNT(*) FROM feed_entries WHERE feed_id = (SELECT id FROM rss_feeds WHERE name = 'baseline')"
        ).fetchone()[0]
        assert count == 5


# ---------------------------------------------------------------------------
# list_feeds
# ---------------------------------------------------------------------------


class TestListFeeds:
    """Test feed listing."""

    def test_list_empty(self, rss_db):
        """No feeds shows appropriate message."""
        result = rss_db.list_feeds()
        assert "No feed subscriptions" in result

    def test_list_active_feeds(self, rss_db):
        """Active feeds are listed."""
        parsed = _make_parsed_feed()
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            rss_db.subscribe_feed("blog1", "https://example.com/1")
            rss_db.subscribe_feed("blog2", "https://example.com/2")

        result = rss_db.list_feeds()
        assert "blog1" in result
        assert "blog2" in result

    def test_list_hides_paused(self, rss_db):
        """Paused feeds are hidden by default."""
        parsed = _make_parsed_feed()
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            rss_db.subscribe_feed("active", "https://example.com/active")
            rss_db.subscribe_feed("paused", "https://example.com/paused")

        conn = rss_db._get_db()
        conn.execute("UPDATE rss_feeds SET enabled = 0 WHERE name = 'paused'")
        conn.commit()

        result = rss_db.list_feeds()
        assert "active" in result
        assert "paused" not in result

    def test_list_show_disabled(self, rss_db):
        """show_disabled includes paused feeds."""
        parsed = _make_parsed_feed()
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            rss_db.subscribe_feed("active", "https://example.com/active")
            rss_db.subscribe_feed("paused", "https://example.com/paused")

        conn = rss_db._get_db()
        conn.execute("UPDATE rss_feeds SET enabled = 0 WHERE name = 'paused'")
        conn.commit()

        result = rss_db.list_feeds(show_disabled=True)
        assert "active" in result
        assert "paused" in result


# ---------------------------------------------------------------------------
# check_feed
# ---------------------------------------------------------------------------


class TestCheckFeed:
    """Test manual feed checking."""

    def test_check_no_args(self, rss_db):
        """check_feed with no args returns help message."""
        result = rss_db.check_feed()
        assert "provide" in result.lower()

    def test_check_by_id_not_found(self, rss_db):
        """Check non-existent feed ID."""
        result = rss_db.check_feed(feed_id=999)
        assert "not found" in result

    def test_check_by_id_not_modified(self, rss_db):
        """Check feed that hasn't changed (304)."""
        parsed = _make_parsed_feed()
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            rss_db.subscribe_feed("blog", "https://example.com/feed")

        with patch.object(rss_db, "_fetch_feed", return_value=(None, None, None, False)):
            result = rss_db.check_feed(feed_id=1)

        assert "not changed" in result.lower()

    def test_check_by_id_new_entries(self, rss_db):
        """Check feed with new entries."""
        initial = _make_parsed_feed(entries=[_make_feed_entry(title="Old", link="https://example.com/old")])
        with patch.object(rss_db, "_fetch_feed", return_value=(initial, None, None, True)):
            rss_db.subscribe_feed("blog", "https://example.com/feed")

        new_parsed = _make_parsed_feed(entries=[
            _make_feed_entry(title="Old", link="https://example.com/old"),
            _make_feed_entry(title="New Post", link="https://example.com/new"),
        ])
        with patch.object(rss_db, "_fetch_feed", return_value=(new_parsed, "e2", "m2", True)):
            result = rss_db.check_feed(feed_id=1)

        assert "1 new" in result
        assert "New Post" in result

    def test_check_by_id_no_new_entries(self, rss_db):
        """Check feed where all entries already seen."""
        entries = [_make_feed_entry(title="Old", link="https://example.com/old")]
        parsed = _make_parsed_feed(entries=entries)
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            rss_db.subscribe_feed("blog", "https://example.com/feed")

        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            result = rss_db.check_feed(feed_id=1)

        assert "no new entries" in result.lower()

    def test_check_by_id_fetch_error(self, rss_db):
        """Check feed that fails to fetch records error."""
        parsed = _make_parsed_feed()
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            rss_db.subscribe_feed("blog", "https://example.com/feed")

        with patch.object(rss_db, "_fetch_feed", side_effect=Exception("timeout")):
            result = rss_db.check_feed(feed_id=1)

        assert "Error" in result
        # Error count should be incremented
        conn = rss_db._get_db()
        row = conn.execute("SELECT error_count FROM rss_feeds WHERE id = 1").fetchone()
        assert row[0] == 1

    def test_check_oneoff_url(self, rss_db):
        """One-off URL check without subscription."""
        parsed = _make_parsed_feed(entries=[
            _make_feed_entry(title="Article 1"),
            _make_feed_entry(title="Article 2", link="https://example.com/2"),
        ])
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            result = rss_db.check_feed(url="https://example.com/rss")

        assert "Article 1" in result
        assert "Article 2" in result


# ---------------------------------------------------------------------------
# unsubscribe_feed
# ---------------------------------------------------------------------------


class TestUnsubscribeFeed:
    """Test feed unsubscription."""

    def test_unsubscribe_not_found(self, rss_db):
        """Unsubscribe non-existent feed."""
        result = rss_db.unsubscribe_feed(feed_id=999)
        assert "not found" in result

    def test_pause_feed(self, rss_db):
        """Pause an active feed."""
        parsed = _make_parsed_feed()
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            rss_db.subscribe_feed("blog", "https://example.com/feed")

        result = rss_db.unsubscribe_feed(feed_id=1)
        assert "paused" in result.lower()

        conn = rss_db._get_db()
        row = conn.execute("SELECT enabled FROM rss_feeds WHERE id = 1").fetchone()
        assert row[0] == 0

    def test_pause_already_paused(self, rss_db):
        """Pausing already paused feed returns appropriate message."""
        parsed = _make_parsed_feed()
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            rss_db.subscribe_feed("blog", "https://example.com/feed")

        rss_db.unsubscribe_feed(feed_id=1)  # Pause
        result = rss_db.unsubscribe_feed(feed_id=1)  # Pause again
        assert "already paused" in result.lower()

    def test_resume_feed(self, rss_db):
        """Resume a paused feed."""
        parsed = _make_parsed_feed()
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            rss_db.subscribe_feed("blog", "https://example.com/feed")

        rss_db.unsubscribe_feed(feed_id=1)  # Pause
        result = rss_db.unsubscribe_feed(feed_id=1, resume=True)
        assert "resumed" in result.lower()

        conn = rss_db._get_db()
        row = conn.execute("SELECT enabled FROM rss_feeds WHERE id = 1").fetchone()
        assert row[0] == 1

    def test_resume_already_active(self, rss_db):
        """Resuming already active feed returns appropriate message."""
        parsed = _make_parsed_feed()
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            rss_db.subscribe_feed("blog", "https://example.com/feed")

        result = rss_db.unsubscribe_feed(feed_id=1, resume=True)
        assert "already active" in result.lower()

    def test_delete_feed(self, rss_db):
        """Delete a feed permanently."""
        parsed = _make_parsed_feed()
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            rss_db.subscribe_feed("blog", "https://example.com/feed")

        result = rss_db.unsubscribe_feed(feed_id=1, delete=True)
        assert "deleted" in result.lower()

        conn = rss_db._get_db()
        assert conn.execute("SELECT COUNT(*) FROM rss_feeds").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM feed_entries").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Entry deduplication
# ---------------------------------------------------------------------------


class TestEntryDedup:
    """Test entry deduplication via UNIQUE constraint."""

    def test_duplicate_guid_ignored(self, rss_db):
        """Entries with same guid are not inserted twice."""
        parsed = _make_parsed_feed(entries=[
            _make_feed_entry(title="Post", link="https://example.com/1"),
        ])
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            rss_db.subscribe_feed("blog", "https://example.com/feed")

        conn = rss_db._get_db()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new = rss_db._store_new_entries(conn, 1, parsed.entries, now)
        conn.commit()

        assert len(new) == 0  # Already stored as baseline

    def test_new_guid_inserted(self, rss_db):
        """Entries with new guid are inserted."""
        parsed = _make_parsed_feed(entries=[
            _make_feed_entry(title="Old", link="https://example.com/old"),
        ])
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            rss_db.subscribe_feed("blog", "https://example.com/feed")

        conn = rss_db._get_db()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_entries = [_make_feed_entry(title="New", link="https://example.com/new")]
        new = rss_db._store_new_entries(conn, 1, new_entries, now)
        conn.commit()

        assert len(new) == 1
        assert new[0]["title"] == "New"


# ---------------------------------------------------------------------------
# Error auto-pause
# ---------------------------------------------------------------------------


class TestErrorAutoPause:
    """Test auto-pause after MAX_ERROR_COUNT errors."""

    def test_auto_pause_at_threshold(self, rss_db):
        """Feed is auto-paused after MAX_ERROR_COUNT errors."""
        parsed = _make_parsed_feed()
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            rss_db.subscribe_feed("blog", "https://example.com/feed")

        conn = rss_db._get_db()
        # Set error_count to threshold - 1
        conn.execute(
            "UPDATE rss_feeds SET error_count = ? WHERE id = 1",
            (rss_db.MAX_ERROR_COUNT - 1,),
        )
        conn.commit()

        # Trigger one more error via check
        with patch.object(rss_db, "_fetch_feed", side_effect=Exception("fail")):
            rss_db.check_feed(feed_id=1)

        row = conn.execute("SELECT enabled, error_count FROM rss_feeds WHERE id = 1").fetchone()
        assert row[0] == 0  # disabled
        assert row[1] == rss_db.MAX_ERROR_COUNT

    def test_no_auto_pause_below_threshold(self, rss_db):
        """Feed stays active below error threshold."""
        parsed = _make_parsed_feed()
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            rss_db.subscribe_feed("blog", "https://example.com/feed")

        with patch.object(rss_db, "_fetch_feed", side_effect=Exception("fail")):
            rss_db.check_feed(feed_id=1)

        conn = rss_db._get_db()
        row = conn.execute("SELECT enabled, error_count FROM rss_feeds WHERE id = 1").fetchone()
        assert row[0] == 1  # still enabled
        assert row[1] == 1


# ---------------------------------------------------------------------------
# collect_feed_events (heartbeat hook)
# ---------------------------------------------------------------------------


class TestCollectFeedEvents:
    """Test heartbeat hook for collecting feed events."""

    def test_no_due_feeds(self, rss_db):
        """No due feeds returns empty list."""
        # Subscribe but set next_check far in the future
        parsed = _make_parsed_feed()
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            rss_db.subscribe_feed("blog", "https://example.com/feed")

        future = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        conn = rss_db._get_db()
        conn.execute("UPDATE rss_feeds SET next_check = ?", (future,))
        conn.commit()

        with patch.object(rss_db, "_import_feedparser", return_value=MagicMock()):
            events = rss_db.collect_feed_events()
        assert events == []

    def test_due_feed_no_new_entries(self, rss_db):
        """Due feed with no new entries returns empty."""
        entries = [_make_feed_entry(title="Old", link="https://example.com/old")]
        parsed = _make_parsed_feed(entries=entries)
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            rss_db.subscribe_feed("blog", "https://example.com/feed")

        # Make it due now
        conn = rss_db._get_db()
        past = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE rss_feeds SET next_check = ?", (past,))
        conn.commit()

        with (
            patch.object(rss_db, "_import_feedparser", return_value=MagicMock()),
            patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)),
        ):
            events = rss_db.collect_feed_events()

        assert events == []

    def test_due_feed_with_new_entries(self, rss_db):
        """Due feed with new entries returns events."""
        initial = _make_parsed_feed(entries=[
            _make_feed_entry(title="Old", link="https://example.com/old"),
        ])
        with patch.object(rss_db, "_fetch_feed", return_value=(initial, None, None, True)):
            rss_db.subscribe_feed("blog", "https://example.com/feed")

        # Make it due
        conn = rss_db._get_db()
        past = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE rss_feeds SET next_check = ?", (past,))
        conn.commit()

        updated = _make_parsed_feed(entries=[
            _make_feed_entry(title="Old", link="https://example.com/old"),
            _make_feed_entry(title="Brand New", link="https://example.com/new"),
        ])
        with (
            patch.object(rss_db, "_import_feedparser", return_value=MagicMock()),
            patch.object(rss_db, "_fetch_feed", return_value=(updated, "e2", "m2", True)),
        ):
            events = rss_db.collect_feed_events()

        assert len(events) == 1
        assert events[0]["type"] == "rss_new_entries"
        assert "Brand New" in events[0]["data"]["action"]

    def test_due_feed_fetch_error(self, rss_db):
        """Due feed fetch error increments error_count and returns empty."""
        parsed = _make_parsed_feed()
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, None, None, True)):
            rss_db.subscribe_feed("blog", "https://example.com/feed")

        conn = rss_db._get_db()
        past = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE rss_feeds SET next_check = ?", (past,))
        conn.commit()

        with (
            patch.object(rss_db, "_import_feedparser", return_value=MagicMock()),
            patch.object(rss_db, "_fetch_feed", side_effect=Exception("timeout")),
        ):
            events = rss_db.collect_feed_events()

        assert events == []
        # Re-read from the same DB to check error count
        row = rss_db._get_db().execute("SELECT error_count FROM rss_feeds WHERE id = 1").fetchone()
        assert row[0] == 1

    def test_feedparser_not_installed(self, rss_db):
        """collect_feed_events returns empty when feedparser missing."""
        with patch.object(rss_db, "_import_feedparser", side_effect=ImportError("missing")):
            events = rss_db.collect_feed_events()

        assert events == []

    def test_not_modified_updates_timestamps(self, rss_db):
        """304 Not Modified still updates last_check and next_check."""
        parsed = _make_parsed_feed()
        with patch.object(rss_db, "_fetch_feed", return_value=(parsed, "etag1", "mod1", True)):
            rss_db.subscribe_feed("blog", "https://example.com/feed")

        conn = rss_db._get_db()
        past = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE rss_feeds SET next_check = ?", (past,))
        conn.commit()

        with (
            patch.object(rss_db, "_import_feedparser", return_value=MagicMock()),
            patch.object(rss_db, "_fetch_feed", return_value=(None, "etag1", "mod1", False)),
        ):
            events = rss_db.collect_feed_events()

        assert events == []
        row = rss_db._get_db().execute("SELECT last_check FROM rss_feeds WHERE id = 1").fetchone()
        assert row[0] is not None  # Updated


# ---------------------------------------------------------------------------
# _entry_guid
# ---------------------------------------------------------------------------


class TestEntryGuid:
    """Test GUID extraction from feed entries."""

    def test_uses_id(self, rss_db):
        """Prefers entry.id when available."""
        entry = _make_feed_entry()
        entry.id = "unique-id-123"
        assert rss_db._entry_guid(entry) == "unique-id-123"

    def test_fallback_to_link(self, rss_db):
        """Falls back to link when id is missing."""
        entry = _make_feed_entry()
        entry.id = None
        entry.link = "https://example.com/article"
        assert rss_db._entry_guid(entry) == "https://example.com/article"

    def test_fallback_to_hash(self, rss_db):
        """Falls back to content hash when id and link are missing."""
        entry = _make_feed_entry()
        entry.id = None
        entry.link = None
        entry.title = "My Title"
        entry.summary = "My Summary"
        guid = rss_db._entry_guid(entry)
        assert len(guid) == 32  # SHA-256 truncated to 32 chars


# ---------------------------------------------------------------------------
# _format_entries
# ---------------------------------------------------------------------------


class TestFormatEntries:
    """Test entry formatting."""

    def test_empty(self, rss_db):
        """Empty list returns appropriate message."""
        result = rss_db._format_entries([])
        assert "No entries" in result

    def test_truncates_at_max(self, rss_db):
        """Only max_entries are shown."""
        entries = [{"title": f"Entry {i}", "link": "", "published": "", "summary": ""} for i in range(20)]
        result = rss_db._format_entries(entries, max_entries=5)
        assert "Entry 0" in result
        assert "Entry 4" in result
        assert "15 more" in result

    def test_long_summary_truncated(self, rss_db):
        """Long summaries are truncated."""
        entries = [{"title": "Post", "link": "", "published": "", "summary": "x" * 300}]
        result = rss_db._format_entries(entries)
        assert "..." in result


# ---------------------------------------------------------------------------
# _fetch_feed
# ---------------------------------------------------------------------------


class TestFetchFeed:
    """Test feed fetching."""

    def test_304_not_modified(self, rss_db):
        """304 response returns was_modified=False."""
        resp = _make_httpx_response(status_code=304)
        with (
            patch("httpx.get", return_value=resp),
            patch.object(rss_db, "_import_feedparser", return_value=MagicMock()),
        ):
            result = rss_db._fetch_feed("https://example.com/feed", etag="old-etag")

        assert result[3] is False  # was_modified

    def test_conditional_headers_sent(self, rss_db):
        """ETag and Last-Modified are sent as conditional headers."""
        resp = _make_httpx_response(status_code=304)
        mock_fp = MagicMock()
        with (
            patch("httpx.get", return_value=resp) as mock_get,
            patch.object(rss_db, "_import_feedparser", return_value=mock_fp),
        ):
            rss_db._fetch_feed("https://example.com/feed", etag="my-etag", modified="my-modified")

        headers = mock_get.call_args[1]["headers"]
        assert headers["If-None-Match"] == "my-etag"
        assert headers["If-Modified-Since"] == "my-modified"

    def test_successful_parse(self, rss_db):
        """Successful fetch returns parsed feed."""
        parsed = _make_parsed_feed()
        resp = _make_httpx_response(headers={"ETag": "new-etag"})
        mock_fp = MagicMock()
        mock_fp.parse.return_value = parsed
        with (
            patch("httpx.get", return_value=resp),
            patch.object(rss_db, "_import_feedparser", return_value=mock_fp),
        ):
            result = rss_db._fetch_feed("https://example.com/feed")

        assert result[0] == parsed
        assert result[1] == "new-etag"
        assert result[3] is True  # was_modified

    def test_bozo_with_no_entries_raises(self, rss_db):
        """Bozo feed with no entries raises ValueError."""
        parsed = MagicMock()
        parsed.bozo = True
        parsed.entries = []
        parsed.bozo_exception = Exception("bad XML")
        resp = _make_httpx_response()
        mock_fp = MagicMock()
        mock_fp.parse.return_value = parsed
        with (
            patch("httpx.get", return_value=resp),
            patch.object(rss_db, "_import_feedparser", return_value=mock_fp),
        ):
            with pytest.raises(ValueError, match="Feed parse error"):
                rss_db._fetch_feed("https://example.com/bad")

    def test_bozo_with_entries_ok(self, rss_db):
        """Bozo feed with entries is accepted (common for loose XML)."""
        parsed = _make_parsed_feed()
        parsed.bozo = True
        resp = _make_httpx_response()
        mock_fp = MagicMock()
        mock_fp.parse.return_value = parsed
        with (
            patch("httpx.get", return_value=resp),
            patch.object(rss_db, "_import_feedparser", return_value=mock_fp),
        ):
            result = rss_db._fetch_feed("https://example.com/loose")

        assert result[0] == parsed
