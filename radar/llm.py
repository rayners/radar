"""LLM client with tool call support for Ollama and OpenAI-compatible APIs."""

import json
from typing import Any

import httpx

from radar.config import get_config
from radar.tools import execute_tool, get_tools_schema


def chat(
    messages: list[dict[str, Any]],
    use_tools: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Send messages to LLM and handle tool calls.

    Args:
        messages: List of message dicts with role/content
        use_tools: Whether to include tools and handle tool calls

    Returns:
        Tuple of (final assistant message, full message history)
    """
    config = get_config()

    if config.llm.provider == "openai":
        return _chat_openai(messages, use_tools, config)
    else:
        return _chat_ollama(messages, use_tools, config)


def _chat_ollama(messages, use_tools, config):
    """Chat using Ollama's native API."""
    url = f"{config.llm.base_url.rstrip('/')}/api/chat"

    tools = get_tools_schema() if use_tools else []
    all_messages = list(messages)
    iterations = 0

    while iterations < config.max_tool_iterations:
        iterations += 1

        payload = {
            "model": config.llm.model,
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
            raise RuntimeError(f"Cannot connect to Ollama at {config.llm.base_url}")

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


def _chat_openai(messages, use_tools, config):
    """Chat using OpenAI-compatible API."""
    from openai import OpenAI

    client = OpenAI(
        base_url=config.llm.base_url,
        api_key=config.llm.api_key or "not-needed",  # Some proxies don't require key
    )

    tools = get_tools_schema() if use_tools else None
    all_messages = _convert_messages_to_openai(messages)
    iterations = 0

    # Convert tools to OpenAI format
    openai_tools = _convert_tools_to_openai(tools) if tools else None

    while iterations < config.max_tool_iterations:
        iterations += 1

        kwargs = {
            "model": config.llm.model,
            "messages": all_messages,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools

        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as e:
            raise RuntimeError(f"OpenAI API error: {e}")

        assistant_message = response.choices[0].message
        all_messages.append(_openai_message_to_dict(assistant_message))

        tool_calls = assistant_message.tool_calls
        if not tool_calls:
            # No tool calls, convert back to Ollama format and return
            final_ollama = _convert_openai_to_ollama_format(assistant_message)
            return final_ollama, _convert_messages_from_openai(all_messages)

        # Execute tools and add results
        for tool_call in tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            result = execute_tool(tool_name, tool_args)

            tool_message = {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            }
            all_messages.append(tool_message)

    # Max iterations reached
    final_message = {
        "role": "assistant",
        "content": "I've reached the maximum number of tool call iterations. Please try a simpler request.",
    }
    all_messages.append(final_message)
    return final_message, _convert_messages_from_openai(all_messages)


def _convert_tools_to_openai(ollama_tools: list[dict]) -> list[dict]:
    """Convert Ollama tool format to OpenAI format."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["function"]["name"],
                "description": tool["function"]["description"],
                "parameters": tool["function"]["parameters"],
            }
        }
        for tool in ollama_tools
    ]


def _convert_messages_to_openai(messages: list[dict]) -> list[dict]:
    """Convert Ollama message format to OpenAI format."""
    result = []
    for msg in messages:
        converted = {"role": msg["role"], "content": msg.get("content", "")}

        # Handle tool calls in assistant messages
        if msg.get("tool_calls"):
            converted["tool_calls"] = [
                {
                    "id": f"call_{i}",
                    "type": "function",
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": json.dumps(tc["function"].get("arguments", {}))
                        if isinstance(tc["function"].get("arguments"), dict)
                        else tc["function"].get("arguments", "{}"),
                    },
                }
                for i, tc in enumerate(msg["tool_calls"])
            ]

        result.append(converted)
    return result


def _convert_messages_from_openai(messages: list[dict]) -> list[dict]:
    """Convert OpenAI message format back to Ollama format."""
    result = []
    for msg in messages:
        converted = {"role": msg["role"], "content": msg.get("content", "")}

        # Handle tool calls
        if msg.get("tool_calls"):
            converted["tool_calls"] = [
                {
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": json.loads(tc["function"]["arguments"])
                        if isinstance(tc["function"]["arguments"], str)
                        else tc["function"]["arguments"],
                    }
                }
                for tc in msg["tool_calls"]
            ]

        # Handle tool responses (drop tool_call_id as Ollama doesn't use it)
        if msg["role"] == "tool" and "tool_call_id" in msg:
            converted = {"role": "tool", "content": msg.get("content", "")}

        result.append(converted)
    return result


def _openai_message_to_dict(message) -> dict:
    """Convert OpenAI message object to dict."""
    result = {"role": message.role, "content": message.content or ""}

    if message.tool_calls:
        result["tool_calls"] = [
            {
                "id": tc.id,
                "type": tc.type,
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in message.tool_calls
        ]

    return result


def _convert_openai_to_ollama_format(message) -> dict:
    """Convert OpenAI assistant message to Ollama format."""
    result = {"role": "assistant", "content": message.content or ""}

    if message.tool_calls:
        result["tool_calls"] = [
            {
                "function": {
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments)
                    if isinstance(tc.function.arguments, str)
                    else tc.function.arguments,
                }
            }
            for tc in message.tool_calls
        ]

    return result
