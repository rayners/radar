"""Tools for managing URL monitors via chat."""

from radar.tools import tool


@tool(
    name="monitor_url",
    description="Create a URL monitor that periodically checks a web page for changes. "
    "Changes are detected at each heartbeat and reported automatically.",
    parameters={
        "name": {"type": "string", "description": "Short name for this monitor (e.g., 'Python changelog')"},
        "url": {"type": "string", "description": "URL to monitor"},
        "interval_minutes": {
            "type": "integer",
            "description": "Minutes between checks (default: 60, minimum: 5)",
            "optional": True,
        },
        "css_selector": {
            "type": "string",
            "description": "CSS selector to monitor only part of the page (requires beautifulsoup4)",
            "optional": True,
        },
        "min_change_threshold": {
            "type": "integer",
            "description": "Minimum number of changed lines to report (default: 0)",
            "optional": True,
        },
    },
)
def monitor_url(
    name: str,
    url: str,
    interval_minutes: int | None = None,
    css_selector: str | None = None,
    min_change_threshold: int = 0,
) -> str:
    from radar.url_monitors import create_monitor, get_monitor

    try:
        monitor_id = create_monitor(
            name=name,
            url=url,
            check_interval_minutes=interval_minutes,
            css_selector=css_selector,
            min_change_threshold=min_change_threshold,
        )
    except ValueError as e:
        return f"Error: {e}"

    monitor = get_monitor(monitor_id)
    interval = monitor["check_interval_minutes"] if monitor else interval_minutes
    return (
        f"URL monitor '{name}' (ID {monitor_id}) created.\n"
        f"URL: {url}\n"
        f"Check interval: every {interval} minutes\n"
        f"CSS selector: {css_selector or '(full page)'}\n"
        f"Will check on next heartbeat."
    )


@tool(
    name="list_url_monitors",
    description="List all URL monitors with their status, last check time, and error count.",
    parameters={
        "show_disabled": {
            "type": "boolean",
            "description": "Include paused/disabled monitors (default: false)",
            "optional": True,
        },
    },
)
def list_url_monitors(show_disabled: bool = False) -> str:
    from radar.url_monitors import list_monitors

    monitors = list_monitors(enabled_only=not show_disabled)

    if not monitors:
        return "No URL monitors found."

    lines = []
    for m in monitors:
        status = "enabled" if m["enabled"] else "paused"
        last = m["last_check"] or "never"
        next_c = m["next_check"] or "-"
        errors = m["error_count"]
        selector = f" (selector: {m['css_selector']})" if m.get("css_selector") else ""
        error_info = f" | Errors: {errors}" if errors else ""
        last_err = f"\n    Last error: {m['last_error']}" if m.get("last_error") else ""
        lines.append(
            f"[{m['id']}] {m['name']} ({status}){selector}\n"
            f"    URL: {m['url']}\n"
            f"    Interval: every {m['check_interval_minutes']} min\n"
            f"    Last check: {last} | Next check: {next_c}{error_info}{last_err}"
        )

    return "\n\n".join(lines)


@tool(
    name="check_url",
    description="Manually check a monitored URL for changes right now, or do a one-off check of any URL.",
    parameters={
        "monitor_id": {
            "type": "integer",
            "description": "ID of an existing monitor to check",
            "optional": True,
        },
        "url": {
            "type": "string",
            "description": "URL for a one-off check (no monitor needed)",
            "optional": True,
        },
    },
)
def check_url(monitor_id: int | None = None, url: str | None = None) -> str:
    if monitor_id is not None:
        from radar.url_monitors import get_monitor, check_monitor

        monitor = get_monitor(monitor_id)
        if not monitor:
            return f"Error: monitor {monitor_id} not found"

        try:
            change = check_monitor(monitor)
        except Exception as e:
            return f"Error checking '{monitor['name']}': {e}"

        if change is None:
            return f"No changes detected for '{monitor['name']}' ({monitor['url']})"

        return (
            f"Changes detected for '{change['name']}' ({change['url']}):\n"
            f"Changed lines: {change['change_size']}\n"
            f"Diff:\n{change['diff_summary']}"
        )

    elif url is not None:
        from radar.url_monitors import fetch_url_content, extract_text

        try:
            result = fetch_url_content(url)
        except Exception as e:
            return f"Error fetching URL: {e}"

        if result is None:
            return "No content returned."

        text = extract_text(result["content"])
        # Truncate for display
        if len(text) > 2000:
            text = text[:2000] + "\n... (truncated)"
        return f"Fetched content from {url}:\n\n{text}"

    return "Error: provide either monitor_id or url"


@tool(
    name="remove_monitor",
    description="Remove or pause a URL monitor. By default pauses it (can be resumed). "
    "Use delete=true to permanently remove.",
    parameters={
        "monitor_id": {"type": "integer", "description": "ID of the monitor"},
        "delete": {
            "type": "boolean",
            "description": "Permanently delete instead of pause (default: false)",
            "optional": True,
        },
        "resume": {
            "type": "boolean",
            "description": "Resume a paused monitor (default: false)",
            "optional": True,
        },
    },
)
def remove_monitor(monitor_id: int, delete: bool = False, resume: bool = False) -> str:
    from radar.url_monitors import get_monitor, delete_monitor, pause_monitor, resume_monitor

    monitor = get_monitor(monitor_id)
    if not monitor:
        return f"Error: monitor {monitor_id} not found"

    if resume:
        resume_monitor(monitor_id)
        return f"Monitor '{monitor['name']}' (ID {monitor_id}) resumed."

    if delete:
        delete_monitor(monitor_id)
        return f"Monitor '{monitor['name']}' (ID {monitor_id}) permanently deleted."

    pause_monitor(monitor_id)
    return f"Monitor '{monitor['name']}' (ID {monitor_id}) paused."
