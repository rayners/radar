"""Tool for summarizing conversations on demand."""

from radar.tools import tool


@tool(
    name="summarize_conversations",
    description=(
        "Retrieve and format conversation data for a given period. "
        "Returns formatted conversation text that you should then summarize. "
        'Supported periods: "today", "yesterday", "this_week", "last_week", '
        '"this_month", "last_month", or an explicit range like "2025-01-01:2025-01-07".'
    ),
    parameters={
        "period": {
            "type": "string",
            "description": (
                'Time period to summarize. Examples: "today", "yesterday", '
                '"this_week", "last_week", "this_month", "last_month", '
                'or "2025-01-01:2025-01-07"'
            ),
        },
    },
)
def summarize_conversations(period: str) -> str:
    """Retrieve conversations for a period and return formatted text."""
    try:
        from radar.summaries import (
            _parse_period_range,
            format_conversations_for_llm,
            get_conversations_in_range,
        )

        start_date, end_date, period_type, label = _parse_period_range(period)

        conversations = get_conversations_in_range(start_date, end_date)

        if not conversations:
            return f"No conversations found for period '{period}' ({label})."

        formatted = format_conversations_for_llm(conversations)

        header = (
            f"Found {len(conversations)} conversation(s) for {period} "
            f"({start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}).\n"
            f"Period type: {period_type}, Label: {label}\n\n"
        )

        return header + formatted

    except ValueError as e:
        return f"Error parsing period '{period}': {e}"
    except Exception as e:
        return f"Error retrieving conversations: {e}"
