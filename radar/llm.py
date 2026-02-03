"""Ollama API client with tool call support."""

import json
from typing import Any

import httpx

from radar.config import get_config
from radar.tools import execute_tool, get_tools_schema


def chat(
    messages: list[dict[str, Any]],
    use_tools: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Send messages to Ollama and handle tool calls.

    Args:
        messages: List of message dicts with role/content
        use_tools: Whether to include tools and handle tool calls

    Returns:
        Tuple of (final assistant message, full message history)
    """
    config = get_config()
    url = f"{config.ollama.base_url.rstrip('/')}/api/chat"

    tools = get_tools_schema() if use_tools else []
    all_messages = list(messages)
    iterations = 0

    while iterations < config.max_tool_iterations:
        iterations += 1

        payload = {
            "model": config.ollama.model,
            "messages": all_messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        try:
            response = httpx.post(url, json=payload, timeout=120)
            response.raise_for_status()
        except httpx.TimeoutException:
            raise RuntimeError("Ollama request timed out")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Ollama error: {e.response.status_code} - {e.response.text}")
        except httpx.ConnectError:
            raise RuntimeError(f"Cannot connect to Ollama at {config.ollama.base_url}")

        data = response.json()
        assistant_message = data.get("message", {})
        all_messages.append(assistant_message)

        # Check for tool calls
        tool_calls = assistant_message.get("tool_calls", [])
        if not tool_calls:
            # No tool calls, we're done
            return assistant_message, all_messages

        # Execute each tool call and add results
        for tool_call in tool_calls:
            func = tool_call.get("function", {})
            tool_name = func.get("name", "")
            tool_args = func.get("arguments", {})

            # Arguments might be a string that needs parsing
            if isinstance(tool_args, str):
                try:
                    tool_args = json.loads(tool_args)
                except json.JSONDecodeError:
                    tool_args = {}

            result = execute_tool(tool_name, tool_args)

            # Add tool result as a message
            tool_message = {
                "role": "tool",
                "content": result,
            }
            all_messages.append(tool_message)

    # Max iterations reached
    final_message = {
        "role": "assistant",
        "content": "I've reached the maximum number of tool call iterations. Please try a simpler request.",
    }
    all_messages.append(final_message)
    return final_message, all_messages
