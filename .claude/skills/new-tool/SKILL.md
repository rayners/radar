---
name: new-tool
description: "Scaffold a new radar tool with implementation, tests, and doc entries"
disable-model-invocation: true
---

# New Tool Generator

When the user invokes `/new-tool`, scaffold a complete new tool for radar.

The user should provide at minimum a tool name and description. Ask for clarification if needed.

## Step 1: Create the tool module

Create `radar/tools/<name>.py` following this pattern:

```python
"""Brief description of the tool."""

from radar.tools import tool


@tool(
    name="<name>",
    description="<description>",
    parameters={
        "param_name": {
            "type": "string",
            "description": "What this parameter does",
        },
        "optional_param": {
            "type": "string",
            "description": "An optional parameter",
            "optional": True,
        },
    },
)
def <name>(param_name: str, optional_param: str | None = None) -> str:
    """Brief docstring."""
    # Implementation here
    return "Result"
```

Key rules:
- Tools return strings (results displayed to user)
- Import from `radar.tools import tool`
- Use `from radar.config import get_config` if config is needed
- Mark optional parameters with `"optional": True` in the schema and `| None = None` in the signature
- The file is auto-discovered — no manual imports needed
- Parameter types: `"string"`, `"integer"`, `"boolean"`, `"array"`, `"object"`

## Step 2: Create tests

Create `tests/test_<name>.py` following this pattern:

```python
"""Tests for radar/tools/<name>.py."""

from radar.tools.<name> import <name>


class TestToolName:
    """Test the <name> tool."""

    def test_basic_usage(self):
        result = <name>("input")
        assert "expected" in result

    def test_error_handling(self):
        result = <name>("")
        assert "Error" in result or result  # Tools return error strings, not exceptions
```

Key rules:
- Test the function directly (bypass LLM)
- Use the `isolated_data_dir` fixture from `conftest.py` if the tool reads/writes data
- Patch at the source module (e.g., `radar.tools.<name>.some_dep`), not the importing module
- Tools return error strings rather than raising exceptions — test for those strings
- Use `TestClass` grouping with descriptive class names

## Step 3: Update docs/user-guide.md

Find the tools table (search for `| Tool | Category |`) and add a row:

```
| `<name>` | <Category> | <Brief description> |
```

Categories: `Input`, `Output`, `Memory`, `Automation`, `Meta`

Keep the table sorted by category, then alphabetically within each category.

## Step 4: Update docs/scenarios.md

Find the capability inventory table (search for `| Tool | Category | Key capability |`) and add a matching row:

```
| `<name>` | <Category> | <Brief description> |
```

## Step 5: Run tests

Run `python -m pytest tests/test_<name>.py -v` to verify the tests pass.

## Summary

After completion, list what was created:
- `radar/tools/<name>.py` — tool implementation
- `tests/test_<name>.py` — tests
- `docs/user-guide.md` — tools table updated
- `docs/scenarios.md` — capability inventory updated
