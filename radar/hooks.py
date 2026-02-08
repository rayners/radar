"""Hook system for intercepting tool execution and filtering tool lists."""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("radar.hooks")


class HookPoint(Enum):
    """Points where hooks can intercept."""

    PRE_TOOL_CALL = "pre_tool_call"
    POST_TOOL_CALL = "post_tool_call"
    FILTER_TOOLS = "filter_tools"
    PRE_AGENT_RUN = "pre_agent_run"
    POST_AGENT_RUN = "post_agent_run"
    PRE_MEMORY_STORE = "pre_memory_store"
    POST_MEMORY_SEARCH = "post_memory_search"
    PRE_HEARTBEAT = "pre_heartbeat"
    POST_HEARTBEAT = "post_heartbeat"
    HEARTBEAT_COLLECT = "heartbeat_collect"


@dataclass
class HookResult:
    """Result from a pre-tool hook."""

    blocked: bool = False
    message: str = ""


@dataclass
class HookRegistration:
    """A registered hook callback."""

    name: str
    hook_point: HookPoint
    callback: Callable
    priority: int = 50
    source: str = ""  # e.g. "config", "plugin:my_plugin"
    description: str = ""


# Global registry: hook point -> sorted list of registrations
_hooks: dict[HookPoint, list[HookRegistration]] = {
    HookPoint.PRE_TOOL_CALL: [],
    HookPoint.POST_TOOL_CALL: [],
    HookPoint.FILTER_TOOLS: [],
    HookPoint.PRE_AGENT_RUN: [],
    HookPoint.POST_AGENT_RUN: [],
    HookPoint.PRE_MEMORY_STORE: [],
    HookPoint.POST_MEMORY_SEARCH: [],
    HookPoint.PRE_HEARTBEAT: [],
    HookPoint.POST_HEARTBEAT: [],
    HookPoint.HEARTBEAT_COLLECT: [],
}


def register_hook(registration: HookRegistration) -> None:
    """Register a hook callback.

    Hooks are kept sorted by priority (lower numbers run first).
    """
    hooks_list = _hooks[registration.hook_point]
    hooks_list.append(registration)
    hooks_list.sort(key=lambda h: h.priority)
    logger.debug(
        "Registered hook '%s' at %s (priority %d, source=%s)",
        registration.name,
        registration.hook_point.value,
        registration.priority,
        registration.source,
    )


def unregister_hook(name: str) -> bool:
    """Unregister a hook by name.

    Returns True if a hook was removed.
    """
    removed = False
    for hook_point in _hooks:
        before = len(_hooks[hook_point])
        _hooks[hook_point] = [h for h in _hooks[hook_point] if h.name != name]
        if len(_hooks[hook_point]) < before:
            removed = True
    return removed


def unregister_hooks_by_source(source: str) -> int:
    """Unregister all hooks from a given source.

    Returns count of hooks removed.
    """
    count = 0
    for hook_point in _hooks:
        before = len(_hooks[hook_point])
        _hooks[hook_point] = [h for h in _hooks[hook_point] if h.source != source]
        count += before - len(_hooks[hook_point])
    return count


def clear_all_hooks() -> None:
    """Remove all registered hooks."""
    for hook_point in _hooks:
        _hooks[hook_point].clear()


def list_hooks() -> list[dict[str, Any]]:
    """List all registered hooks for introspection."""
    result = []
    for hook_point, hooks_list in _hooks.items():
        for h in hooks_list:
            result.append({
                "name": h.name,
                "hook_point": hook_point.value,
                "priority": h.priority,
                "source": h.source,
                "description": h.description,
            })
    return result


def run_pre_tool_hooks(tool_name: str, arguments: dict[str, Any]) -> HookResult:
    """Run all pre-tool-call hooks.

    Returns a HookResult. If any hook blocks, short-circuits immediately.
    """
    hooks_list = _hooks[HookPoint.PRE_TOOL_CALL]
    if not hooks_list:
        return HookResult()

    for hook in hooks_list:
        try:
            result = hook.callback(tool_name, arguments)
            if isinstance(result, HookResult) and result.blocked:
                logger.info(
                    "Hook '%s' blocked tool '%s': %s",
                    hook.name, tool_name, result.message,
                )
                return result
        except Exception:
            logger.warning(
                "Hook '%s' raised an exception (skipping)",
                hook.name,
                exc_info=True,
            )

    return HookResult()


def run_post_tool_hooks(
    tool_name: str,
    arguments: dict[str, Any],
    result: str,
    success: bool,
) -> None:
    """Run all post-tool-call hooks (observe only, cannot block)."""
    hooks_list = _hooks[HookPoint.POST_TOOL_CALL]
    if not hooks_list:
        return

    for hook in hooks_list:
        try:
            hook.callback(tool_name, arguments, result, success)
        except Exception:
            logger.warning(
                "Post-hook '%s' raised an exception (skipping)",
                hook.name,
                exc_info=True,
            )


