"""Conversation export API endpoint."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

router = APIRouter()


@router.get("/api/export/{conversation_id}")
async def export_conversation(conversation_id: str, format: str = "json"):
    """Export a conversation as JSON or Markdown."""
    from radar.export import export_json, export_markdown

    if format not in ("json", "markdown"):
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid format: {format}. Use 'json' or 'markdown'."},
        )

    try:
        if format == "json":
            content = export_json(conversation_id)
            media_type = "application/json"
            ext = "json"
        else:
            content = export_markdown(conversation_id)
            media_type = "text/markdown"
            ext = "md"
    except ValueError:
        return JSONResponse(
            status_code=404,
            content={"error": f"Conversation not found: {conversation_id}"},
        )

    filename = f"conversation-{conversation_id[:8]}.{ext}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
