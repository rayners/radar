"""Tool registry with decorator-based registration."""

import builtins
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


def register_dynamic_tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    code: str,
) -> bool:
    """Register a dynamically loaded tool.

    Args:
        name: Tool name for the API
        description: Human-readable description
        parameters: JSON Schema for parameters (properties dict)
        code: Python code containing the tool function

    Returns:
        True if registration succeeded, False otherwise.
    """
    # Create the tool schema
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

    # Create a safe namespace for execution
    safe_builtins = {
        "True": True,
        "False": False,
        "None": None,
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "chr": chr,
        "dict": dict,
        "divmod": divmod,
        "enumerate": enumerate,
        "filter": filter,
        "float": float,
        "format": format,
        "frozenset": frozenset,
        "hash": hash,
        "hex": hex,
        "int": int,
        "isinstance": isinstance,
        "issubclass": issubclass,
        "iter": iter,
        "len": len,
        "list": list,
        "map": map,
        "max": max,
        "min": min,
        "next": next,
        "oct": oct,
        "ord": ord,
        "pow": pow,
        "print": print,
        "range": range,
        "repr": repr,
        "reversed": reversed,
        "round": round,
        "set": set,
        "slice": slice,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "type": type,
        "zip": zip,
    }

    namespace = {"__builtins__": safe_builtins}

    try:
        # Execute the code to define the function
        # Note: This code has been validated by CodeValidator before reaching here
        # Using builtins.exec() because 'exec' is shadowed by radar.tools.exec module
        builtins.exec(code, namespace)  # noqa: S102

        # Get the function
        if name not in namespace:
            return False

        func = namespace[name]

        # Register it
        _registry[name] = (func, schema)
        return True

    except Exception:
        return False


def unregister_tool(name: str) -> bool:
    """Unregister a tool by name.

    Args:
        name: Name of the tool to unregister

    Returns:
        True if tool was unregistered, False if not found.
    """
    if name in _registry:
        del _registry[name]
        return True
    return False


def is_dynamic_tool(name: str) -> bool:
    """Check if a tool was dynamically registered."""
    # Dynamic tools aren't in the static imports list
    static_tools = {
        "exec", "github", "list_directory", "notify", "pdf_extract",
        "read_file", "recall", "remember", "weather", "write_file",
        "create_tool", "debug_tool", "rollback_tool",
        "suggest_personality_update", "analyze_feedback",
    }
    return name in _registry and name not in static_tools


# Auto-import all tool modules to register them
from radar.tools import (
    exec,
    github,
    list_directory,
    notify,
    pdf_extract,
    read_file,
    recall,
    remember,
    weather,
    write_file,
    create_tool,
    debug_tool,
    rollback_tool,
    suggest_personality,
    analyze_feedback,
)

__all__ = [
    "tool",
    "get_tools_schema",
    "execute_tool",
    "get_tool_names",
    "register_dynamic_tool",
    "unregister_tool",
    "is_dynamic_tool",
]
