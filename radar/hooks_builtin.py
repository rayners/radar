"""Config-driven hook builders.

Reads hooks.rules from radar.yaml and registers hook callbacks.
"""

import logging
import re
from datetime import datetime
from typing import Any

from radar.hooks import HookPoint, HookRegistration, HookResult, register_hook

logger = logging.getLogger("radar.hooks")


DEFAULT_SAFETY_RULES: list[dict] = [
    {
        "name": "block_injection_phrases",
        "hook_point": "pre_agent_run",
        "type": "block_message_pattern",
        "patterns": [
            "ignore previous instructions",
            "ignore all previous",
            "disregard previous instructions",
            "override system prompt",
            "new system prompt",
        ],
        "message": "Message blocked: detected prompt injection attempt",
        "priority": 10,
    },
    {
        "name": "anti_memory_poisoning",
        "hook_point": "pre_memory_store",
        "type": "block_memory_pattern",
        "patterns": [
            "ignore previous instructions",
            "override system prompt",
            "you are now",
            "new instructions:",
        ],
        "message": "Memory blocked: contains instruction-like content",
        "priority": 10,
    },
]


def load_config_hooks() -> int:
    """Load hooks from config and register them.

    When hooks are enabled but no user rules are configured, baseline safety
    rules are applied automatically (prompt injection blocking, memory
    anti-poisoning).

    Returns count of hooks registered.
    """
    try:
        from radar.config import get_config
        config = get_config()
    except Exception:
        return 0

    if not config.hooks.enabled:
        return 0

    rules = config.hooks.rules
    if not rules:
        rules = DEFAULT_SAFETY_RULES

    count = 0
    for rule in rules:
        try:
            registration = _build_hook(rule)
            if registration:
                register_hook(registration)
                count += 1
        except Exception:
            logger.warning(
                "Failed to build hook from rule: %s",
                rule.get("name", "(unnamed)"),
                exc_info=True,
            )

    if count:
        logger.info("Loaded %d config hook(s)", count)
    return count


def _build_hook(rule: dict) -> HookRegistration | None:
    """Build a HookRegistration from a config rule dict."""
    name = rule.get("name", "unnamed")
    hook_point_str = rule.get("hook_point", "")
    rule_type = rule.get("type", "")
    priority = rule.get("priority", 50)

    try:
        hook_point = HookPoint(hook_point_str)
    except ValueError:
        logger.warning("Unknown hook_point '%s' in rule '%s'", hook_point_str, name)
        return None

    callback = _build_callback(hook_point, rule_type, rule)
    if callback is None:
        logger.warning("Unknown rule type '%s' in rule '%s'", rule_type, name)
        return None

    return HookRegistration(
        name=name,
        hook_point=hook_point,
        callback=callback,
        priority=priority,
        source="config",
        description=rule.get("description", f"{rule_type} rule"),
    )


_CALLBACK_BUILDERS: dict[HookPoint, Any] = {}  # populated after definitions below


def _build_callback(
    hook_point: HookPoint,
    rule_type: str,
    rule: dict,
) -> Any:
    """Build a callback function for a rule type."""
    builder = _CALLBACK_BUILDERS.get(hook_point)
    if builder is None:
        return None
    return builder(rule_type, rule)


# --- Pre-tool callbacks ---


def _build_pre_callback(rule_type: str, rule: dict) -> Any:
    """Build a pre-tool-call callback."""
    if rule_type == "block_command_pattern":
        return _make_block_command_pattern(rule)
    elif rule_type == "block_path_pattern":
        return _make_block_path_pattern(rule)
    elif rule_type == "block_tool":
        return _make_block_tool(rule)
    return None


def _make_block_command_pattern(rule: dict) -> Any:
    """Block exec commands matching substring patterns."""
    patterns = rule.get("patterns", [])
    tools = set(rule.get("tools", ["exec"]))
    message = rule.get("message", "Command blocked by hook")

    def callback(tool_name: str, arguments: dict) -> HookResult:
        if tool_name not in tools:
            return HookResult()
        command = arguments.get("command", "")
        for pattern in patterns:
            if pattern in command:
                return HookResult(blocked=True, message=message)
        return HookResult()

    return callback


