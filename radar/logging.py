"""Logging system for Radar daemon."""

import json
from collections import deque
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

# Global state
_log_buffer: deque[dict[str, Any]] = deque(maxlen=1000)
_buffer_lock = Lock()
_daemon_start_time: datetime | None = None
_api_call_count = 0
_api_call_lock = Lock()


def _get_log_file() -> Path:
    """Get the path to the log file."""
    data_dir = Path.home() / ".local" / "share" / "radar"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "radar.log"


def setup_logging() -> None:
    """Initialize the logging system. Call on daemon start."""
    global _daemon_start_time, _api_call_count
    _daemon_start_time = datetime.now()
    _api_call_count = 0
    log("info", "Radar daemon started")


def log(level: str, message: str, **extra: Any) -> None:
    """Log a message.

    Args:
        level: Log level (debug, info, warn, error)
        message: Log message
        **extra: Additional structured data to include
    """
    global _log_buffer

    entry = {
        "timestamp": datetime.now().isoformat(),
        "level": level.lower(),
        "message": message,
        **extra,
    }

    # Add to in-memory buffer
    with _buffer_lock:
        _log_buffer.append(entry)

    # Append to file
    try:
        log_file = _get_log_file()
        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Don't crash on log write failures


def increment_api_calls() -> None:
    """Increment the API call counter."""
    global _api_call_count
    with _api_call_lock:
        _api_call_count += 1


def get_logs(
    level: str = "all",
    limit: int = 200,
    since: str | None = None,
) -> list[dict[str, Any]]:
    """Get log entries.

    Args:
        level: Filter by level ("all", "error", "warn", "info", "debug")
        limit: Maximum number of entries to return
        since: Only return entries after this ISO timestamp

    Returns:
        List of log entries, newest first
    """
    global _log_buffer

    # Get from buffer first (recent logs)
    with _buffer_lock:
        entries = list(_log_buffer)

    # If buffer is small, also read from file
    if len(entries) < limit:
        try:
            log_file = _get_log_file()
            if log_file.exists():
                with open(log_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                entry = json.loads(line)
                                # Only add if not already in buffer
                                if entry not in entries:
                                    entries.append(entry)
                            except json.JSONDecodeError:
                                continue
        except Exception:
            pass

    # Sort by timestamp descending
    entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    # Filter by level
    if level != "all":
        level_order = {"error": 0, "warn": 1, "info": 2, "debug": 3}
        min_level = level_order.get(level, 2)
        entries = [
            e for e in entries
            if level_order.get(e.get("level", "info"), 2) <= min_level
        ]

    # Filter by since timestamp
    if since:
        entries = [e for e in entries if e.get("timestamp", "") > since]

    return entries[:limit]


def get_log_stats() -> dict[str, Any]:
    """Get log statistics for the last 24 hours.

    Returns:
        Dict with error_count, warn_count, api_calls
    """
    global _api_call_count

    # Calculate 24h ago timestamp
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()

    entries = get_logs(limit=10000)
    recent = [e for e in entries if e.get("timestamp", "") > cutoff]

    error_count = sum(1 for e in recent if e.get("level") == "error")
    warn_count = sum(1 for e in recent if e.get("level") == "warn")

    with _api_call_lock:
        api_calls = _api_call_count

    return {
        "error_count": error_count,
        "warn_count": warn_count,
        "api_calls": api_calls,
    }


def get_uptime() -> str:
    """Get daemon uptime as a human-readable string.

    Returns:
        Uptime string like "3d 14h" or "45m" or "—" if not running
    """
    global _daemon_start_time

    if _daemon_start_time is None:
        return "—"

    delta = datetime.now() - _daemon_start_time
    total_seconds = int(delta.total_seconds())

    if total_seconds < 60:
        return f"{total_seconds}s"

    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes}m"

    hours = minutes // 60
    if hours < 24:
        remaining_minutes = minutes % 60
        if remaining_minutes:
            return f"{hours}h {remaining_minutes}m"
        return f"{hours}h"

    days = hours // 24
    remaining_hours = hours % 24
    if remaining_hours:
        return f"{days}d {remaining_hours}h"
    return f"{days}d"


def get_recent_entries(since: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Get recent log entries for streaming.

    Args:
        since: Only return entries after this ISO timestamp
        limit: Maximum entries to return

    Returns:
        List of log entries, oldest first (for appending)
    """
    entries = get_logs(limit=limit, since=since)
    # Reverse to get oldest first for appending
    return list(reversed(entries))
