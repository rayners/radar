"""Summary web routes."""

from html import escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from radar.web import get_common_context, templates

router = APIRouter()


@router.get("/summaries", response_class=HTMLResponse)
async def summaries_page(request: Request):
    """Summaries page."""
    from radar.summaries import list_summaries

    context = get_common_context(request, "summaries")

    all_summaries = list_summaries(limit=50)

    # Group by period type
    grouped = {"daily": [], "weekly": [], "monthly": []}
    for s in all_summaries:
        pt = s.get("period_type", "daily")
        if pt in grouped:
            grouped[pt].append(s)

    context["grouped_summaries"] = grouped
    context["total_count"] = len(all_summaries)

    return templates.TemplateResponse("summaries.html", context)


@router.get("/api/summaries", response_class=HTMLResponse)
async def api_summaries(period_type: str = "", limit: int = 20):
    """Return HTML fragment of summaries for HTMX."""
    from radar.summaries import list_summaries

    pt = period_type if period_type else None
    summaries = list_summaries(period_type=pt, limit=limit)

    if not summaries:
        return HTMLResponse(
            '<div class="card">'
            '<div class="card__body text-muted" style="text-align: center; padding: var(--space-xl);">'
            "<p>No summaries found.</p>"
            "</div>"
            "</div>"
        )

    html_parts = []
    for s in summaries:
        metadata = s.get("metadata", {})
        content = s.get("content", "")
        period = escape(metadata.get("period", s.get("period_type", "")))
        date_label = escape(metadata.get("date", s.get("filename", "")))
        topics = metadata.get("topics", [])
        convs = metadata.get("conversations", 0)

        # Truncate content for preview
        preview = escape(content[:200] + "..." if len(content) > 200 else content)

        topic_badges = ""
        if topics:
            badges = " ".join(
                f'<span class="activity-log__type activity-log__type--chat">{escape(t)}</span>'
                for t in topics[:5]
            )
            topic_badges = f'<div class="mt-sm">{badges}</div>'

        html_parts.append(
            f'<div class="card mb-md">'
            f'<div class="card__header">'
            f'<span class="card__title">{period.title()} — {date_label}</span>'
            f'<span class="text-muted" style="font-size: 0.8rem;">{convs} conversations</span>'
            f"</div>"
            f'<div class="card__body">'
            f'<div style="white-space: pre-wrap; font-size: 0.85rem;">{preview}</div>'
            f"{topic_badges}"
            f"</div>"
            f"</div>"
        )

    return HTMLResponse("\n".join(html_parts))


@router.post("/api/summaries/generate", response_class=HTMLResponse)
async def api_summaries_generate(request: Request):
    """Trigger summary generation for a period."""
    form = await request.form()
    period = form.get("period", "today")

    try:
        from radar.summaries import (
            _parse_period_range,
            format_conversations_for_llm,
            get_conversations_in_range,
        )

        start_date, end_date, period_type, label = _parse_period_range(period)
        conversations = get_conversations_in_range(start_date, end_date)

        if not conversations:
            return HTMLResponse(
                '<div class="text-muted" style="padding: var(--space-md);">'
                f"No conversations found for {escape(period)}."
                "</div>"
            )

        formatted = format_conversations_for_llm(conversations)

        # Use the agent to generate the summary
        try:
            from radar.agent import ask

            prompt = (
                f"Generate a {period_type} conversation summary for {label}. "
                f"Summarize the key topics, decisions, and outcomes from these conversations. "
                f"Then call store_conversation_summary to save it.\n\n{formatted}"
            )
            result = ask(prompt)

            return HTMLResponse(
                '<div class="card">'
                '<div class="card__body">'
                f'<div class="text-phosphor">Summary generated for {escape(label)}</div>'
                f'<div class="mt-sm" style="white-space: pre-wrap; font-size: 0.85rem;">'
                f"{escape(result[:500])}</div>"
                "</div>"
                "</div>"
            )
        except Exception as e:
            return HTMLResponse(
                f'<div class="text-error">Error generating summary: {escape(str(e))}</div>',
                status_code=500,
            )

    except ValueError as e:
        return HTMLResponse(
            f'<div class="text-error">Invalid period: {escape(str(e))}</div>',
            status_code=400,
        )
