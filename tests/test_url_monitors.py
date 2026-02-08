"""Tests for URL monitor CRUD, fetching, diffing, and tools."""

import hashlib
import json
import zlib
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _setup(isolated_data_dir):
    """Ensure every test has an isolated data directory."""


# ---------------------------------------------------------------------------
# TestCreateAndGetMonitor
# ---------------------------------------------------------------------------

class TestCreateAndGetMonitor:
    def test_create_monitor_defaults(self):
        from radar.url_monitors import create_monitor, get_monitor

        mid = create_monitor("Test", "https://example.com")
        m = get_monitor(mid)
        assert m is not None
        assert m["name"] == "Test"
        assert m["url"] == "https://example.com"
        assert m["check_interval_minutes"] == 60
        assert m["enabled"] == 1
        assert m["css_selector"] is None
        assert m["error_count"] == 0

    def test_create_monitor_custom_interval(self):
        from radar.url_monitors import create_monitor, get_monitor

        mid = create_monitor("Fast", "https://example.com", check_interval_minutes=10)
        m = get_monitor(mid)
        assert m["check_interval_minutes"] == 10

    def test_create_monitor_with_selector(self):
        from radar.url_monitors import create_monitor, get_monitor

        mid = create_monitor("Sel", "https://example.com", css_selector=".content")
        m = get_monitor(mid)
        assert m["css_selector"] == ".content"

    def test_create_monitor_with_headers(self):
        from radar.url_monitors import create_monitor, get_monitor

        mid = create_monitor("Auth", "https://example.com", headers={"Authorization": "Bearer tok"})
        m = get_monitor(mid)
        assert json.loads(m["headers"]) == {"Authorization": "Bearer tok"}

    def test_create_monitor_interval_too_small(self):
        from radar.url_monitors import create_monitor

        with pytest.raises(ValueError, match="at least"):
            create_monitor("Bad", "https://example.com", check_interval_minutes=1)

    def test_get_nonexistent_monitor(self):
        from radar.url_monitors import get_monitor

        assert get_monitor(9999) is None

    def test_next_check_set_to_now(self):
        from radar.url_monitors import create_monitor, get_monitor

        mid = create_monitor("Now", "https://example.com")
        m = get_monitor(mid)
        # next_check should be set (approximately now)
        assert m["next_check"] is not None


# ---------------------------------------------------------------------------
# TestListMonitors
# ---------------------------------------------------------------------------

class TestListMonitors:
    def test_list_empty(self):
        from radar.url_monitors import list_monitors

        assert list_monitors() == []

    def test_list_all(self):
        from radar.url_monitors import create_monitor, list_monitors

        create_monitor("A", "https://a.com")
        create_monitor("B", "https://b.com")
        monitors = list_monitors()
        assert len(monitors) == 2

    def test_list_enabled_only(self):
        from radar.url_monitors import create_monitor, list_monitors, pause_monitor

        mid_a = create_monitor("A", "https://a.com")
        create_monitor("B", "https://b.com")
        pause_monitor(mid_a)
        enabled = list_monitors(enabled_only=True)
        assert len(enabled) == 1
        assert enabled[0]["name"] == "B"


# ---------------------------------------------------------------------------
# TestDeleteAndPauseMonitor
# ---------------------------------------------------------------------------

class TestDeleteAndPauseMonitor:
    def test_delete_monitor(self):
        from radar.url_monitors import create_monitor, delete_monitor, get_monitor

        mid = create_monitor("Del", "https://example.com")
        assert delete_monitor(mid) is True
        assert get_monitor(mid) is None

    def test_delete_nonexistent(self):
        from radar.url_monitors import delete_monitor

        assert delete_monitor(9999) is False

    def test_pause_and_resume(self):
        from radar.url_monitors import create_monitor, get_monitor, pause_monitor, resume_monitor

        mid = create_monitor("Toggle", "https://example.com")
        pause_monitor(mid)
        assert get_monitor(mid)["enabled"] == 0

        resume_monitor(mid)
        m = get_monitor(mid)
        assert m["enabled"] == 1
        assert m["error_count"] == 0

    def test_delete_cascade_changes(self):
        from radar.url_monitors import create_monitor, delete_monitor, record_change, get_changes

        mid = create_monitor("Cascade", "https://example.com")
        record_change(mid, "aaa", "bbb", "diff", 5)
        assert len(get_changes(mid)) == 1

        delete_monitor(mid)
        assert get_changes(mid) == []