def _make_block_path_pattern(rule: dict) -> Any:
    """Block file tools accessing paths under configured directories."""
    from pathlib import Path

    blocked_dirs = [Path(d).expanduser().resolve() for d in rule.get("paths", [])]
    tools = set(rule.get("tools", ["read_file", "write_file"]))
    message = rule.get("message", "Path blocked by hook")

    def callback(tool_name: str, arguments: dict) -> HookResult:
        if tool_name not in tools:
            return HookResult()
        path_str = arguments.get("path", "") or arguments.get("file_path", "")
        if not path_str:
            return HookResult()
        try:
            target = Path(path_str).expanduser().resolve()
            for blocked in blocked_dirs:
                if target == blocked or blocked in target.parents:
                    return HookResult(blocked=True, message=message)
        except Exception:
            pass
        return HookResult()

    return callback


def _make_block_tool(rule: dict) -> Any:
    """Block specific tools entirely."""
    blocked_tools = set(rule.get("tools", []))
    message = rule.get("message", "Tool blocked by hook")

    def callback(tool_name: str, arguments: dict) -> HookResult:
        if tool_name in blocked_tools:
            return HookResult(blocked=True, message=message)
        return HookResult()

    return callback


# --- Post-tool callbacks ---


def _build_post_callback(rule_type: str, rule: dict) -> Any:
    """Build a post-tool-call callback."""
    if rule_type == "log":
        return _make_log_callback(rule)
    return None


def _make_log_callback(rule: dict) -> Any:
    """Log tool execution."""
    log_level = rule.get("log_level", "info")

    def callback(
        tool_name: str,
        arguments: dict,
        result: str,
        success: bool,
    ) -> None:
        from radar.logging import log
        status = "success" if success else "failure"
        log(log_level, f"Hook log: {tool_name} ({status})", tool=tool_name)

    return callback


# --- Filter callbacks ---


def _build_filter_callback(rule_type: str, rule: dict) -> Any:
    """Build a filter-tools callback."""
    if rule_type == "time_restrict":
        return _make_time_restrict(rule)
    elif rule_type == "allowlist":
        return _make_allowlist(rule)
    elif rule_type == "denylist":
        return _make_denylist(rule)
    return None


def _make_time_restrict(rule: dict) -> Any:
    """Remove tools during a time window."""
    start_hour = rule.get("start_hour", 22)
    end_hour = rule.get("end_hour", 8)
    restricted_tools = set(rule.get("tools", []))

    def callback(tools: list[dict]) -> list[dict]:
        hour = datetime.now().hour
        # Check if current hour falls in restricted window
        if start_hour > end_hour:
            # Wraps midnight (e.g., 22:00-08:00)
            in_window = hour >= start_hour or hour < end_hour
        else:
            # Same-day window (e.g., 09:00-17:00)
            in_window = start_hour <= hour < end_hour

        if not in_window:
            return tools

        return [
            t for t in tools
            if t.get("function", {}).get("name") not in restricted_tools
        ]

    return callback


def _make_allowlist(rule: dict) -> Any:
    """Only keep tools in the allowlist."""
    allowed = set(rule.get("tools", []))

    def callback(tools: list[dict]) -> list[dict]:
        return [
            t for t in tools
            if t.get("function", {}).get("name") in allowed
        ]

    return callback


def _make_denylist(rule: dict) -> Any:
    """Remove tools in the denylist."""
    denied = set(rule.get("tools", []))

    def callback(tools: list[dict]) -> list[dict]:
        return [
            t for t in tools
            if t.get("function", {}).get("name") not in denied
        ]

    return callback


# --- Pre-agent callbacks ---


def _build_pre_agent_callback(rule_type: str, rule: dict) -> Any:
    """Build a pre-agent callback."""
    if rule_type == "block_message_pattern":
        return _make_block_message_pattern(rule)
    return None


def _make_block_message_pattern(rule: dict) -> Any:
    """Block messages matching substring patterns."""
    patterns = rule.get("patterns", [])
    message = rule.get("message", "Message blocked by hook")

    def callback(user_message: str, conversation_id: str | None) -> HookResult:
        lower_msg = user_message.lower()
        for pattern in patterns:
            if pattern.lower() in lower_msg:
                return HookResult(blocked=True, message=message)
        return HookResult()

    return callback


# --- Post-agent callbacks ---


def _build_post_agent_callback(rule_type: str, rule: dict) -> Any:
    """Build a post-agent callback."""
    if rule_type == "redact_response":
        return _make_redact_response(rule)
    elif rule_type == "log_agent":
        return _make_log_agent(rule)
    return None


