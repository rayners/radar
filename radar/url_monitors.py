"""URL monitor CRUD, fetching, diffing, and heartbeat integration."""

import difflib
import hashlib
import json
import zlib
from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import Any

import httpx

from radar.config import get_config
from radar.retry import is_retryable_httpx_error, retry_call
from radar.semantic import _get_connection


# ---------------------------------------------------------------------------
# HTML text extraction
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    """Strip HTML tags and return visible text."""

    _skip_tags = frozenset({"script", "style", "head", "noscript"})

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._skip_tags and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._parts.append(text)

    def get_text(self) -> str:
        return "\n".join(self._parts)


def extract_text(html: str, css_selector: str | None = None) -> str:
    """Extract visible text from HTML.

    If *css_selector* is given and beautifulsoup4 is available, only text
    within matching elements is returned.  Falls back to full-page extraction.
    """
    if css_selector:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            elements = soup.select(css_selector)
            if elements:
                return "\n".join(el.get_text(separator="\n", strip=True) for el in elements)
        except ImportError:
            pass  # fall through to stdlib parser

    parser = _TextExtractor()
    parser.feed(html)
    return parser.get_text()


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def fetch_url_content(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    last_etag: str | None = None,
    last_modified: str | None = None,
) -> dict[str, Any] | None:
    """Fetch a URL, honouring conditional-request headers.

    Returns ``None`` on HTTP 304 (not modified).  Otherwise returns::

        {"content": str, "etag": str|None, "last_modified": str|None}
    """
    config = get_config()
    wm = config.web_monitor

    req_headers: dict[str, str] = {"User-Agent": wm.user_agent}
    if headers:
        req_headers.update(headers)
    if last_etag:
        req_headers["If-None-Match"] = last_etag
    if last_modified:
        req_headers["If-Modified-Since"] = last_modified

    retry_cfg = config.retry
    max_retries = (retry_cfg.max_retries if retry_cfg.url_monitor_retries else 0)

    def _do_fetch():
        resp = httpx.get(url, headers=req_headers, timeout=wm.fetch_timeout, follow_redirects=True)
        if resp.status_code == 304:
            return None
        resp.raise_for_status()
        return resp

    response = retry_call(
        _do_fetch, max_retries=max_retries, retry_cfg=retry_cfg,
        is_retryable_fn=is_retryable_httpx_error, provider="url-monitor", label=url,
    )

    if response is None:
        return None

    content = response.text
    if len(content) > wm.max_content_size:
        content = content[:wm.max_content_size]

    return {
        "content": content,
        "etag": response.headers.get("etag"),
        "last_modified": response.headers.get("last-modified"),
    }


# ---------------------------------------------------------------------------
# Diffing
# ---------------------------------------------------------------------------

