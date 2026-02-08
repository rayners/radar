"""Conversation summary file I/O, conversation scanning, and formatting.

Summaries are stored as markdown files with YAML front matter:
    $RADAR_DATA_DIR/summaries/{period_type}/{label}.md

Supported period types: daily, weekly, monthly.
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from radar.config import get_config, get_data_paths


def get_summaries_dir() -> Path:
    """Get the summaries base directory, creating subdirs if needed."""
    base = get_data_paths().base / "summaries"
    for subdir in ("daily", "weekly", "monthly"):
        (base / subdir).mkdir(parents=True, exist_ok=True)
    return base


def _label_for_period(period_type: str, date_or_label: str) -> str:
    """Normalize a date/label string for the given period type.

    For daily: expects ISO date "2025-01-07" → "2025-01-07"
    For weekly: expects ISO week "2025-W02" → "2025-W02"
    For monthly: expects "2025-01" → "2025-01"
    """
    return date_or_label


def get_summary_path(period_type: str, date_or_label: str) -> Path:
    """Get the expected file path for a summary."""
    label = _label_for_period(period_type, date_or_label)
    return get_summaries_dir() / period_type / f"{label}.md"


def summary_exists(period_type: str, date_or_label: str) -> bool:
    """Check if a summary file exists."""
    return get_summary_path(period_type, date_or_label).exists()


def write_summary(
    period_type: str,
    date_or_label: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Write a markdown summary file with YAML front matter.

    Args:
        period_type: "daily", "weekly", or "monthly"
        date_or_label: Date label (e.g., "2025-01-07", "2025-W02", "2025-01")
        content: Markdown body of the summary
        metadata: Additional front matter fields (merged with defaults)

    Returns:
        Path to the written file
    """
    path = get_summary_path(period_type, date_or_label)

    front_matter = {
        "period": period_type,
        "date": date_or_label,
    }
    if metadata:
        front_matter.update(metadata)

    # Build file content
    fm_str = yaml.dump(front_matter, default_flow_style=False, sort_keys=False).strip()
    file_content = f"---\n{fm_str}\n---\n\n{content}\n"

    path.write_text(file_content)
    return path


def read_summary(period_type: str, date_or_label: str) -> dict[str, Any] | None:
    """Read and parse a summary file.

    Returns:
        Dict with 'metadata' (front matter) and 'content' (body), or None if not found.
    """
    path = get_summary_path(period_type, date_or_label)
    if not path.exists():
        return None

    return parse_summary_file(path)


def parse_summary_file(path: Path) -> dict[str, Any]:
    """Parse a summary markdown file with YAML front matter.

    Returns:
        Dict with 'metadata' (front matter dict), 'content' (body str), and 'path'.
    """
    text = path.read_text()

    metadata = {}
    content = text

    # Parse YAML front matter
    match = re.match(r"^---\n(.*?)\n---\n\n?(.*)", text, re.DOTALL)
    if match:
        try:
            metadata = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            metadata = {}
        content = match.group(2).strip()

    return {
        "metadata": metadata,
        "content": content,
        "path": str(path),
    }