# ---------------------------------------------------------------------------
# TestDueMonitors
# ---------------------------------------------------------------------------

class TestDueMonitors:
    def test_newly_created_is_due(self):
        from radar.url_monitors import create_monitor, get_due_monitors

        create_monitor("Due", "https://example.com")
        due = get_due_monitors()
        assert len(due) == 1
        assert due[0]["name"] == "Due"

    def test_paused_not_due(self):
        from radar.url_monitors import create_monitor, get_due_monitors, pause_monitor

        mid = create_monitor("Paused", "https://example.com")
        pause_monitor(mid)
        assert get_due_monitors() == []

    def test_future_check_not_due(self):
        from radar.url_monitors import create_monitor, get_due_monitors, _to_sqlite_datetime
        from radar.semantic import _get_connection

        mid = create_monitor("Future", "https://example.com")
        future = datetime.now() + timedelta(hours=1)
        conn = _get_connection()
        try:
            conn.execute(
                "UPDATE url_monitors SET next_check = ? WHERE id = ?",
                (_to_sqlite_datetime(future), mid),
            )
            conn.commit()
        finally:
            conn.close()

        assert get_due_monitors() == []


# ---------------------------------------------------------------------------
# TestFetchAndDiff
# ---------------------------------------------------------------------------

class TestFetchAndDiff:
    def test_extract_text_basic_html(self):
        from radar.url_monitors import extract_text

        html = "<html><body><h1>Hello</h1><p>World</p></body></html>"
        text = extract_text(html)
        assert "Hello" in text
        assert "World" in text

    def test_extract_text_strips_script_style(self):
        from radar.url_monitors import extract_text

        html = "<html><head><style>body{}</style></head><body><script>alert(1)</script><p>Visible</p></body></html>"
        text = extract_text(html)
        assert "Visible" in text
        assert "alert" not in text
        assert "body{}" not in text

    def test_extract_text_with_css_selector_no_bs4(self):
        from radar.url_monitors import extract_text

        # When bs4 is not available or selector matches nothing, falls back to full page
        html = "<html><body><p>Full page</p></body></html>"
        text = extract_text(html, css_selector=".nonexistent")
        assert "Full page" in text

    def test_compute_diff_basic(self):
        from radar.url_monitors import compute_diff

        diff = compute_diff("line1\nline2\n", "line1\nline3\n")
        assert diff["change_size"] > 0
        assert "line2" in diff["diff_summary"]
        assert "line3" in diff["diff_summary"]

    def test_compute_diff_identical(self):
        from radar.url_monitors import compute_diff

        diff = compute_diff("same\n", "same\n")
        assert diff["change_size"] == 0

    def test_compute_diff_truncation(self):
        from radar.url_monitors import compute_diff
        from radar.config import get_config

        config = get_config()
        config.web_monitor.max_diff_length = 50

        old = "\n".join(f"line{i}" for i in range(100))
        new = "\n".join(f"changed{i}" for i in range(100))
        diff = compute_diff(old, new)
        assert "truncated" in diff["diff_summary"]

    @patch("radar.url_monitors.httpx.get")
    def test_fetch_url_content_basic(self, mock_get):
        from radar.url_monitors import fetch_url_content

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>Hello</body></html>"
        mock_resp.headers = {"etag": '"abc"', "last-modified": "Wed, 01 Jan 2025 00:00:00 GMT"}
        mock_get.return_value = mock_resp

        result = fetch_url_content("https://example.com")
        assert result is not None
        assert "Hello" in result["content"]
        assert result["etag"] == '"abc"'

    @patch("radar.url_monitors.httpx.get")
    def test_fetch_url_content_304(self, mock_get):
        from radar.url_monitors import fetch_url_content

        mock_resp = MagicMock()
        mock_resp.status_code = 304
        mock_get.return_value = mock_resp

        result = fetch_url_content("https://example.com", last_etag='"abc"')
        assert result is None

    @patch("radar.url_monitors.httpx.get")
    def test_fetch_sends_conditional_headers(self, mock_get):
        from radar.url_monitors import fetch_url_content

        mock_resp = MagicMock()
        mock_resp.status_code = 304
        mock_get.return_value = mock_resp

        fetch_url_content(
            "https://example.com",
            last_etag='"xyz"',
            last_modified="Thu, 01 Jan 2025 00:00:00 GMT",
        )

        call_kwargs = mock_get.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers["If-None-Match"] == '"xyz"'
        assert headers["If-Modified-Since"] == "Thu, 01 Jan 2025 00:00:00 GMT"

    @patch("radar.url_monitors.httpx.get")
    def test_fetch_content_size_limit(self, mock_get):
        from radar.url_monitors import fetch_url_content
        from radar.config import get_config

        config = get_config()
        config.web_monitor.max_content_size = 100

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "x" * 500
        mock_resp.headers = {}
        mock_get.return_value = mock_resp

        result = fetch_url_content("https://example.com")
        assert len(result["content"]) == 100


