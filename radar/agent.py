"""Agent orchestration - context building and LLM interaction."""

from datetime import datetime
from pathlib import Path
from typing import Any

from radar.config import get_config
from radar.llm import chat
from radar.memory import (
    add_message,
    create_conversation,
    get_messages,
    messages_to_api_format,
)

DEFAULT_PERSONALITY = """# Default

A practical, local-first AI assistant.

## Instructions

You are Radar, a personal AI assistant running locally on the user's machine.

Be concise, practical, and proactive. You have access to tools - use them directly rather than suggesting actions.

When given a task, execute it using your available tools. If you need multiple steps, work through them sequentially. Report results briefly.

If you discover something noteworthy during a task, flag it. If you're unsure about a destructive action, ask for confirmation.

Current time: {current_time}
"""


def get_personalities_dir() -> Path:
    """Get the personalities directory, creating if needed."""
    dir_path = Path.home() / ".local" / "share" / "radar" / "personalities"
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def _ensure_default_personality() -> None:
    """Create default personality file if it doesn't exist."""
    default = get_personalities_dir() / "default.md"
    if not default.exists():
        default.write_text(DEFAULT_PERSONALITY)


def load_personality(name_or_path: str) -> str:
    """Load personality content from file.

    Args:
        name_or_path: Either a personality name (looked up in personalities dir)
                      or an explicit path to a personality file.

    Returns:
        The personality content as a string.
    """
    # Ensure default exists
    _ensure_default_personality()

    # Check if it's an explicit path
    path = Path(name_or_path).expanduser()
    if path.exists() and path.is_file():
        return path.read_text()

    # Otherwise look in personalities directory
    personality_file = get_personalities_dir() / f"{name_or_path}.md"
    if personality_file.exists():
        return personality_file.read_text()

    # Fall back to default
    return DEFAULT_PERSONALITY


def _build_system_prompt(personality_override: str | None = None) -> str:
    """Build the system prompt with current time and personality notes.

    Args:
        personality_override: Optional personality name/path to use instead of config.
    """
    config = get_config()

    # Use override if provided, otherwise use config
    personality_name = personality_override or config.personality

    # Load personality file (falls back to DEFAULT_PERSONALITY if not found)
    template = load_personality(personality_name)

    # Format with current time
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prompt = template.replace("{current_time}", current_time)

    # Inject personality notes from semantic memory
    try:
        from radar.semantic import search_memories
        notes = search_memories("personality preferences style user likes", limit=5)
        if notes:
            prompt += "\n\nThings to remember about the user:\n"
            for note in notes:
                prompt += f"- {note['content']}\n"
    except Exception:
        pass  # Memory not available or empty

    return prompt


def run(
    user_message: str,
    conversation_id: str | None = None,
    personality: str | None = None,
) -> tuple[str, str]:
    """Run the agent with a user message.

    Args:
        user_message: The user's input
        conversation_id: Optional existing conversation ID
        personality: Optional personality name/path override

    Returns:
        Tuple of (assistant response text, conversation_id)
    """
    # Create or use existing conversation
    if conversation_id is None:
        conversation_id = create_conversation()

    # Store user message
    add_message(conversation_id, "user", user_message)

    # Build messages for API
    system_message = {"role": "system", "content": _build_system_prompt(personality)}

    # Load conversation history
    stored_messages = get_messages(conversation_id)
    api_messages = [system_message] + messages_to_api_format(stored_messages)

    # Call LLM with tool support
    final_message, all_messages = chat(api_messages)

    # Store all new messages from the interaction
    # Skip system message and messages we already have stored
    new_messages = all_messages[len(api_messages) :]
    for msg in new_messages:
        add_message(
            conversation_id,
            msg.get("role", "assistant"),
            msg.get("content"),
            msg.get("tool_calls"),
        )

    response_text = final_message.get("content", "")
    return response_text, conversation_id


def ask(user_message: str, personality: str | None = None) -> str:
    """One-shot question without persistent conversation.

    Args:
        user_message: The user's question
        personality: Optional personality name/path override

    Returns:
        Assistant response text
    """
    system_message = {"role": "system", "content": _build_system_prompt(personality)}
    user_msg = {"role": "user", "content": user_message}

    final_message, _ = chat([system_message, user_msg])
    return final_message.get("content", "")
