"""Tool for analyzing user feedback patterns."""

from radar.config import get_config
from radar.feedback import get_unprocessed_feedback, get_feedback_summary, mark_feedback_processed
from radar.tools import tool


@tool(
    name="analyze_feedback",
    description="Analyze recent user feedback to identify patterns. Returns feedback entries for analysis. Use this to understand what users like/dislike and inform personality improvements.",
    parameters={
        "limit": {
            "type": "integer",
            "description": "Maximum number of feedback entries to analyze (default 50)",
            "optional": True,
        },
        "include_processed": {
            "type": "boolean",
            "description": "Include already-processed feedback (default False)",
            "optional": True,
        },
        "mark_as_processed": {
            "type": "boolean",
            "description": "Mark returned feedback as processed (default True)",
            "optional": True,
        },
    },
)
def analyze_feedback(
    limit: int = 50,
    include_processed: bool = False,
    mark_as_processed: bool = True,
) -> str:
    """Analyze user feedback patterns."""
    config = get_config()

    # Check minimum feedback threshold
    summary = get_feedback_summary()
    total = summary["total"]
    min_required = config.personality_evolution.min_feedback_for_analysis

    if total < min_required:
        return (
            f"Insufficient feedback for analysis. Have {total} entries, "
            f"need at least {min_required}. "
            f"Summary: {summary['positive']} positive, {summary['negative']} negative."
        )

    # Get feedback entries
    if include_processed:
        from radar.feedback import get_all_feedback
        feedback = get_all_feedback(limit=limit)
    else:
        feedback = get_unprocessed_feedback(limit=limit)

    if not feedback:
        return (
            f"No {'unprocessed ' if not include_processed else ''}feedback to analyze. "
            f"Total feedback: {total} ({summary['positive']} positive, {summary['negative']} negative)"
        )

    # Build analysis report
    lines = [
        f"# Feedback Analysis Report",
        f"",
        f"## Summary",
        f"- Total feedback: {total}",
        f"- Positive: {summary['positive']} ({100*summary['positive']/total:.1f}%)" if total > 0 else "- Positive: 0",
        f"- Negative: {summary['negative']} ({100*summary['negative']/total:.1f}%)" if total > 0 else "- Negative: 0",
        f"- Unprocessed: {summary['unprocessed']}",
        f"",
        f"## Feedback Entries ({len(feedback)} shown)",
        f"",
    ]

    positive_entries = []
    negative_entries = []

    for entry in feedback:
        sentiment = entry["sentiment"]
        content = entry.get("response_content", "")
        comment = entry.get("user_comment", "")
        created = entry.get("created_at", "")

        entry_text = f"- [{created[:16]}] "
        if content:
            # Truncate long content
            preview = content[:200] + "..." if len(content) > 200 else content
            preview = preview.replace("\n", " ")
            entry_text += f'"{preview}"'
        if comment:
            entry_text += f" (Comment: {comment})"

        if sentiment == "positive":
            positive_entries.append(entry_text)
        else:
            negative_entries.append(entry_text)

    if positive_entries:
        lines.append("### Positive Feedback")
        lines.extend(positive_entries)
        lines.append("")

    if negative_entries:
        lines.append("### Negative Feedback")
        lines.extend(negative_entries)
        lines.append("")

    # Mark as processed if requested
    if mark_as_processed and not include_processed:
        feedback_ids = [e["id"] for e in feedback]
        count = mark_feedback_processed(feedback_ids)
        lines.append(f"*Marked {count} entries as processed.*")

    lines.append("")
    lines.append(
        "## Next Steps\n"
        "Based on this analysis, consider using `suggest_personality_update` to:\n"
        "- Add instructions that align with positive feedback patterns\n"
        "- Remove or modify instructions that correlate with negative feedback\n"
        "- Adjust tone, verbosity, or other style elements"
    )

    return "\n".join(lines)