# ---------------------------------------------------------------------------
# TestCheckMonitor
# ---------------------------------------------------------------------------

class TestCheckMonitor:
    @patch("radar.url_monitors.httpx.get")
    def test_first_check_stores_baseline(self, mock_get):
        from radar.url_monitors import create_monitor, get_monitor, check_monitor

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>Initial content</body></html>"
        mock_resp.headers = {"etag": '"v1"'}
        mock_get.return_value = mock_resp

        mid = create_monitor("Baseline", "https://example.com")
        monitor = get_monitor(mid)
        result = check_monitor(monitor)

        assert result is None  # First check, no diff
        updated = get_monitor(mid)
        assert updated["last_hash"] is not None
        assert updated["last_content"] is not None
        assert updated["last_etag"] == '"v1"'

    @patch("radar.url_monitors.httpx.get")
    def test_check_detects_change(self, mock_get):
        from radar.url_monitors import create_monitor, get_monitor, check_monitor

        # First check
        mock_resp1 = MagicMock()
        mock_resp1.status_code = 200
        mock_resp1.text = "<html><body>Version 1</body></html>"
        mock_resp1.headers = {}
        mock_get.return_value = mock_resp1

        mid = create_monitor("Change", "https://example.com")
        monitor = get_monitor(mid)
        check_monitor(monitor)

        # Second check with different content
        mock_resp2 = MagicMock()
        mock_resp2.status_code = 200
        mock_resp2.text = "<html><body>Version 2</body></html>"
        mock_resp2.headers = {}
        mock_get.return_value = mock_resp2

        monitor = get_monitor(mid)
        result = check_monitor(monitor)

        assert result is not None
        assert result["change_size"] > 0
        assert "Version 1" in result["diff_summary"] or "Version 2" in result["diff_summary"]

    @patch("radar.url_monitors.httpx.get")
    def test_check_no_change(self, mock_get):
        from radar.url_monitors import create_monitor, get_monitor, check_monitor

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>Same content</body></html>"
        mock_resp.headers = {}
        mock_get.return_value = mock_resp

        mid = create_monitor("NoChange", "https://example.com")
        monitor = get_monitor(mid)
        check_monitor(monitor)

        # Same content again
        monitor = get_monitor(mid)
        result = check_monitor(monitor)
        assert result is None

    @patch("radar.url_monitors.httpx.get")
    def test_check_304_no_change(self, mock_get):
        from radar.url_monitors import create_monitor, get_monitor, check_monitor

        # First check
        mock_resp1 = MagicMock()
        mock_resp1.status_code = 200
        mock_resp1.text = "<html><body>Content</body></html>"
        mock_resp1.headers = {"etag": '"v1"'}
        mock_get.return_value = mock_resp1

        mid = create_monitor("304", "https://example.com")
        monitor = get_monitor(mid)
        check_monitor(monitor)

        # 304 response
        mock_resp2 = MagicMock()
        mock_resp2.status_code = 304
        mock_get.return_value = mock_resp2

        monitor = get_monitor(mid)
        result = check_monitor(monitor)
        assert result is None

    @patch("radar.url_monitors.httpx.get")
    def test_check_error_increments_count(self, mock_get):
        from radar.url_monitors import create_monitor, get_monitor, check_monitor

        mock_get.side_effect = Exception("Connection failed")

        mid = create_monitor("Error", "https://example.com")
        monitor = get_monitor(mid)

        with pytest.raises(Exception, match="Connection failed"):
            check_monitor(monitor)

        updated = get_monitor(mid)
        assert updated["error_count"] == 1
        assert "Connection failed" in updated["last_error"]

    @patch("radar.url_monitors.httpx.get")
    def test_auto_pause_after_max_errors(self, mock_get):
        from radar.url_monitors import create_monitor, get_monitor, check_monitor
        from radar.config import get_config

        config = get_config()
        config.web_monitor.max_error_count = 2

        mock_get.side_effect = Exception("fail")

        mid = create_monitor("AutoPause", "https://example.com")
        for _ in range(2):
            monitor = get_monitor(mid)
            try:
                check_monitor(monitor)
            except Exception:
                pass

        updated = get_monitor(mid)
        assert updated["enabled"] == 0

    @patch("radar.url_monitors.httpx.get")
    def test_min_change_threshold_filters_small_changes(self, mock_get):
        from radar.url_monitors import create_monitor, get_monitor, check_monitor

        # First check
        mock_resp1 = MagicMock()
        mock_resp1.status_code = 200
        mock_resp1.text = "<html><body>Line1\nLine2\nLine3</body></html>"
        mock_resp1.headers = {}
        mock_get.return_value = mock_resp1

        mid = create_monitor("Threshold", "https://example.com", min_change_threshold=100)
        monitor = get_monitor(mid)
        check_monitor(monitor)

        # Small change
        mock_resp2 = MagicMock()
        mock_resp2.status_code = 200
        mock_resp2.text = "<html><body>Line1\nLine2 updated\nLine3</body></html>"
        mock_resp2.headers = {}
        mock_get.return_value = mock_resp2

        monitor = get_monitor(mid)
        result = check_monitor(monitor)
        assert result is None  # Below threshold


