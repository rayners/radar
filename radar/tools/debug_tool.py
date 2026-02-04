"""Debug tool for iteratively fixing failed plugins."""

from radar.config import get_config
from radar.plugins import get_plugin_loader
from radar.tools import tool


@tool(
    name="debug_tool",
    description="""Debug a failing tool by viewing errors and proposing fixes.

Call without fix_code to see the last error, traceback, and failing test case.
Call with fix_code to apply a fix and re-run tests.

The debugging loop:
1. Call debug_tool(tool_name="xxx") to see the error
2. Analyze the error and write fixed code
3. Call debug_tool(tool_name="xxx", fix_code="...fixed code...") to apply and test
4. Repeat until tests pass or max attempts reached""",
    parameters={
        "tool_name": {
            "type": "string",
            "description": "Name of the tool to debug",
        },
        "fix_code": {
            "type": "string",
            "description": "Updated Python code to fix the tool (optional - omit to view error)",
            "optional": True,
        },
    },
)
def debug_tool(tool_name: str, fix_code: str = None) -> str:
    """Debug a failing tool by viewing errors or applying fixes."""
    config = get_config()
    loader = get_plugin_loader()

    if fix_code is None:
        # Return the last error for this tool
        last_error = loader.get_last_error(tool_name)

        if last_error is None:
            return f"No errors found for tool '{tool_name}'"

        result = f"=== Debug info for '{tool_name}' ===\n\n"
        result += f"Error type: {last_error.error_type}\n"
        result += f"Attempt: {last_error.attempt_number} of {last_error.max_attempts}\n"
        result += f"Timestamp: {last_error.timestamp}\n\n"

        result += f"Error message:\n{last_error.message}\n\n"

        if last_error.input_args:
            result += f"Input arguments:\n{last_error.input_args}\n\n"

        if last_error.expected_output:
            result += f"Expected output: {last_error.expected_output}\n"

        if last_error.actual_output:
            result += f"Actual output: {last_error.actual_output}\n\n"

        if last_error.traceback_str:
            # Truncate very long tracebacks
            tb = last_error.traceback_str
            if len(tb) > 1500:
                tb = tb[:1500] + "\n... (truncated)"
            result += f"Traceback:\n{tb}\n"

        # Get current code for reference
        plugin_path = loader.pending_dir / tool_name
        if not plugin_path.exists():
            plugin_path = loader.available_dir / tool_name

        if plugin_path.exists():
            code_file = plugin_path / "tool.py"
            if code_file.exists():
                current_code = code_file.read_text()
                if len(current_code) > 2000:
                    current_code = current_code[:2000] + "\n... (truncated)"
                result += f"\n=== Current code ===\n{current_code}\n"

        if last_error.attempt_number >= last_error.max_attempts:
            result += f"\n[WARNING] Max attempts ({last_error.max_attempts}) reached. "
            result += "Consider a different approach or manual intervention."

        return result

    # Apply fix_code
    error_count = loader.get_error_count(tool_name)
    max_attempts = config.plugins.max_debug_attempts

    if error_count >= max_attempts:
        return (
            f"Max debug attempts ({max_attempts}) reached for '{tool_name}'. "
            "The tool has been saved to the 'failed' directory. "
            "Consider trying a completely different approach or ask the user for help."
        )

    # Attempt the fix
    success, message, error_details = loader.update_plugin_code(tool_name, fix_code)

    if success:
        result = f"Success! Tool '{tool_name}' fixed and updated.\n"
        result += "All tests passed. "

        # Check if it needs approval
        pending_path = loader.pending_dir / tool_name
        if pending_path.exists():
            result += "The tool is in pending_review and requires human approval."
        else:
            result += "The tool is now active and can be used."

        return result

    # Fix failed
    result = f"Fix attempt failed: {message}\n\n"

    if error_details:
        if "issues" in error_details:
            result += "Validation issues:\n"
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
                    if test.get("output"):
                        result += f"    Output: {test['output']}\n"

        if "attempt" in error_details:
            remaining = max_attempts - error_details["attempt"]
            result += f"\nAttempts remaining: {remaining}"

    return result
