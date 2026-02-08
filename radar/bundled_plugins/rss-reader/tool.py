"""RSS/Atom feed reader plugin — subscribe, check, and monitor feeds."""

import hashlib
import logging
import sqlite3
from datetime import datetime, timedelta

import httpx

from radar.hooks import HookResult
from radar.semantic import _get_connection

logger = logging.getLogger("radar.plugins.rss-reader")

MAX_ERROR_COUNT = 5
MIN_INTERVAL_MINUTES = 5
DEFAULT_INTERVAL_MINUTES = 60
DEFAULT_MAX_ENTRIES = 10
FETCH_TIMEOUT = 30
USER_AGENT = "Radar/1.0 (RSS Reader)"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def _init_feed_tables(conn: sqlite3.Connection) -> None:
    """Create feed tables if they don't exist (lazy init)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rss_feeds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            check_interval_minutes INTEGER NOT NULL DEFAULT 60,
            max_entries INTEGER NOT NULL DEFAULT 10,
            enabled INTEGER NOT NULL DEFAULT 1,
            last_check TEXT,
            next_check TEXT,
            last_etag TEXT,
            last_modified TEXT,
            error_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feed_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feed_id INTEGER NOT NULL,
            guid TEXT NOT NULL,
            title TEXT,
            link TEXT,
            published TEXT,
            summary TEXT,
            detected_at TEXT NOT NULL,
            UNIQUE(feed_id, guid),
            FOREIGN KEY (feed_id) REFERENCES rss_feeds(id)
        )
    """)
    conn.commit()


def _get_db() -> sqlite3.Connection:
    """Get a database connection with feed tables initialized."""
    conn = _get_connection()
    _init_feed_tables(conn)
    return conn


# ---------------------------------------------------------------------------
# Feed parsing helpers
# ---------------------------------------------------------------------------

def _import_feedparser():
    """Import feedparser with a clear error message if missing."""
    try:
        import feedparser
        return feedparser
    except ImportError:
        raise ImportError(
            "feedparser is required for RSS feed monitoring. "
            "Install with: pip install radar[rss]"
        )


def _entry_guid(entry) -> str:
    """Extract a stable unique ID for a feed entry."""
    # Prefer explicit id/guid
    guid = getattr(entry, "id", None)
    if guid:
        return guid

    # Fall back to link
    link = getattr(entry, "link", None)
    if link:
        return link

    # Last resort: hash of title + summary
    title = getattr(entry, "title", "")
    summary = getattr(entry, "summary", "")
    content = f"{title}:{summary}"
    return hashlib.sha256(content.encode()).hexdigest()[:32]


def _entry_published(entry) -> str | None:
    """Extract published date from a feed entry."""
    published = getattr(entry, "published", None)
    if published:
        return published
    updated = getattr(entry, "updated", None)
    if updated:
        return updated
    return None


