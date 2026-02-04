"""Scheduler for heartbeat and event processing."""

from datetime import datetime, time
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from radar.config import get_config, get_data_paths

# Global state
_scheduler: BackgroundScheduler | None = None
_event_queue: list[dict[str, Any]] = []
_last_heartbeat: datetime | None = None


def _is_quiet_hours() -> bool:
    """Check if current time is within quiet hours."""
    config = get_config()
    now = datetime.now().time()

    try:
        start = datetime.strptime(config.heartbeat.quiet_hours_start, "%H:%M").time()
        end = datetime.strptime(config.heartbeat.quiet_hours_end, "%H:%M").time()
    except ValueError:
        return False

    # Handle overnight quiet hours (e.g., 23:00 - 07:00)
    if start > end:
        return now >= start or now <= end
    else:
        return start <= now <= end


def _build_heartbeat_message(events: list[dict[str, Any]]) -> str:
    """Build the heartbeat message from queued events."""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not events:
        return f"Heartbeat at {current_time}. No new events."

    lines = [f"Heartbeat at {current_time}. Events since last check:"]

    for e in events:
        data = e["data"]
        desc = data.get("description", e["type"])
        path = data.get("path", "")
        action = data.get("action")

        if action:
            lines.append(f"- {desc}")
            lines.append(f"  File: {path}")
            lines.append(f"  Action: {action}")
        else:
            lines.append(f"- {desc}: {path}")

    return "\n".join(lines)


def _log_heartbeat(message: str, **extra) -> None:
    """Log a heartbeat event."""
    try:
        from radar.logging import log
        log("info", message, **extra)
    except Exception:
        pass


def _heartbeat_tick() -> None:
    """Execute a heartbeat tick."""
    global _last_heartbeat, _event_queue

    if _is_quiet_hours():
        _log_heartbeat("Heartbeat skipped (quiet hours)")
        return

    # Collect pending events
    events = _event_queue.copy()
    _event_queue.clear()

    # Build heartbeat message
    message = _build_heartbeat_message(events)

    # Run agent with heartbeat message
    try:
        from radar.agent import run
        _log_heartbeat("Heartbeat started", event_count=len(events))
        run(message, conversation_id=_get_heartbeat_conversation_id())
        _log_heartbeat("Heartbeat completed", event_count=len(events))
    except Exception as e:
        # Log error but don't crash scheduler
        import sys
        print(f"Heartbeat error: {e}", file=sys.stderr)
        _log_heartbeat("Heartbeat failed", error=str(e))

    _last_heartbeat = datetime.now()


def _get_heartbeat_conversation_id() -> str:
    """Get or create a persistent heartbeat conversation ID."""
    heartbeat_file = get_data_paths().base / "heartbeat_conversation"
    if heartbeat_file.exists():
        return heartbeat_file.read_text().strip()
    else:
        from radar.memory import create_conversation
        conv_id = create_conversation()
        heartbeat_file.write_text(conv_id)
        return conv_id


def start_scheduler() -> None:
    """Start the background scheduler."""
    global _scheduler

    if _scheduler is not None:
        return  # Already running

    config = get_config()
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _heartbeat_tick,
        "interval",
        minutes=config.heartbeat.interval_minutes,
        id="heartbeat",
        name="Heartbeat",
    )
    _scheduler.start()


def stop_scheduler() -> None:
    """Stop the background scheduler."""
    global _scheduler

    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def trigger_heartbeat() -> str:
    """Manually trigger a heartbeat and return the result."""
    if _is_quiet_hours():
        return "Skipped: quiet hours active"

    _heartbeat_tick()
    return "Heartbeat triggered"


def get_status() -> dict[str, Any]:
    """Get scheduler status information."""
    global _scheduler, _last_heartbeat, _event_queue

    config = get_config()

    running = _scheduler is not None and _scheduler.running
    next_run = None

    if running:
        job = _scheduler.get_job("heartbeat")
        if job and job.next_run_time:
            next_run = job.next_run_time.strftime("%H:%M:%S")

    return {
        "running": running,
        "last_heartbeat": _last_heartbeat.strftime("%Y-%m-%d %H:%M:%S") if _last_heartbeat else None,
        "next_heartbeat": next_run,
        "pending_events": len(_event_queue),
        "quiet_hours": _is_quiet_hours(),
        "interval_minutes": config.heartbeat.interval_minutes,
        "quiet_hours_start": config.heartbeat.quiet_hours_start,
        "quiet_hours_end": config.heartbeat.quiet_hours_end,
    }


def add_event(event_type: str, data: dict[str, Any]) -> None:
    """Add an event to the queue for the next heartbeat.

    Args:
        event_type: Type of event (e.g., "file_created", "file_modified")
        data: Event data dictionary
    """
    global _event_queue

    _event_queue.append({
        "type": event_type,
        "data": data,
        "timestamp": datetime.now().isoformat(),
    })
