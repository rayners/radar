"""Create tool meta-tool for LLM-driven tool generation."""

import json

from radar.config import get_config
from radar.plugins import get_plugin_loader
from radar.tools import tool


@tool(
    name="create_tool",
    description="""Create a new tool/plugin. The code will be validated for safety and tested before saving.

IMPORTANT: The code must define a function with the SAME NAME as the tool name parameter.
For example, if name="reverse_string", the code must contain: def reverse_string(text: str) -> str:

The function should:
- Take parameters as keyword arguments
- Return a string result
- Not use dangerous operations (no os, subprocess, file I/O, network, etc.)
- Be self-contained (no external dependencies)

Test cases verify the function works correctly before saving.""",
    parameters={
        "name": {
            "type": "string",
            "description": "Tool name (must match function name in code, use snake_case)",
        },
        "description": {
            "type": "string",
            "description": "Human-readable description of what the tool does",
        },
        "parameters": {
            "type": "object",
            "description": "JSON Schema for tool parameters (properties dict format)",
        },
        "code": {
            "type": "string",
            "description": "Python code defining the tool function. Function name MUST match the 'name' parameter.",
        },
        "test_cases": {
            "type": "array",
            "description": "List of test cases. Each test case should have: name, input_args (dict), expected_output (string) or expected_contains (string)",
        },
    },
)
def create_tool(
    name: str,
    description: str,
    parameters: dict,
    code: str,
    test_cases: list[dict],
) -> str:
    """Create a new tool with validation and testing."""
    config = get_config()

    # Check if LLM-generated tools are allowed
    if not config.plugins.allow_llm_generated:
        return "Error: LLM-generated tools are disabled in configuration"

    # Validate name
    if not name.replace("_", "").isalnum():
        return f"Error: Invalid tool name '{name}'. Use only letters, numbers, and underscores."

    # Ensure at least one test case
    if not test_cases:
        return "Error: At least one test case is required"

    # Determine auto-approve setting
    auto_approve = config.plugins.auto_approve or config.plugins.auto_approve_if_tests_pass

    # Create the plugin
    loader = get_plugin_loader()
    success, message, error_details = loader.create_plugin(
        name=name,
        description=description,
        parameters=parameters,
        code=code,
        test_cases=test_cases,
        auto_approve=auto_approve,
    )

    if success:
        return message

    # Handle failure - provide debugging information
    result = f"Failed to create tool: {message}\n"

    if error_details:
        if "issues" in error_details:
            result += "\nValidation issues:\n"
            for issue in error_details["issues"]:
                result += f"  - {issue}\n"

        if "test_results" in error_details:
            result += "\nTest results:\n"
            for test in error_details["test_results"]:
                status = "PASS" if test.get("passed") else "FAIL"
                result += f"  [{status}] {test.get('name', 'test')}\n"
                if not test.get("passed"):
                    if test.get("error"):
                        result += f"    Error: {test['error']}\n"
                    if test.get("traceback"):
                        # Truncate long tracebacks
                        tb = test["traceback"]
                        if len(tb) > 500:
                            tb = tb[:500] + "..."
                        result += f"    Traceback:\n{tb}\n"

        if "error" in error_details and error_details["error"]:
            result += "\nUse the debug_tool to view full error details and attempt fixes."

    return result
