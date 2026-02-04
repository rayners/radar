"""Tool for suggesting personality updates."""

from radar.config import get_config
from radar.feedback import store_suggestion
from radar.tools import tool


@tool(
    name="suggest_personality_update",
    description="Suggest an update to a personality file. Changes go to pending review by default. Use this to propose improvements based on user feedback or observed patterns.",
    parameters={
        "personality_name": {
            "type": "string",
            "description": "Name of the personality to modify (e.g., 'default', 'creative')",
        },
        "suggestion_type": {
            "type": "string",
            "description": "Type of change: 'add' (append new content), 'remove' (delete content), or 'modify' (replace entire file)",
        },
        "content": {
            "type": "string",
            "description": "The content to add, remove, or the complete new content for modify",
        },
        "reason": {
            "type": "string",
            "description": "Reason for suggesting this change",
            "optional": True,
        },
    },
)
def suggest_personality_update(
    personality_name: str,
    suggestion_type: str,
    content: str,
    reason: str | None = None,
) -> str:
    """Suggest a personality update."""
    config = get_config()

    # Check if suggestions are allowed
    if not config.personality_evolution.allow_suggestions:
        return "Personality suggestions are disabled in configuration"

    # Validate suggestion type
    if suggestion_type not in ("add", "remove", "modify"):
        return f"Invalid suggestion_type '{suggestion_type}'. Must be 'add', 'remove', or 'modify'"

    try:
        suggestion_id = store_suggestion(
            personality_name=personality_name,
            suggestion_type=suggestion_type,
            content=content,
            reason=reason,
            source="llm_tool",
        )

        # Check if auto-approve is enabled
        if config.personality_evolution.auto_approve_suggestions:
            from radar.feedback import approve_suggestion
            success, message = approve_suggestion(suggestion_id)
            if success:
                return f"Suggestion #{suggestion_id} auto-approved and applied: {message}"
            else:
                return f"Suggestion #{suggestion_id} created but auto-approve failed: {message}"

        return (
            f"Suggestion #{suggestion_id} created and pending review. "
            f"Type: {suggestion_type}, Personality: {personality_name}"
        )

    except ValueError as e:
        return f"Error creating suggestion: {e}"
    except Exception as e:
        return f"Error storing suggestion: {e}"
