"""Chat API routes."""

import json
from html import escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.post("/api/ask")
async def api_ask(request: Request):
    """Quick ask endpoint."""
    from radar.agent import ask

    form = await request.form()
    message = form.get("message", "")

    if not message:
        return HTMLResponse('<div class="text-muted">No message provided</div>')

    personality = form.get("personality") or None
    response = ask(message, personality=personality)

    return HTMLResponse(
        f"""
        <div class="message message--user">
            <div class="message__role">you</div>
            <div class="message__content">{escape(message)}</div>
        </div>
        <div class="message message--assistant mt-md">
            <div class="message__role">radar</div>
            <div class="message__content">{escape(response)}</div>
        </div>
        """
    )


@router.post("/api/chat")
async def api_chat(request: Request):
    """Chat message endpoint."""
    from radar.agent import run
    from radar.memory import get_messages

    form = await request.form()
    message = form.get("message", "")
    conversation_id = form.get("conversation_id") or None

    if not message:
        return HTMLResponse("")

    personality = form.get("personality") or None
    response, new_conversation_id = run(message, conversation_id, personality=personality)

    # Get message index for feedback (count messages in conversation)
    messages = get_messages(new_conversation_id)
    message_index = len(messages) - 1  # Last message (the response)

    # Encode response for data attribute (JSON encode then escape for HTML attribute)
    raw_response_attr = escape(json.dumps(response))

    # Include conversation_id in response for HTMX to track
    # Add feedback buttons to assistant message
    # data-raw contains JSON-encoded markdown for client-side rendering
    positive_vals = escape(json.dumps({"conversation_id": new_conversation_id, "message_index": message_index, "sentiment": "positive"}))
    negative_vals = escape(json.dumps({"conversation_id": new_conversation_id, "message_index": message_index, "sentiment": "negative"}))
    return HTMLResponse(
        f"""
        <div class="message message--user">
            <div class="message__role">you</div>
            <div class="message__content">{escape(message)}</div>
        </div>
        <div class="message message--assistant" data-conversation-id="{escape(new_conversation_id)}" data-message-index="{message_index}">
            <div class="message__role">radar</div>
            <div class="message__content" data-raw="{raw_response_attr}"></div>
            <div class="message__feedback">
                <button class="feedback-btn feedback-btn--positive"
                        hx-post="/api/feedback"
                        hx-vals='{positive_vals}'
                        hx-swap="outerHTML"
                        title="This was helpful">
                    <span class="feedback-icon">+</span>
                </button>
                <button class="feedback-btn feedback-btn--negative"
                        hx-post="/api/feedback"
                        hx-vals='{negative_vals}'
                        hx-swap="outerHTML"
                        title="This could be better">
                    <span class="feedback-icon">-</span>
                </button>
            </div>
        </div>
        """
    )


@router.post("/api/feedback")
async def api_feedback(request: Request):
    """Store user feedback on a response."""
    from radar.feedback import store_feedback

    form = await request.form()
    conversation_id = form.get("conversation_id", "")
    message_index = int(form.get("message_index", 0))
    sentiment = form.get("sentiment", "")
    response_content = form.get("response_content", "")
    user_comment = form.get("user_comment", "")

    if not conversation_id or sentiment not in ("positive", "negative"):
        return HTMLResponse(
            '<span class="text-error">Invalid feedback</span>',
            status_code=400
        )

    try:
        store_feedback(
            conversation_id=conversation_id,
            message_index=message_index,
            sentiment=sentiment,
            response_content=response_content or None,
            user_comment=user_comment or None,
        )

        # Return a confirmation that replaces the feedback buttons
        icon = "+" if sentiment == "positive" else "-"
        color = "phosphor" if sentiment == "positive" else "muted"
        return HTMLResponse(
            f'<span class="feedback-recorded text-{color}" title="Feedback recorded">'
            f'<span class="feedback-icon">{icon}</span> Recorded</span>'
        )

    except Exception as e:
        return HTMLResponse(
            f'<span class="text-error">Error: {escape(str(e))}</span>',
            status_code=500
        )