def run_filter_tools_hooks(tools: list[dict]) -> list[dict]:
    """Run all filter-tools hooks, chaining the result.

    Each hook receives the tool list and returns a (possibly filtered) list.
    """
    hooks_list = _hooks[HookPoint.FILTER_TOOLS]
    if not hooks_list:
        return tools

    for hook in hooks_list:
        try:
            filtered = hook.callback(tools)
            if isinstance(filtered, list):
                tools = filtered
        except Exception:
            logger.warning(
                "Filter hook '%s' raised an exception (skipping)",
                hook.name,
                exc_info=True,
            )

    return tools


def run_pre_agent_hooks(user_message: str, conversation_id: str | None) -> HookResult:
    """Run all pre-agent hooks.

    Returns a HookResult. If any hook blocks, short-circuits immediately.
    """
    hooks_list = _hooks[HookPoint.PRE_AGENT_RUN]
    if not hooks_list:
        return HookResult()

    for hook in hooks_list:
        try:
            result = hook.callback(user_message, conversation_id)
            if isinstance(result, HookResult) and result.blocked:
                logger.info(
                    "Hook '%s' blocked agent run: %s",
                    hook.name, result.message,
                )
                return result
        except Exception:
            logger.warning(
                "Hook '%s' raised an exception (skipping)",
                hook.name,
                exc_info=True,
            )

    return HookResult()


def run_post_agent_hooks(
    user_message: str,
    response: str,
    conversation_id: str | None,
) -> str:
    """Run all post-agent hooks. Callbacks can return a modified response string."""
    hooks_list = _hooks[HookPoint.POST_AGENT_RUN]
    if not hooks_list:
        return response

    for hook in hooks_list:
        try:
            result = hook.callback(user_message, response, conversation_id)
            if isinstance(result, str):
                response = result
        except Exception:
            logger.warning(
                "Post-agent hook '%s' raised an exception (skipping)",
                hook.name,
                exc_info=True,
            )

    return response


def run_pre_memory_store_hooks(content: str, source: str | None) -> HookResult:
    """Run all pre-memory-store hooks.

    Returns a HookResult. If any hook blocks, short-circuits immediately.
    """
    hooks_list = _hooks[HookPoint.PRE_MEMORY_STORE]
    if not hooks_list:
        return HookResult()

    for hook in hooks_list:
        try:
            result = hook.callback(content, source)
            if isinstance(result, HookResult) and result.blocked:
                logger.info(
                    "Hook '%s' blocked memory store: %s",
                    hook.name, result.message,
                )
                return result
        except Exception:
            logger.warning(
                "Hook '%s' raised an exception (skipping)",
                hook.name,
                exc_info=True,
            )

    return HookResult()


def run_post_memory_search_hooks(query: str, results: list[dict]) -> list[dict]:
    """Run all post-memory-search hooks. Callbacks can filter/rerank results."""
    hooks_list = _hooks[HookPoint.POST_MEMORY_SEARCH]
    if not hooks_list:
        return results

    for hook in hooks_list:
        try:
            filtered = hook.callback(query, results)
            if isinstance(filtered, list):
                results = filtered
        except Exception:
            logger.warning(
                "Post-memory hook '%s' raised an exception (skipping)",
                hook.name,
                exc_info=True,
            )

    return results


def run_pre_heartbeat_hooks(event_count: int) -> HookResult:
    """Run all pre-heartbeat hooks.

    Returns a HookResult. If any hook blocks, short-circuits immediately.
    """
    hooks_list = _hooks[HookPoint.PRE_HEARTBEAT]
    if not hooks_list:
        return HookResult()

    for hook in hooks_list:
        try:
            result = hook.callback(event_count)
            if isinstance(result, HookResult) and result.blocked:
                logger.info(
                    "Hook '%s' blocked heartbeat: %s",
                    hook.name, result.message,
                )
                return result
        except Exception:
            logger.warning(
                "Hook '%s' raised an exception (skipping)",
                hook.name,
                exc_info=True,
            )

    return HookResult()


def run_post_heartbeat_hooks(
    event_count: int,
    success: bool,
    error: str | None,
) -> None:
    """Run all post-heartbeat hooks (observe only, cannot block)."""
    hooks_list = _hooks[HookPoint.POST_HEARTBEAT]
    if not hooks_list:
        return

    for hook in hooks_list:
        try:
            hook.callback(event_count, success, error)
        except Exception:
            logger.warning(
                "Post-heartbeat hook '%s' raised an exception (skipping)",
                hook.name,
                exc_info=True,
            )


def run_heartbeat_collect_hooks() -> list[dict]:
    """Run all heartbeat-collect hooks and return collected events.

    Each callback should return a list of event dicts (or a single dict).
    Results are merged into a flat list. Failing hooks are logged and skipped.
    """
    hooks_list = _hooks[HookPoint.HEARTBEAT_COLLECT]
    if not hooks_list:
        return []

    events: list[dict] = []
    for hook in hooks_list:
        try:
            result = hook.callback()
            if isinstance(result, list):
                events.extend(result)
            elif isinstance(result, dict):
                events.append(result)
        except Exception:
            logger.warning(
                "Heartbeat-collect hook '%s' raised an exception (skipping)",
                hook.name,
                exc_info=True,
            )

    return events