# ---------------------------------------------------------------------------
# TestChangeHistory
# ---------------------------------------------------------------------------

class TestChangeHistory:
    def test_record_and_get_changes(self):
        from radar.url_monitors import create_monitor, record_change, get_changes

        mid = create_monitor("History", "https://example.com")
        record_change(mid, "hash1", "hash2", "diff text", 5)
        record_change(mid, "hash2", "hash3", "diff text 2", 3)

        changes = get_changes(mid)
        assert len(changes) == 2
        # Most recent first
        assert changes[0]["new_hash"] == "hash3"

    def test_get_changes_limit(self):
        from radar.url_monitors import create_monitor, record_change, get_changes

        mid = create_monitor("Limit", "https://example.com")
        for i in range(5):
            record_change(mid, f"h{i}", f"h{i+1}", f"diff{i}", i)

        changes = get_changes(mid, limit=2)
        assert len(changes) == 2

    def test_get_changes_empty(self):
        from radar.url_monitors import create_monitor, get_changes

        mid = create_monitor("Empty", "https://example.com")
        assert get_changes(mid) == []


# ---------------------------------------------------------------------------
# TestTools
# ---------------------------------------------------------------------------

class TestTools:
    def test_monitor_url_tool(self):
        from radar.tools.url_monitor import monitor_url

        result = monitor_url("Test Site", "https://example.com")
        assert "ID" in result
        assert "Test Site" in result
        assert "60 minutes" in result

    def test_monitor_url_custom_interval(self):
        from radar.tools.url_monitor import monitor_url

        result = monitor_url("Fast", "https://example.com", interval_minutes=15)
        assert "15 minutes" in result

    def test_monitor_url_bad_interval(self):
        from radar.tools.url_monitor import monitor_url

        result = monitor_url("Bad", "https://example.com", interval_minutes=1)
        assert "Error" in result

    def test_list_url_monitors_tool_empty(self):
        from radar.tools.url_monitor import list_url_monitors

        result = list_url_monitors()
        assert "No URL monitors" in result

    def test_list_url_monitors_tool_with_monitors(self):
        from radar.url_monitors import create_monitor
        from radar.tools.url_monitor import list_url_monitors

        create_monitor("A", "https://a.com")
        create_monitor("B", "https://b.com")

        result = list_url_monitors()
        assert "A" in result
        assert "B" in result

    @patch("radar.url_monitors.httpx.get")
    def test_check_url_tool_by_id(self, mock_get):
        from radar.url_monitors import create_monitor, get_monitor, check_monitor
        from radar.tools.url_monitor import check_url

        # Setup: create and do first check
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>Content</body></html>"
        mock_resp.headers = {}
        mock_get.return_value = mock_resp

        mid = create_monitor("Check", "https://example.com")
        monitor = get_monitor(mid)
        check_monitor(monitor)

        # Check via tool (no change)
        result = check_url(monitor_id=mid)
        assert "No changes" in result

    @patch("radar.url_monitors.httpx.get")
    def test_check_url_tool_one_off(self, mock_get):
        from radar.tools.url_monitor import check_url

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>Hello World</body></html>"
        mock_resp.headers = {}
        mock_get.return_value = mock_resp

        result = check_url(url="https://example.com")
        assert "Hello World" in result

    def test_check_url_no_args(self):
        from radar.tools.url_monitor import check_url

        result = check_url()
        assert "Error" in result

    def test_check_url_bad_id(self):
        from radar.tools.url_monitor import check_url

        result = check_url(monitor_id=9999)
        assert "not found" in result

    def test_remove_monitor_tool_pause(self):
        from radar.url_monitors import create_monitor, get_monitor
        from radar.tools.url_monitor import remove_monitor

        mid = create_monitor("Pause", "https://example.com")
        result = remove_monitor(mid)
        assert "paused" in result
        assert get_monitor(mid)["enabled"] == 0

    def test_remove_monitor_tool_delete(self):
        from radar.url_monitors import create_monitor, get_monitor
        from radar.tools.url_monitor import remove_monitor

        mid = create_monitor("Delete", "https://example.com")
        result = remove_monitor(mid, delete=True)
        assert "deleted" in result
        assert get_monitor(mid) is None

    def test_remove_monitor_tool_resume(self):
        from radar.url_monitors import create_monitor, get_monitor, pause_monitor
        from radar.tools.url_monitor import remove_monitor

        mid = create_monitor("Resume", "https://example.com")
        pause_monitor(mid)
        result = remove_monitor(mid, resume=True)
        assert "resumed" in result
        assert get_monitor(mid)["enabled"] == 1

    def test_remove_monitor_not_found(self):
        from radar.tools.url_monitor import remove_monitor

        result = remove_monitor(9999)
        assert "not found" in result
