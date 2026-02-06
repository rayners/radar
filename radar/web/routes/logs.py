"""Logs routes."""

from datetime import datetime
from html import escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from radar.web import templates, get_common_context

router = APIRouter()


def _format_log_timestamp(iso_timestamp: str) -> str:
    """Format ISO timestamp to HH:MM:SS for display."""
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        return dt.strftime("%H:%M:%S")
    except Exception:
        return "--:--:--"


@router.get("/logs", response_class=HTMLResponse)
async def logs(request: Request):
    """Logs page."""
    from radar.logging import get_logs, get_log_stats, get_uptime

    context = get_common_context(request, "logs")

    # Load actual logs
    log_entries = get_logs(limit=100)
    stats = get_log_stats()

    context["logs"] = [
        {
            "timestamp": _format_log_timestamp(e.get("timestamp", "")),
            "level": e.get("level", "info"),
            "message": e.get("message", ""),
        }
        for e in log_entries
    ]
    context["error_count"] = stats["error_count"]
    context["warn_count"] = stats["warn_count"]
    context["api_calls"] = stats["api_calls"]
    context["uptime"] = get_uptime()

    return templates.TemplateResponse("logs.html", context)


@router.get("/api/logs")
async def api_logs(level: str = "all"):
    """Get filtered log entries as HTML."""
    from radar.logging import get_logs

    entries = get_logs(level=level, limit=200)

    if not entries:
        return HTMLResponse(
            '<div class="log-viewer__line">'
            '<span class="log-viewer__timestamp">--:--:--</span>'
            '<span class="log-viewer__level log-viewer__level--info">info</span>'
            '<span class="log-viewer__message text-muted">No log entries found</span>'
            '</div>'
        )

    lines = []
    for entry in entries:
        timestamp = _format_log_timestamp(entry.get("timestamp", ""))
        level_str = entry.get("level", "info")
        message = escape(entry.get("message", ""))
        lines.append(
            f'<div class="log-viewer__line">'
            f'<span class="log-viewer__timestamp">{timestamp}</span>'
            f'<span class="log-viewer__level log-viewer__level--{level_str}">{level_str}</span>'
            f'<span class="log-viewer__message">{message}</span>'
            f'</div>'
        )

    return HTMLResponse("\n".join(lines))


@router.get("/api/logs/stream")
async def api_logs_stream(since: str = ""):
    """Get new log entries since timestamp for HTMX streaming."""
    from radar.logging import get_recent_entries

    # Get entries since the provided timestamp
    entries = get_recent_entries(since=since if since else None, limit=50)

    if not entries:
        return HTMLResponse("")

    lines = []
    for entry in entries:
        timestamp = _format_log_timestamp(entry.get("timestamp", ""))
        level_str = entry.get("level", "info")
        message = escape(entry.get("message", ""))
        lines.append(
            f'<div class="log-viewer__line" data-timestamp="{entry.get("timestamp", "")}">'
            f'<span class="log-viewer__timestamp">{timestamp}</span>'
            f'<span class="log-viewer__level log-viewer__level--{level_str}">{level_str}</span>'
            f'<span class="log-viewer__message">{message}</span>'
            f'</div>'
        )

    return HTMLResponse("\n".join(lines))
