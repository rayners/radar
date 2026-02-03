"""Tool registry with decorator-based registration."""

from functools import wraps
from typing import Any, Callable

# Global registry: name -> (function, schema)
_registry: dict[str, tuple[Callable, dict]] = {}


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
) -> Callable:
    """Decorator to register a function as a tool.

    Args:
        name: Tool name for the API
        description: Human-readable description
        parameters: JSON Schema for parameters (properties dict)
    """

    def decorator(func: Callable) -> Callable:
        schema = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": parameters,
                    "required": [k for k, v in parameters.items() if not v.get("optional", False)],
                },
            },
        }
        _registry[name] = (func, schema)

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


def get_tools_schema() -> list[dict]:
    """Return list of tool definitions for the API."""
    return [schema for _, schema in _registry.values()]


def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    """Execute a tool by name with given arguments.

    Returns the tool's string result or error message.
    """
    if name not in _registry:
        return f"Error: Unknown tool '{name}'"

    func, _ = _registry[name]
    try:
        result = func(**arguments)
        return str(result)
    except Exception as e:
        return f"Error executing {name}: {e}"


def get_tool_names() -> list[str]:
    """Get list of registered tool names."""
    return list(_registry.keys())


# Auto-import all tool modules to register them
from radar.tools import (
    exec,
    list_directory,
    notify,
    pdf_extract,
    read_file,
    write_file,
)

__all__ = [
    "tool",
    "get_tools_schema",
    "execute_tool",
    "get_tool_names",
]