def list_summaries(
    period_type: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List summary files sorted by date (most recent first).

    Args:
        period_type: Filter to a specific period type, or None for all.
        limit: Maximum number of results.

    Returns:
        List of dicts with metadata, content preview, and path.
    """
    summaries_dir = get_summaries_dir()
    types = [period_type] if period_type else ["daily", "weekly", "monthly"]

    results = []
    for pt in types:
        type_dir = summaries_dir / pt
        if not type_dir.exists():
            continue
        for md_file in type_dir.glob("*.md"):
            parsed = parse_summary_file(md_file)
            parsed["period_type"] = pt
            parsed["filename"] = md_file.stem
            results.append(parsed)

    # Sort by filename descending (works for ISO dates)
    results.sort(key=lambda x: x["filename"], reverse=True)
    return results[:limit]


def get_latest_summary(period_type: str) -> dict[str, Any] | None:
    """Get the most recent summary of a given type."""
    summaries = list_summaries(period_type=period_type, limit=1)
    return summaries[0] if summaries else None


def get_conversations_in_range(
    start_date: datetime,
    end_date: datetime,
) -> list[dict[str, Any]]:
    """Scan JSONL files for conversations in a date range.

    Args:
        start_date: Start of range (inclusive)
        end_date: End of range (inclusive, up to end of day)

    Returns:
        List of dicts with 'id', 'messages', 'created_at', 'type'.
    """
    from radar.memory import _get_heartbeat_conversation_id

    conv_dir = get_data_paths().conversations
    if not conv_dir.exists():
        return []

    heartbeat_id = _get_heartbeat_conversation_id()
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    conversations = []

    for conv_path in sorted(conv_dir.glob("*.jsonl")):
        conversation_id = conv_path.stem

        # Skip heartbeat conversations
        if conversation_id == heartbeat_id:
            continue

        messages = []
        created_at = None

        with open(conv_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                timestamp = msg.get("timestamp", "")
                if not timestamp:
                    continue

                # Extract date portion
                msg_date = timestamp[:10]

                if created_at is None:
                    created_at = timestamp

                # Check if message falls within range
                if start_str <= msg_date <= end_str:
                    messages.append(msg)

        if not messages:
            continue

        # Check that the conversation was created within range
        if created_at and start_str <= created_at[:10] <= end_str:
            conversations.append({
                "id": conversation_id,
                "messages": messages,
                "created_at": created_at,
                "type": "chat",
            })

    # Sort by created_at
    conversations.sort(key=lambda c: c.get("created_at", ""))
    return conversations


def format_conversations_for_llm(
    conversations: list[dict[str, Any]],
    max_tokens_approx: int = 4000,
) -> str:
    """Format conversations into a prompt-friendly string.

    Keeps user messages and final assistant responses, dropping tool call
    internals to stay within token budget.

    Args:
        conversations: List of conversation dicts from get_conversations_in_range()
        max_tokens_approx: Approximate token limit (chars / 4)

    Returns:
        Formatted string for LLM consumption.
    """
    max_chars = max_tokens_approx * 4  # Rough chars-to-tokens ratio
    lines = []
    total_chars = 0

    for conv in conversations:
        conv_header = f"\n## Conversation ({conv.get('created_at', 'unknown')[:16]})\n"
        if total_chars + len(conv_header) > max_chars:
            break
        lines.append(conv_header)
        total_chars += len(conv_header)

        for msg in conv.get("messages", []):
            role = msg.get("role", "")
            content = msg.get("content")

            # Skip tool role messages and messages with only tool calls (no content)
            if role == "tool":
                continue
            if role == "assistant" and not content and msg.get("tool_calls"):
                continue

            if content:
                prefix = "User" if role == "user" else "Assistant"
                # Truncate very long individual messages
                truncated = content[:500] + "..." if len(content) > 500 else content
                line = f"**{prefix}**: {truncated}\n"

                if total_chars + len(line) > max_chars:
                    lines.append("\n*[Truncated due to length]*\n")
                    return "\n".join(lines)

                lines.append(line)
                total_chars += len(line)

    if not lines:
        return "No conversations found in this period."

    return "\n".join(lines)


def _parse_period_range(period: str) -> tuple[datetime, datetime, str, str]:
    """Parse a period string into start/end dates and period type/label.

    Supported formats:
        "today" → today's date range
        "yesterday" → yesterday's date range
        "this_week" → current ISO week
        "last_week" → previous ISO week
        "this_month" → current month
        "last_month" → previous month
        "2025-01-01:2025-01-07" → explicit date range

    Returns:
        (start_date, end_date, period_type, label)
    """
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if period == "today":
        return today, today, "daily", today.strftime("%Y-%m-%d")

    if period == "yesterday":
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday, "daily", yesterday.strftime("%Y-%m-%d")

    if period == "this_week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        label = f"{start.isocalendar()[0]}-W{start.isocalendar()[1]:02d}"
        return start, end, "weekly", label

    if period == "last_week":
        start = today - timedelta(days=today.weekday() + 7)
        end = start + timedelta(days=6)
        label = f"{start.isocalendar()[0]}-W{start.isocalendar()[1]:02d}"
        return start, end, "weekly", label

    if period == "this_month":
        start = today.replace(day=1)
        # End of month
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end = start.replace(month=start.month + 1, day=1) - timedelta(days=1)
        label = start.strftime("%Y-%m")
        return start, end, "monthly", label

    if period == "last_month":
        first_of_this_month = today.replace(day=1)
        end = first_of_this_month - timedelta(days=1)
        start = end.replace(day=1)
        label = start.strftime("%Y-%m")
        return start, end, "monthly", label

    # Explicit range: "2025-01-01:2025-01-07"
    if ":" in period:
        parts = period.split(":")
        if len(parts) == 2:
            start = datetime.strptime(parts[0].strip(), "%Y-%m-%d")
            end = datetime.strptime(parts[1].strip(), "%Y-%m-%d")
            # Determine period type from range length
            delta = (end - start).days
            if delta <= 1:
                ptype = "daily"
                label = start.strftime("%Y-%m-%d")
            elif delta <= 7:
                ptype = "weekly"
                label = f"{start.isocalendar()[0]}-W{start.isocalendar()[1]:02d}"
            else:
                ptype = "monthly"
                label = start.strftime("%Y-%m")
            return start, end, ptype, label

    raise ValueError(f"Unknown period format: {period}")


def check_summary_due(period_type: str) -> str | None:
    """Check if a summary should be generated and return formatted conversation data.

    Returns:
        Formatted conversation string if summary is due, None otherwise.
    """
    config = get_config()
    summaries_config = getattr(config, "summaries", None)
    if summaries_config and not summaries_config.enabled:
        return None

    now = datetime.now()

    if period_type == "daily":
        # Check if configured time has passed
        summary_time_str = "21:00"
        if summaries_config:
            summary_time_str = summaries_config.daily_summary_time
        hour, minute = map(int, summary_time_str.split(":"))

        if now.hour < hour or (now.hour == hour and now.minute < minute):
            return None

        label = now.strftime("%Y-%m-%d")
        if summary_exists("daily", label):
            return None

        # Get today's conversations
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        conversations = get_conversations_in_range(today, today)
        if not conversations:
            return None

        return format_conversations_for_llm(conversations)

    if period_type == "weekly":
        day_of_week = "sun"
        if summaries_config:
            day_of_week = summaries_config.weekly_summary_day

        day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
        target_day = day_map.get(day_of_week.lower()[:3], 6)
        if now.weekday() != target_day:
            return None

        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=6)
        label = f"{start.isocalendar()[0]}-W{start.isocalendar()[1]:02d}"

        if summary_exists("weekly", label):
            return None

        conversations = get_conversations_in_range(start, end)
        if not conversations:
            return None

        return format_conversations_for_llm(conversations)

    if period_type == "monthly":
        summary_day = 1
        if summaries_config:
            summary_day = summaries_config.monthly_summary_day

        if now.day != summary_day:
            return None

        # Summarize last month
        first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = first_of_this_month - timedelta(days=1)
        start = end.replace(day=1)
        label = start.strftime("%Y-%m")

        if summary_exists("monthly", label):
            return None

        conversations = get_conversations_in_range(start, end)
        if not conversations:
            return None

        return format_conversations_for_llm(conversations)

    return None