def _make_redact_response(rule: dict) -> Any:
    """Replace patterns in LLM responses."""
    patterns = [re.compile(p) for p in rule.get("patterns", [])]
    replacement = rule.get("replacement", "[REDACTED]")

    def callback(
        user_message: str,
        response: str,
        conversation_id: str | None,
    ) -> str:
        for pattern in patterns:
            response = pattern.sub(replacement, response)
        return response

    return callback


def _make_log_agent(rule: dict) -> Any:
    """Log agent interactions."""
    log_level = rule.get("log_level", "info")

    def callback(
        user_message: str,
        response: str,
        conversation_id: str | None,
    ) -> None:
        from radar.logging import log
        log(log_level, f"Hook log: agent run (conversation={conversation_id})")

    return callback


# --- Pre-memory callbacks ---


def _build_pre_memory_callback(rule_type: str, rule: dict) -> Any:
    """Build a pre-memory-store callback."""
    if rule_type == "block_memory_pattern":
        return _make_block_memory_pattern(rule)
    return None


def _make_block_memory_pattern(rule: dict) -> Any:
    """Block storing memories matching patterns."""
    patterns = rule.get("patterns", [])
    message = rule.get("message", "Memory storage blocked by hook")

    def callback(content: str, source: str | None) -> HookResult:
        lower_content = content.lower()
        for pattern in patterns:
            if pattern.lower() in lower_content:
                return HookResult(blocked=True, message=message)
        return HookResult()

    return callback


# --- Post-memory callbacks ---


def _build_post_memory_callback(rule_type: str, rule: dict) -> Any:
    """Build a post-memory-search callback."""
    if rule_type == "filter_memory_pattern":
        return _make_filter_memory_pattern(rule)
    return None


def _make_filter_memory_pattern(rule: dict) -> Any:
    """Remove search results matching patterns."""
    exclude_patterns = rule.get("exclude_patterns", [])

    def callback(query: str, results: list[dict]) -> list[dict]:
        filtered = []
        for result in results:
            content = result.get("content", "").lower()
            if not any(p.lower() in content for p in exclude_patterns):
                filtered.append(result)
        return filtered

    return callback


# --- Pre-heartbeat callbacks ---


def _build_pre_heartbeat_callback(rule_type: str, rule: dict) -> Any:
    """Build a pre-heartbeat callback."""
    # No config-driven pre-heartbeat rules yet; plugin hooks can fill this.
    return None


# --- Post-heartbeat callbacks ---


def _build_post_heartbeat_callback(rule_type: str, rule: dict) -> Any:
    """Build a post-heartbeat callback."""
    if rule_type == "log_heartbeat":
        return _make_log_heartbeat(rule)
    return None


def _make_log_heartbeat(rule: dict) -> Any:
    """Log heartbeat execution."""
    log_level = rule.get("log_level", "info")

    def callback(event_count: int, success: bool, error: str | None) -> None:
        from radar.logging import log
        status = "success" if success else f"failure: {error}"
        log(log_level, f"Hook log: heartbeat ({status}, {event_count} events)")

    return callback


# --- Heartbeat-collect callbacks ---


def _build_heartbeat_collect_callback(rule_type: str, rule: dict) -> Any:
    """Build a heartbeat-collect callback.

    No config-driven rules for this hook point; only plugin hooks contribute.
    """
    return None


# Populate the dispatch dict now that all builder functions are defined.
_CALLBACK_BUILDERS.update({
    HookPoint.PRE_TOOL_CALL: _build_pre_callback,
    HookPoint.POST_TOOL_CALL: _build_post_callback,
    HookPoint.FILTER_TOOLS: _build_filter_callback,
    HookPoint.PRE_AGENT_RUN: _build_pre_agent_callback,
    HookPoint.POST_AGENT_RUN: _build_post_agent_callback,
    HookPoint.PRE_MEMORY_STORE: _build_pre_memory_callback,
    HookPoint.POST_MEMORY_SEARCH: _build_post_memory_callback,
    HookPoint.PRE_HEARTBEAT: _build_pre_heartbeat_callback,
    HookPoint.POST_HEARTBEAT: _build_post_heartbeat_callback,
    HookPoint.HEARTBEAT_COLLECT: _build_heartbeat_collect_callback,
})
