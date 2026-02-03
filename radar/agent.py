"""Agent orchestration - context building and LLM interaction."""

from datetime import datetime
from typing import Any

from radar.config import get_config
from radar.llm import chat
from radar.memory import (
    add_message,
    create_conversation,
    get_messages,
    messages_to_api_format,
)

DEFAULT_SYSTEM_PROMPT = """You are Radar, a personal AI assistant running locally on the user's machine.
You are concise, practical, and proactive. You use tools to take action rather
than just suggesting what the user could do.

When given a task, execute it using your available tools. If you need multiple
steps, work through them sequentially. Report results briefly.

If you discover something noteworthy during a task, flag it. If you're unsure
about a destructive action, ask for confirmation.

Current time: {current_time}"""


def _build_system_prompt() -> str:
    """Build the system prompt with current time and personality notes."""
    config = get_config()
    template = config.system_prompt or DEFAULT_SYSTEM_PROMPT
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prompt = template.format(current_time=current_time)

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
) -> tuple[str, str]:
    """Run the agent with a user message.

    Args:
        user_message: The user's input
        conversation_id: Optional existing conversation ID

    Returns:
        Tuple of (assistant response text, conversation_id)
    """
    # Create or use existing conversation
    if conversation_id is None:
        conversation_id = create_conversation()

    # Store user message
    add_message(conversation_id, "user", user_message)

    # Build messages for API
    system_message = {"role": "system", "content": _build_system_prompt()}

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


def ask(user_message: str) -> str:
    """One-shot question without persistent conversation.

    Args:
        user_message: The user's question

    Returns:
        Assistant response text
    """
    system_message = {"role": "system", "content": _build_system_prompt()}
    user_msg = {"role": "user", "content": user_message}

    final_message, _ = chat([system_message, user_msg])
    return final_message.get("content", "")
