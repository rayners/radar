"""LLM client with tool call support for Ollama and OpenAI-compatible APIs."""

import json
import time
from typing import Any

import httpx

from radar.config import get_config
from radar.retry import compute_delay, is_retryable_httpx_error, is_retryable_openai_error, log_retry
from radar.tools import execute_tool, get_tools_schema


def _log_api_call(provider: str, model: str) -> None:
    """Log an API call and increment counter."""
    try:
        from radar.logging import log, increment_api_calls
        increment_api_calls()
        log("debug", f"LLM API call", provider=provider, model=model)
    except Exception:
        pass  # Don't fail on logging errors


def _is_rate_limit_error(status_code: int | None, error_text: str) -> bool:
    """Check if an error indicates rate limiting."""
    if status_code in (429, 503):
        return True
    lower = error_text.lower()
    return "rate limit" in lower or "temporarily unavailable" in lower


def _log_fallback(primary: str, fallback: str, status_code: int | None, error_text: str) -> None:
    """Log a model fallback event."""
    try:
        from radar.logging import log
        log(
            "warn",
            f"Rate limited on {primary} (HTTP {status_code}), falling back to {fallback}",
            primary_model=primary,
            fallback_model=fallback,
            error=error_text[:200],
        )
    except Exception:
        pass


def chat(
    messages: list[dict[str, Any]],
    use_tools: bool = True,
    model_override: str | None = None,
    fallback_model_override: str | None = None,
    tools_include: list[str] | None = None,
    tools_exclude: list[str] | None = None,
    provider_override: str | None = None,
    base_url_override: str | None = None,
    api_key_override: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Send messages to LLM and handle tool calls.

    Args:
        messages: List of message dicts with role/content
        use_tools: Whether to include tools and handle tool calls
        model_override: Model to use instead of config default (e.g. from personality)
        fallback_model_override: Fallback model override (e.g. from personality)
        tools_include: If set, only provide these tools (allowlist)
        tools_exclude: If set, exclude these tools (denylist)
        provider_override: LLM provider override (e.g. from personality)
        base_url_override: API base URL override (e.g. from personality)
        api_key_override: API key override (resolved from env var by caller)

    Returns:
        Tuple of (final assistant message, full message history)
    """
    config = get_config()
    effective_provider = provider_override or config.llm.provider

    if effective_provider == "openai":
        return _chat_openai(
            messages, use_tools, config,
            model_override=model_override,
            fallback_model_override=fallback_model_override,
            tools_include=tools_include,
            tools_exclude=tools_exclude,
            base_url_override=base_url_override,
            api_key_override=api_key_override,
        )
    else:
        return _chat_ollama(
            messages, use_tools, config,
            model_override=model_override,
            fallback_model_override=fallback_model_override,
            tools_include=tools_include,
            tools_exclude=tools_exclude,
            base_url_override=base_url_override,
        )


def _chat_ollama(
    messages, use_tools, config, *,
    model_override=None, fallback_model_override=None,
    tools_include=None, tools_exclude=None,
    base_url_override=None,
):
    """Chat using Ollama's native API."""
    effective_base_url = base_url_override or config.llm.base_url
    url = f"{effective_base_url.rstrip('/')}/api/chat"

    tools = get_tools_schema(include=tools_include, exclude=tools_exclude) if use_tools else []
    all_messages = list(messages)
    iterations = 0
    active_model = model_override or config.llm.model
    effective_fallback = fallback_model_override or config.llm.fallback_model
    fell_back = False
    retry_cfg = config.retry
    max_retries = (retry_cfg.max_retries if retry_cfg.llm_retries else 0)

    while iterations < config.max_tool_iterations:
        iterations += 1

        payload = {
            "model": active_model,
            "messages": all_messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                _log_api_call("ollama", active_model)
                response = httpx.post(url, json=payload, timeout=120)
                response.raise_for_status()
                last_error = None
                break  # success
            except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as e:
                last_error = e
                if attempt < max_retries and is_retryable_httpx_error(e):
                    delay = compute_delay(
                        attempt,
                        retry_cfg.base_delay,
                        retry_cfg.max_delay,
                    )
                    log_retry("ollama", active_model, attempt, max_retries, e, delay)
                    time.sleep(delay)
                    continue
                break  # non-retryable or retries exhausted

        if last_error is not None:
            if isinstance(last_error, httpx.HTTPStatusError):
                status_code = last_error.response.status_code
                error_text = last_error.response.text
                if (
                    not fell_back
                    and effective_fallback
                    and _is_rate_limit_error(status_code, error_text)
                ):
                    _log_fallback(active_model, effective_fallback, status_code, error_text)
                    active_model = effective_fallback
                    fell_back = True
                    iterations -= 1  # Don't count failed attempt
                    continue
                raise RuntimeError(f"Ollama error: {status_code} - {error_text}")
            elif isinstance(last_error, httpx.TimeoutException):
                raise RuntimeError("Ollama request timed out")
            elif isinstance(last_error, httpx.ConnectError):
                raise RuntimeError(f"Cannot connect to Ollama at {effective_base_url}")

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


def _chat_openai(
    messages, use_tools, config, *,
    model_override=None, fallback_model_override=None,
    tools_include=None, tools_exclude=None,
    base_url_override=None, api_key_override=None,
):
    """Chat using OpenAI-compatible API."""
    from openai import OpenAI

    client = OpenAI(
        base_url=base_url_override or config.llm.base_url,
        api_key=api_key_override or config.llm.api_key or "not-needed",
    )

    tools = get_tools_schema(include=tools_include, exclude=tools_exclude) if use_tools else None
    all_messages = _convert_messages_to_openai(messages)
    iterations = 0
    active_model = model_override or config.llm.model
    effective_fallback = fallback_model_override or config.llm.fallback_model
    fell_back = False
    retry_cfg = config.retry
    max_retries = (retry_cfg.max_retries if retry_cfg.llm_retries else 0)

    # Convert tools to OpenAI format
    openai_tools = _convert_tools_to_openai(tools) if tools else None

    while iterations < config.max_tool_iterations:
        iterations += 1

        kwargs = {
            "model": active_model,
            "messages": all_messages,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                _log_api_call("openai", active_model)
                response = client.chat.completions.create(**kwargs)
                last_error = None
                break  # success
            except Exception as e:
                last_error = e
                if attempt < max_retries and is_retryable_openai_error(e):
                    delay = compute_delay(
                        attempt,
                        retry_cfg.base_delay,
                        retry_cfg.max_delay,
                    )
                    log_retry("openai", active_model, attempt, max_retries, e, delay)
                    time.sleep(delay)
                    continue
                break  # non-retryable or retries exhausted

        if last_error is not None:
            status_code = getattr(last_error, "status_code", None)
            error_text = str(last_error)
            if (
                not fell_back
                and effective_fallback
                and _is_rate_limit_error(status_code, error_text)
            ):
                _log_fallback(active_model, effective_fallback, status_code, error_text)
                active_model = effective_fallback
                fell_back = True
                iterations -= 1
                continue
            raise RuntimeError(f"OpenAI API error: {last_error}")

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