def _format_entries(entries: list[dict], max_entries: int = 10) -> str:
    """Format feed entries for display."""
    if not entries:
        return "No entries found."

    lines = []
    for entry in entries[:max_entries]:
        title = entry.get("title", "(no title)")
        link = entry.get("link", "")
        published = entry.get("published", "")
        summary = entry.get("summary", "")

        line = f"- {title}"
        if link:
            line += f"\n  Link: {link}"
        if published:
            line += f"\n  Published: {published}"
        if summary:
            # Truncate long summaries
            if len(summary) > 200:
                summary = summary[:200] + "..."
            line += f"\n  {summary}"
        lines.append(line)

    result = "\n".join(lines)
    if len(entries) > max_entries:
        result += f"\n\n({len(entries) - max_entries} more entries not shown)"
    return result


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def _fetch_feed(url: str, etag: str | None = None, modified: str | None = None):
    """Fetch and parse an RSS/Atom feed.

    Returns (parsed_feed, new_etag, new_modified, was_modified).
    Raises on network or parse errors.
    """
    feedparser = _import_feedparser()

    headers = {"User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    if modified:
        headers["If-Modified-Since"] = modified

    response = httpx.get(url, headers=headers, timeout=FETCH_TIMEOUT, follow_redirects=True)

    if response.status_code == 304:
        return None, etag, modified, False

    response.raise_for_status()

    parsed = feedparser.parse(response.text)
    if parsed.bozo and not parsed.entries:
        bozo_msg = str(getattr(parsed, "bozo_exception", "Unknown parse error"))
        raise ValueError(f"Feed parse error: {bozo_msg}")

    new_etag = response.headers.get("ETag", etag)
    new_modified = response.headers.get("Last-Modified", modified)

    return parsed, new_etag, new_modified, True


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

def subscribe_feed(
    name: str,
    url: str,
    check_interval_minutes: int = DEFAULT_INTERVAL_MINUTES,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> str:
    """Subscribe to an RSS/Atom feed."""
    if check_interval_minutes < MIN_INTERVAL_MINUTES:
        check_interval_minutes = MIN_INTERVAL_MINUTES

    # Validate feed by fetching it
    try:
        parsed, etag, modified, _ = _fetch_feed(url)
    except ImportError as e:
        return str(e)
    except Exception as e:
        return f"Failed to fetch feed: {e}"

    if parsed is None:
        return "Feed returned no content."

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = _get_db()

    # Check for duplicate URL
    existing = conn.execute(
        "SELECT id, name FROM rss_feeds WHERE url = ?", (url,)
    ).fetchone()
    if existing:
        return f"Already subscribed to this URL as '{existing[1]}' (id: {existing[0]})"

    conn.execute(
        """INSERT INTO rss_feeds
           (name, url, check_interval_minutes, max_entries, enabled,
            last_check, next_check, last_etag, last_modified,
            error_count, last_error, created_at)
           VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, 0, NULL, ?)""",
        (name, url, check_interval_minutes, max_entries,
         now, now, etag, modified, now),
    )
    feed_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Store baseline entries as "seen" so we don't report them as new
    for entry in parsed.entries:
        guid = _entry_guid(entry)
        try:
            conn.execute(
                """INSERT OR IGNORE INTO feed_entries
                   (feed_id, guid, title, link, published, summary, detected_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (feed_id, guid,
                 getattr(entry, "title", None),
                 getattr(entry, "link", None),
                 _entry_published(entry),
                 getattr(entry, "summary", None),
                 now),
            )
        except Exception:
            pass

    conn.commit()

    entry_count = len(parsed.entries)
    feed_title = getattr(parsed.feed, "title", name)
    return (
        f"Subscribed to '{feed_title}' as '{name}' (id: {feed_id})\n"
        f"URL: {url}\n"
        f"Check interval: {check_interval_minutes} minutes\n"
        f"Current entries: {entry_count} (stored as baseline)"
    )


def list_feeds(show_disabled: bool = False) -> str:
    """List all feed subscriptions."""
    conn = _get_db()

    if show_disabled:
        rows = conn.execute(
            "SELECT id, name, url, check_interval_minutes, enabled, "
            "last_check, error_count, last_error FROM rss_feeds "
            "ORDER BY name"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, name, url, check_interval_minutes, enabled, "
            "last_check, error_count, last_error FROM rss_feeds "
            "WHERE enabled = 1 ORDER BY name"
        ).fetchall()

    if not rows:
        return "No feed subscriptions found."

    lines = []
    for row in rows:
        feed_id, name, url, interval, enabled, last_check, error_count, last_error = row
        status = "active" if enabled else "paused"
        line = f"[{feed_id}] {name} ({status})"
        line += f"\n    URL: {url}"
        line += f"\n    Interval: {interval}m"
        if last_check:
            line += f" | Last check: {last_check}"
        if error_count > 0:
            line += f"\n    Errors: {error_count}"
            if last_error:
                line += f" | Last: {last_error}"
        lines.append(line)

    return "\n".join(lines)


def check_feed(feed_id: int | None = None, url: str | None = None) -> str:
    """Manually check a feed."""
    if feed_id is not None:
        return _check_feed_by_id(feed_id)
    elif url is not None:
        return _check_feed_oneoff(url)
    else:
        return "Please provide either feed_id or url."


def _check_feed_by_id(feed_id: int) -> str:
    """Check an existing feed subscription for new entries."""
    conn = _get_db()

    row = conn.execute(
        "SELECT id, name, url, max_entries, last_etag, last_modified "
        "FROM rss_feeds WHERE id = ?",
        (feed_id,),
    ).fetchone()

    if not row:
        return f"Feed id {feed_id} not found."

    _, name, url, max_entries, etag, modified = row
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        parsed, new_etag, new_modified, was_modified = _fetch_feed(url, etag, modified)
    except ImportError as e:
        return str(e)
    except Exception as e:
        # Record error
        conn.execute(
            "UPDATE rss_feeds SET error_count = error_count + 1, "
            "last_error = ?, last_check = ? WHERE id = ?",
            (str(e)[:500], now, feed_id),
        )
        _maybe_auto_pause(conn, feed_id)
        conn.commit()
        return f"Error checking feed '{name}': {e}"

    if not was_modified:
        conn.execute(
            "UPDATE rss_feeds SET last_check = ? WHERE id = ?",
            (now, feed_id),
        )
        conn.commit()
        return f"Feed '{name}' has not changed since last check."

    # Find new entries
    new_entries = _store_new_entries(conn, feed_id, parsed.entries, now)

    # Update feed metadata
    next_check_dt = datetime.now() + timedelta(
        minutes=conn.execute(
            "SELECT check_interval_minutes FROM rss_feeds WHERE id = ?",
            (feed_id,),
        ).fetchone()[0]
    )
    conn.execute(
        "UPDATE rss_feeds SET last_check = ?, next_check = ?, "
        "last_etag = ?, last_modified = ?, error_count = 0, last_error = NULL "
        "WHERE id = ?",
        (now, next_check_dt.strftime("%Y-%m-%d %H:%M:%S"),
         new_etag, new_modified, feed_id),
    )
    conn.commit()

    if not new_entries:
        return f"Feed '{name}' checked — no new entries."

    return f"Feed '{name}' — {len(new_entries)} new entry(ies):\n\n{_format_entries(new_entries, max_entries)}"


def _check_feed_oneoff(url: str) -> str:
    """One-off check of a feed URL (no subscription)."""
    try:
        parsed, _, _, _ = _fetch_feed(url)
    except ImportError as e:
        return str(e)
    except Exception as e:
        return f"Error fetching feed: {e}"

    if parsed is None:
        return "Feed returned no content."

    entries = []
    for entry in parsed.entries:
        entries.append({
            "title": getattr(entry, "title", None),
            "link": getattr(entry, "link", None),
            "published": _entry_published(entry),
            "summary": getattr(entry, "summary", None),
        })

    feed_title = getattr(parsed.feed, "title", url)
    return f"Feed: {feed_title}\n\n{_format_entries(entries)}"


def unsubscribe_feed(
    feed_id: int,
    delete: bool = False,
    resume: bool = False,
) -> str:
    """Pause, resume, or delete a feed subscription."""
    conn = _get_db()

    row = conn.execute(
        "SELECT name, enabled FROM rss_feeds WHERE id = ?", (feed_id,)
    ).fetchone()
    if not row:
        return f"Feed id {feed_id} not found."

    name, enabled = row

    if delete:
        conn.execute("DELETE FROM feed_entries WHERE feed_id = ?", (feed_id,))
        conn.execute("DELETE FROM rss_feeds WHERE id = ?", (feed_id,))
        conn.commit()
        return f"Feed '{name}' (id: {feed_id}) deleted."

    if resume:
        if enabled:
            return f"Feed '{name}' is already active."
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE rss_feeds SET enabled = 1, error_count = 0, "
            "last_error = NULL, next_check = ? WHERE id = ?",
            (now, feed_id),
        )
        conn.commit()
        return f"Feed '{name}' resumed."

    # Default: pause
    if not enabled:
        return f"Feed '{name}' is already paused."
    conn.execute("UPDATE rss_feeds SET enabled = 0 WHERE id = ?", (feed_id,))
    conn.commit()
    return f"Feed '{name}' paused."


# ---------------------------------------------------------------------------
# Entry storage
# ---------------------------------------------------------------------------

def _store_new_entries(
    conn: sqlite3.Connection,
    feed_id: int,
    entries,
    now: str,
) -> list[dict]:
    """Store new entries and return the list of genuinely new ones."""
    new_entries = []
    for entry in entries:
        guid = _entry_guid(entry)
        title = getattr(entry, "title", None)
        link = getattr(entry, "link", None)
        published = _entry_published(entry)
        summary = getattr(entry, "summary", None)

        try:
            conn.execute(
                """INSERT OR IGNORE INTO feed_entries
                   (feed_id, guid, title, link, published, summary, detected_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (feed_id, guid, title, link, published, summary, now),
            )
            if conn.execute("SELECT changes()").fetchone()[0] > 0:
                new_entries.append({
                    "title": title,
                    "link": link,
                    "published": published,
                    "summary": summary,
                })
        except Exception:
            pass

    return new_entries


def _maybe_auto_pause(conn: sqlite3.Connection, feed_id: int) -> None:
    """Auto-pause a feed if it has too many consecutive errors."""
    row = conn.execute(
        "SELECT error_count FROM rss_feeds WHERE id = ?", (feed_id,)
    ).fetchone()
    if row and row[0] >= MAX_ERROR_COUNT:
        conn.execute(
            "UPDATE rss_feeds SET enabled = 0 WHERE id = ?", (feed_id,)
        )
        logger.warning("Auto-paused feed %d after %d consecutive errors", feed_id, row[0])


# ---------------------------------------------------------------------------
# Heartbeat hook
# ---------------------------------------------------------------------------

def collect_feed_events() -> list[dict]:
    """Check due RSS feeds and return new entry events.

    Called by the HEARTBEAT_COLLECT hook during each heartbeat tick.
    """
    try:
        _import_feedparser()
    except ImportError:
        return []  # feedparser not installed, skip silently

    try:
        conn = _get_db()
    except Exception:
        return []

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    due_feeds = conn.execute(
        "SELECT id, name, url, max_entries, last_etag, last_modified, "
        "check_interval_minutes "
        "FROM rss_feeds WHERE enabled = 1 AND next_check <= ?",
        (now,),
    ).fetchall()

    if not due_feeds:
        return []

    events = []
    for row in due_feeds:
        feed_id, name, url, max_entries, etag, modified, interval = row

        try:
            parsed, new_etag, new_modified, was_modified = _fetch_feed(
                url, etag, modified
            )
        except Exception as e:
            conn.execute(
                "UPDATE rss_feeds SET error_count = error_count + 1, "
                "last_error = ?, last_check = ? WHERE id = ?",
                (str(e)[:500], now, feed_id),
            )
            _maybe_auto_pause(conn, feed_id)
            conn.commit()
            logger.warning("RSS feed '%s' fetch error: %s", name, e)
            continue

        next_check_dt = datetime.now() + timedelta(minutes=interval)
        next_check_str = next_check_dt.strftime("%Y-%m-%d %H:%M:%S")

        if not was_modified:
            conn.execute(
                "UPDATE rss_feeds SET last_check = ?, next_check = ? WHERE id = ?",
                (now, next_check_str, feed_id),
            )
            conn.commit()
            continue

        new_entries = _store_new_entries(conn, feed_id, parsed.entries, now)

        conn.execute(
            "UPDATE rss_feeds SET last_check = ?, next_check = ?, "
            "last_etag = ?, last_modified = ?, error_count = 0, last_error = NULL "
            "WHERE id = ?",
            (now, next_check_str, new_etag, new_modified, feed_id),
        )
        conn.commit()

        if new_entries:
            entry_text = _format_entries(new_entries, max_entries)
            events.append({
                "type": "rss_new_entries",
                "data": {
                    "description": f"RSS: {len(new_entries)} new entry(ies) in '{name}'",
                    "action": (
                        f"The RSS feed '{name}' ({url}) has "
                        f"{len(new_entries)} new entry(ies):\n\n"
                        f"{entry_text}\n\n"
                        f"Summarize the new entries and notify the user."
                    ),
                },
            })

    return events
