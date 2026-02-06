"""Calendar tool using khal CLI."""

import json
import subprocess
import time
from datetime import datetime, timedelta

from radar.tools import tool

# ── Cache ──
_cache: dict[str, tuple[float, str]] = {}
_CACHE_TTL = 300  # seconds


def _get_cached(key: str) -> str | None:
    """Return cached result if within TTL, else None."""
    if key in _cache:
        ts, result = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return result
    return None


def _set_cached(key: str, result: str) -> None:
    _cache[key] = (time.time(), result)


def reset_cache() -> None:
    """Clear cache (for testing)."""
    _cache.clear()


# ── khal CLI wrapper ──
_JSON_FIELDS = ["title", "start-date", "start-time", "end-time",
                "location", "description", "calendar", "all-day"]


def _run_khal(args: list[str]) -> tuple[str, bool]:
    """Run a khal CLI command.

    Args:
        args: Command arguments (without 'khal' prefix)

    Returns:
        Tuple of (output, success)
    """
    try:
        result = subprocess.run(
            ["khal"] + args,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip()
            return error, False
        return result.stdout, True
    except FileNotFoundError:
        return "Error: khal not installed. Install with: pip install khal", False
    except subprocess.TimeoutExpired:
        return "Error: khal command timed out", False
    except Exception as e:
        return f"Error: {e}", False


def _parse_json_events(output: str) -> list[dict]:
    """Parse khal --json output into event dicts."""
    if not output.strip():
        return []
    try:
        data = json.loads(output)
        if isinstance(data, list):
            return data
        return [data]
    except json.JSONDecodeError:
        return []


def _format_events(events: list[dict], header: str) -> str:
    """Format parsed events as readable markdown."""
    if not events:
        return f"**{header}**\n\nNo events found."

    lines = [f"**{header}**", ""]

    # Group events by date
    current_date = None
    for event in events:
        date = event.get("start-date", "")
        if date != current_date:
            if current_date is not None:
                lines.append("")
            lines.append(f"**{date}**")
            current_date = date

        all_day = event.get("all-day", False)
        start_time = event.get("start-time", "")
        end_time = event.get("end-time", "")

        if all_day:
            time_str = "All day"
        elif start_time and end_time:
            time_str = f"{start_time} - {end_time}"
        elif start_time:
            time_str = start_time
        else:
            time_str = "All day"

        title = event.get("title", "") or "(No title)"
        line = f"- {time_str}: {title}"

        location = event.get("location", "")
        if location:
            line += f" ({location})"
        calendar_name = event.get("calendar", "")
        if calendar_name:
            line += f" [{calendar_name}]"

        lines.append(line)

    return "\n".join(lines)


# ── Operations ──

def _list_events(start: str, end: str, calendar_name: str | None,
                 header: str) -> str:
    """List events in a date range using khal list --json."""
    cache_key = f"list:{start}:{end}:{calendar_name}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    args = ["list", "--json"] + _JSON_FIELDS + ["-df", ""]
    if calendar_name:
        args.extend(["-a", calendar_name])
    args.extend([start, end])

    output, success = _run_khal(args)
    if not success:
        return f"Error listing events: {output}"

    events = _parse_json_events(output)
    result = _format_events(events, header)

    _set_cached(cache_key, result)
    return result


def _list_calendars() -> str:
    """List configured calendars using khal printcalendars."""
    cache_key = "calendars"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    output, success = _run_khal(["printcalendars"])
    if not success:
        return f"Error listing calendars: {output}"

    calendars = [c.strip() for c in output.strip().splitlines() if c.strip()]
    if not calendars:
        result = "**Calendars**\n\nNo calendars configured."
    else:
        lines = ["**Calendars**", ""]
        for cal in calendars:
            lines.append(f"- {cal}")
        result = "\n".join(lines)

    _set_cached(cache_key, result)
    return result


def _get_reminders(minutes: int = 15) -> str:
    """Get events starting within N minutes (for heartbeat).

    Returns formatted string of upcoming events, or empty string if none.
    """
    cache_key = f"reminders:{minutes}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    now = datetime.now()
    end = now + timedelta(minutes=minutes)
    start_str = now.strftime("%Y-%m-%d %H:%M")
    end_str = end.strftime("%Y-%m-%d %H:%M")

    args = ["list", "--json"] + _JSON_FIELDS + ["-df", "",
                                                 start_str, end_str]

    output, success = _run_khal(args)
    if not success:
        _set_cached(cache_key, "")
        return ""

    events = _parse_json_events(output)
    if not events:
        _set_cached(cache_key, "")
        return ""

    lines = []
    for event in events:
        if event.get("all-day", False):
            continue  # Skip all-day events for reminders
        title = event.get("title", "") or "(No title)"
        start_time = event.get("start-time", "")
        line = f"- {start_time}: {title}"
        location = event.get("location", "")
        if location:
            line += f" ({location})"
        lines.append(line)

    result = "\n".join(lines) if lines else ""
    _set_cached(cache_key, result)
    return result


# ── Tool registration ──

@tool(
    name="calendar",
    description="Query calendar events using khal. Shows upcoming events, "
    "today's schedule, or events in a date range. Requires khal to be configured.",
    parameters={
        "operation": {
            "type": "string",
            "enum": ["today", "tomorrow", "week", "list", "calendars"],
            "description": "What to show: today/tomorrow/week for quick views, "
            "list for custom date range, calendars to show available calendars",
        },
        "start_date": {
            "type": "string",
            "description": "Start date YYYY-MM-DD (for 'list' operation)",
            "optional": True,
        },
        "end_date": {
            "type": "string",
            "description": "End date YYYY-MM-DD (for 'list' operation)",
            "optional": True,
        },
        "calendar_name": {
            "type": "string",
            "description": "Filter to a specific calendar (use 'calendars' to see available)",
            "optional": True,
        },
    },
)
def calendar(operation: str, start_date: str | None = None,
             end_date: str | None = None,
             calendar_name: str | None = None) -> str:
    """Query calendar events.

    Args:
        operation: One of 'today', 'tomorrow', 'week', 'list', 'calendars'
        start_date: Start date for 'list' operation (YYYY-MM-DD)
        end_date: End date for 'list' operation (YYYY-MM-DD)
        calendar_name: Filter to a specific calendar

    Returns:
        Formatted calendar information
    """
    operation = operation.lower().strip()

    if operation == "today":
        return _list_events("today", "tomorrow", calendar_name,
                            "Today's Events")
    elif operation == "tomorrow":
        return _list_events("tomorrow", "2d", calendar_name,
                            "Tomorrow's Events")
    elif operation == "week":
        return _list_events("today", "7d", calendar_name,
                            "This Week's Events")
    elif operation == "list":
        if not start_date:
            return "Error: start_date is required for 'list' operation"
        end = end_date or "1d"
        return _list_events(start_date, end, calendar_name,
                            f"Events from {start_date}")
    elif operation == "calendars":
        return _list_calendars()
    else:
        return (f"Unknown operation: {operation}. "
                "Use one of: today, tomorrow, week, list, calendars")
