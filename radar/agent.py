"""Agent orchestration - context building and LLM interaction."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from radar.config import get_config, get_data_paths
from radar.llm import chat
from radar.memory import (
    add_message,
    create_conversation,
    get_messages,
    messages_to_api_format,
)


@dataclass
class PersonalityConfig:
    """Parsed personality with optional front matter metadata."""

    content: str  # Markdown body (front matter stripped)
    model: str | None = None
    fallback_model: str | None = None
    tools_include: list[str] | None = None
    tools_exclude: list[str] | None = None


def parse_personality(raw: str) -> PersonalityConfig:
    """Parse a personality file, extracting optional YAML front matter.

    Args:
        raw: Raw personality file content.

    Returns:
        PersonalityConfig with parsed metadata and body content.

    Raises:
        ValueError: If both tools.include and tools.exclude are present.
    """
    # Check for front matter (must start with ---)
    if not raw.startswith("---"):
        return PersonalityConfig(content=raw)

    # Find the closing ---
    end = raw.find("---", 3)
    if end == -1:
        # No closing --- — treat entire content as body (malformed)
        return PersonalityConfig(content=raw)

    front_matter_str = raw[3:end].strip()
    body = raw[end + 3:].lstrip("\n")

    if not front_matter_str:
        # Empty front matter block
        return PersonalityConfig(content=body)

    try:
        fm = yaml.safe_load(front_matter_str)
    except yaml.YAMLError:
        # Malformed YAML — treat entire content as body
        return PersonalityConfig(content=raw)

    if not isinstance(fm, dict):
        return PersonalityConfig(content=body)

    # Extract fields
    model = fm.get("model")
    fallback_model = fm.get("fallback_model")

    tools = fm.get("tools") or {}
    tools_include = tools.get("include") if isinstance(tools, dict) else None
    tools_exclude = tools.get("exclude") if isinstance(tools, dict) else None

    if tools_include and tools_exclude:
        raise ValueError(
            "Personality front matter cannot specify both tools.include and tools.exclude"
        )

    return PersonalityConfig(
        content=body,
        model=model if isinstance(model, str) else None,
        fallback_model=fallback_model if isinstance(fallback_model, str) else None,
        tools_include=tools_include,
        tools_exclude=tools_exclude,
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
    return get_data_paths().personalities


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


def _load_personality_config(name_or_path: str) -> PersonalityConfig:
    """Load and parse a personality file into a PersonalityConfig.

    Args:
        name_or_path: Personality name or explicit file path.

    Returns:
        PersonalityConfig with parsed metadata and body content.
    """
    raw = load_personality(name_or_path)
    return parse_personality(raw)


def _build_system_prompt(
    personality_override: str | None = None,
) -> tuple[str, PersonalityConfig]:
    """Build the system prompt with current time and personality notes.

    Args:
        personality_override: Optional personality name/path to use instead of config.

    Returns:
        Tuple of (system prompt string, PersonalityConfig).
    """
    config = get_config()

    # Use override if provided, otherwise use config
    personality_name = personality_override or config.personality

    # Load and parse personality file (falls back to DEFAULT_PERSONALITY if not found)
    pc = _load_personality_config(personality_name)

    # Format with current time — use the parsed content (front matter stripped)
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prompt = pc.content.replace("{current_time}", current_time)

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

    return prompt, pc


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
    prompt, pc = _build_system_prompt(personality)
    system_message = {"role": "system", "content": prompt}

    # Load conversation history
    stored_messages = get_messages(conversation_id)
    api_messages = [system_message] + messages_to_api_format(stored_messages)

    # Call LLM with tool support
    final_message, all_messages = chat(
        api_messages,
        model_override=pc.model,
        fallback_model_override=pc.fallback_model,
        tools_include=pc.tools_include,
        tools_exclude=pc.tools_exclude,
    )

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
    prompt, pc = _build_system_prompt(personality)
    system_message = {"role": "system", "content": prompt}
    user_msg = {"role": "user", "content": user_message}

    final_message, _ = chat(
        [system_message, user_msg],
        model_override=pc.model,
        fallback_model_override=pc.fallback_model,
        tools_include=pc.tools_include,
        tools_exclude=pc.tools_exclude,
    )
    return final_message.get("content", "")