def compute_diff(old_text: str, new_text: str) -> dict[str, Any]:
    """Compute a unified diff between *old_text* and *new_text*.

    Returns::

        {"diff_summary": str, "change_size": int}
    """
    config = get_config()
    max_len = config.web_monitor.max_diff_length

    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff_lines = list(difflib.unified_diff(old_lines, new_lines, fromfile="before", tofile="after", lineterm=""))
    change_size = sum(
        1 for line in diff_lines
        if (line.startswith("+") and not line.startswith("+++"))
        or (line.startswith("-") and not line.startswith("---"))
    )

    diff_text = "\n".join(diff_lines)
    if len(diff_text) > max_len:
        diff_text = diff_text[:max_len] + "\n... (truncated)"

    return {"diff_summary": diff_text, "change_size": change_size}


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def _to_sqlite_datetime(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def create_monitor(
    name: str,
    url: str,
    check_interval_minutes: int | None = None,
    css_selector: str | None = None,
    min_change_threshold: int = 0,
    headers: dict[str, str] | None = None,
    created_by: str = "chat",
) -> int:
    """Create a new URL monitor. Returns the monitor ID."""
    config = get_config()
    wm = config.web_monitor

    if check_interval_minutes is None:
        check_interval_minutes = wm.default_interval_minutes
    if check_interval_minutes < wm.min_interval_minutes:
        raise ValueError(f"Interval must be at least {wm.min_interval_minutes} minutes")

    now = datetime.now()
    next_check = now  # Check immediately on first heartbeat

    conn = _get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO url_monitors
            (name, url, check_interval_minutes, css_selector, min_change_threshold,
             headers, next_check, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name, url, check_interval_minutes, css_selector, min_change_threshold,
                json.dumps(headers) if headers else None,
                _to_sqlite_datetime(next_check),
                created_by,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_monitor(monitor_id: int) -> dict[str, Any] | None:
    """Get a monitor by ID."""
    conn = _get_connection()
    try:
        cursor = conn.execute("SELECT * FROM url_monitors WHERE id = ?", (monitor_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_monitors(enabled_only: bool = False) -> list[dict[str, Any]]:
    """List all monitors."""
    conn = _get_connection()
    try:
        where = "WHERE enabled = 1 " if enabled_only else ""
        cursor = conn.execute(f"SELECT * FROM url_monitors {where}ORDER BY created_at DESC")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def delete_monitor(monitor_id: int) -> bool:
    """Delete a monitor and its change history. Returns True if found."""
    conn = _get_connection()
    try:
        conn.execute("DELETE FROM url_changes WHERE monitor_id = ?", (monitor_id,))
        cursor = conn.execute("DELETE FROM url_monitors WHERE id = ?", (monitor_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def pause_monitor(monitor_id: int) -> bool:
    """Pause (disable) a monitor."""
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "UPDATE url_monitors SET enabled = 0 WHERE id = ?", (monitor_id,)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def resume_monitor(monitor_id: int) -> bool:
    """Resume (enable) a paused monitor and reset error count."""
    now = datetime.now()
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "UPDATE url_monitors SET enabled = 1, error_count = 0, next_check = ? WHERE id = ?",
            (_to_sqlite_datetime(now), monitor_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Heartbeat integration
# ---------------------------------------------------------------------------

def get_due_monitors() -> list[dict[str, Any]]:
    """Get all enabled monitors whose next_check is due."""
    conn = _get_connection()
    try:
        cursor = conn.execute(
            """
            SELECT * FROM url_monitors
            WHERE next_check <= datetime('now', 'localtime')
            AND enabled = 1
            ORDER BY next_check ASC
            """
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def check_monitor(monitor: dict[str, Any]) -> dict[str, Any] | None:
    """Fetch a monitor's URL, diff against previous content, update DB.

    Returns a change dict if content changed, or ``None`` if unchanged.
    """
    config = get_config()
    wm = config.web_monitor
    monitor_id = monitor["id"]

    custom_headers = None
    if monitor.get("headers"):
        try:
            custom_headers = json.loads(monitor["headers"])
        except (json.JSONDecodeError, TypeError):
            pass

    try:
        result = fetch_url_content(
            monitor["url"],
            headers=custom_headers,
            last_etag=monitor.get("last_etag"),
            last_modified=monitor.get("last_modified"),
        )
    except Exception as e:
        _record_error(monitor_id, str(e), wm.max_error_count)
        raise

    now = datetime.now()
    next_check = now + timedelta(minutes=monitor["check_interval_minutes"])

    if result is None:
        # 304 Not Modified
        _update_check_time(monitor_id, now, next_check)
        return None

    raw_html = result["content"]
    text = extract_text(raw_html, monitor.get("css_selector"))
    new_hash = hashlib.sha256(text.encode()).hexdigest()
    compressed = zlib.compress(text.encode())

    old_hash = monitor.get("last_hash")

    if old_hash is None:
        # First fetch — store baseline, no diff
        _update_monitor_content(
            monitor_id, now, next_check, new_hash, compressed,
            result.get("etag"), result.get("last_modified"),
        )
        return None

    if new_hash == old_hash:
        # No change
        _update_check_time(monitor_id, now, next_check,
                           etag=result.get("etag"),
                           last_modified=result.get("last_modified"))
        return None

    # Content changed — compute diff
    old_text = ""
    if monitor.get("last_content"):
        try:
            old_text = zlib.decompress(monitor["last_content"]).decode()
        except Exception:
            pass

    diff = compute_diff(old_text, text)

    # Apply minimum change threshold
    if monitor.get("min_change_threshold") and diff["change_size"] < monitor["min_change_threshold"]:
        _update_check_time(monitor_id, now, next_check,
                           etag=result.get("etag"),
                           last_modified=result.get("last_modified"))
        return None

    # Record change
    record_change(monitor_id, old_hash, new_hash, diff["diff_summary"], diff["change_size"])

    # Update monitor with new content
    _update_monitor_content(
        monitor_id, now, next_check, new_hash, compressed,
        result.get("etag"), result.get("last_modified"),
    )

    return {
        "monitor_id": monitor_id,
        "name": monitor["name"],
        "url": monitor["url"],
        "old_hash": old_hash,
        "new_hash": new_hash,
        "diff_summary": diff["diff_summary"],
        "change_size": diff["change_size"],
    }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _update_check_time(
    monitor_id: int,
    last_check: datetime,
    next_check: datetime,
    etag: str | None = None,
    last_modified: str | None = None,
) -> None:
    conn = _get_connection()
    try:
        conn.execute(
            """
            UPDATE url_monitors
            SET last_check = ?, next_check = ?, error_count = 0,
                last_etag = COALESCE(?, last_etag),
                last_modified = COALESCE(?, last_modified)
            WHERE id = ?
            """,
            (_to_sqlite_datetime(last_check), _to_sqlite_datetime(next_check),
             etag, last_modified, monitor_id),
        )
        conn.commit()
    finally:
        conn.close()


def _update_monitor_content(
    monitor_id: int,
    last_check: datetime,
    next_check: datetime,
    new_hash: str,
    compressed_content: bytes,
    etag: str | None,
    last_modified: str | None,
) -> None:
    conn = _get_connection()
    try:
        conn.execute(
            """
            UPDATE url_monitors
            SET last_check = ?, next_check = ?, last_hash = ?, last_content = ?,
                last_etag = ?, last_modified = ?, error_count = 0
            WHERE id = ?
            """,
            (_to_sqlite_datetime(last_check), _to_sqlite_datetime(next_check),
             new_hash, compressed_content, etag, last_modified, monitor_id),
        )
        conn.commit()
    finally:
        conn.close()


def _record_error(monitor_id: int, error: str, max_error_count: int) -> None:
    """Increment error count and auto-pause if threshold exceeded."""
    conn = _get_connection()
    try:
        conn.execute(
            "UPDATE url_monitors SET error_count = error_count + 1, last_error = ? WHERE id = ?",
            (error, monitor_id),
        )
        # Auto-pause after too many consecutive errors
        conn.execute(
            "UPDATE url_monitors SET enabled = 0 WHERE id = ? AND error_count >= ?",
            (monitor_id, max_error_count),
        )
        conn.commit()
    finally:
        conn.close()


def record_change(
    monitor_id: int,
    old_hash: str | None,
    new_hash: str,
    diff_summary: str,
    change_size: int,
) -> int:
    """Record a change in the history table. Returns the change ID."""
    conn = _get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO url_changes (monitor_id, old_hash, new_hash, diff_summary, change_size)
            VALUES (?, ?, ?, ?, ?)
            """,
            (monitor_id, old_hash, new_hash, diff_summary, change_size),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_changes(monitor_id: int, limit: int = 10) -> list[dict[str, Any]]:
    """Get recent changes for a monitor."""
    conn = _get_connection()
    try:
        cursor = conn.execute(
            """
            SELECT * FROM url_changes
            WHERE monitor_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (monitor_id, limit),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
