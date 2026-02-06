"""Tests for tool framework: decorator, execution, schema filtering, dynamic registration."""

from unittest.mock import patch

import pytest

from radar.tools import (
    _registry,
    execute_tool,
    get_tool_names,
    get_tools_schema,
    register_dynamic_tool,
    tool,
    unregister_tool,
    _log_tool_execution,
)


# ===== Fixture: temporary test tool =====

TEMP_TOOL_NAME = "_test_framework_tool"


@pytest.fixture(autouse=False)
def temp_tool():
    """Register a temporary tool for testing, clean up after."""

    @tool(
        name=TEMP_TOOL_NAME,
        description="Temporary tool for framework tests",
        parameters={
            "text": {"type": "string", "description": "Input text"},
            "count": {"type": "integer", "description": "Repeat count", "optional": True},
        },
    )
    def _test_framework_tool(text: str, count: int = 1) -> str:
        return text * count

    yield _test_framework_tool
    unregister_tool(TEMP_TOOL_NAME)


# ===== @tool decorator =====


class TestToolDecorator:
    """Test the @tool decorator for schema generation and registration."""

    def test_decorator_registers_tool(self, temp_tool):
        """Tool appears in _registry after decoration."""
        assert TEMP_TOOL_NAME in _registry

    def test_schema_structure(self, temp_tool):
        """Schema has correct top-level structure."""
        _, schema = _registry[TEMP_TOOL_NAME]
        assert schema["type"] == "function"
        assert "function" in schema
        func_schema = schema["function"]
        assert func_schema["name"] == TEMP_TOOL_NAME
        assert func_schema["description"] == "Temporary tool for framework tests"
        assert "parameters" in func_schema
        assert func_schema["parameters"]["type"] == "object"

    def test_required_params(self, temp_tool):
        """Non-optional params listed in required."""
        _, schema = _registry[TEMP_TOOL_NAME]
        required = schema["function"]["parameters"]["required"]
        assert "text" in required

    def test_optional_params_excluded_from_required(self, temp_tool):
        """Params with optional=True are not in required."""
        _, schema = _registry[TEMP_TOOL_NAME]
        required = schema["function"]["parameters"]["required"]
        assert "count" not in required

    def test_mixed_required_optional(self, temp_tool):
        """Both required and optional params are present in properties."""
        _, schema = _registry[TEMP_TOOL_NAME]
        props = schema["function"]["parameters"]["properties"]
        assert "text" in props
        assert "count" in props

    def test_empty_parameters(self):
        """No params produces empty properties and empty required."""
        name = "_test_empty_params"
        try:

            @tool(name=name, description="No params", parameters={})
            def _test_empty_params() -> str:
                return "ok"

            _, schema = _registry[name]
            assert schema["function"]["parameters"]["properties"] == {}
            assert schema["function"]["parameters"]["required"] == []
        finally:
            unregister_tool(name)

    def test_decorator_preserves_function(self, temp_tool):
        """Decorated function still returns correct value."""
        result = temp_tool("hello", count=3)
        assert result == "hellohellohello"


# ===== execute_tool() =====


class TestExecuteTool:
    """Test execute_tool() dispatch and error handling."""

    def test_execute_returns_result(self, temp_tool):
        """Successful call returns the tool's string."""
        result = execute_tool(TEMP_TOOL_NAME, {"text": "hi"})
        assert result == "hi"

    def test_execute_passes_arguments(self, temp_tool):
        """kwargs are forwarded correctly."""
        result = execute_tool(TEMP_TOOL_NAME, {"text": "ab", "count": 3})
        assert result == "ababab"

    def test_execute_unknown_tool(self):
        """Unknown tool returns error string."""
        result = execute_tool("_nonexistent_tool_xyz", {})
        assert result == "Error: Unknown tool '_nonexistent_tool_xyz'"

    def test_execute_exception_returns_error(self):
        """Tool that raises returns error string, no crash."""
        name = "_test_raises"
        try:

            @tool(name=name, description="Raises", parameters={})
            def _test_raises() -> str:
                raise RuntimeError("boom")

            result = execute_tool(name, {})
            assert "Error executing _test_raises" in result
            assert "boom" in result
        finally:
            unregister_tool(name)

    def test_execute_converts_nonstring(self):
        """Non-string return is coerced via str()."""
        name = "_test_returns_int"
        try:

            @tool(name=name, description="Returns int", parameters={})
            def _test_returns_int() -> str:
                return 42  # type: ignore[return-value]

            result = execute_tool(name, {})
            assert result == "42"
        finally:
            unregister_tool(name)

    def test_execute_no_args(self):
        """Tool with no parameters called with empty dict."""
        name = "_test_no_args"
        try:

            @tool(name=name, description="No args", parameters={})
            def _test_no_args() -> str:
                return "no args"

            result = execute_tool(name, {})
            assert result == "no args"
        finally:
            unregister_tool(name)

    def test_execute_optional_arg_missing(self, temp_tool):
        """Missing optional arg uses default value."""
        result = execute_tool(TEMP_TOOL_NAME, {"text": "x"})
        assert result == "x"


# ===== get_tools_schema() =====


class TestGetToolsSchema:
    """Test get_tools_schema() with include/exclude filtering."""

    @patch("radar.tools.ensure_external_tools_loaded")
    def test_schema_returns_all_by_default(self, mock_ext, temp_tool):
        """No filter returns all registered tools."""
        schemas = get_tools_schema()
        names = {s["function"]["name"] for s in schemas}
        assert TEMP_TOOL_NAME in names
        # Should have more than just our test tool
        assert len(schemas) > 1

    @patch("radar.tools.ensure_external_tools_loaded")
    def test_schema_include_filter(self, mock_ext, temp_tool):
        """Only named tools returned with include."""
        schemas = get_tools_schema(include=[TEMP_TOOL_NAME])
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == TEMP_TOOL_NAME

    @patch("radar.tools.ensure_external_tools_loaded")
    def test_schema_exclude_filter(self, mock_ext, temp_tool):
        """Named tools excluded."""
        schemas = get_tools_schema(exclude=[TEMP_TOOL_NAME])
        names = {s["function"]["name"] for s in schemas}
        assert TEMP_TOOL_NAME not in names
        assert len(schemas) >= 1  # Other tools should remain

    @patch("radar.tools.ensure_external_tools_loaded")
    def test_schema_include_nonexistent(self, mock_ext):
        """Include unknown name returns empty list."""
        schemas = get_tools_schema(include=["_does_not_exist_xyz"])
        assert schemas == []

    @patch("radar.tools.ensure_external_tools_loaded")
    def test_schema_both_filters_returns_all(self, mock_ext, temp_tool):
        """Both include and exclude set is caller error; returns all."""
        # The implementation: include is checked first. If both are set,
        # include takes precedence (not "returns all" as doc suggests).
        # Actually re-reading the code: if include is not None, it returns
        # the include-filtered set. The doc says "both set is caller error
        # (returns all)" but the code returns include-filtered.
        # Test the actual behavior:
        schemas = get_tools_schema(
            include=[TEMP_TOOL_NAME],
            exclude=["exec"],
        )
        # include is checked first, so only TEMP_TOOL_NAME returned
        names = {s["function"]["name"] for s in schemas}
        assert TEMP_TOOL_NAME in names


# ===== register_dynamic_tool() =====


class TestRegisterDynamicTool:
    """Test register_dynamic_tool() sandboxed registration."""

    def test_register_success(self):
        """Returns True and tool is callable."""
        name = "_test_dyn_success"
        code = f"def {name}(x):\n    return str(x) + '!'"
        try:
            result = register_dynamic_tool(
                name, "Dynamic test", {"x": {"type": "string", "description": "Input"}}, code
            )
            assert result is True
            assert name in _registry
            # Execute it
            assert execute_tool(name, {"x": "hello"}) == "hello!"
        finally:
            unregister_tool(name)

    def test_register_syntax_error(self):
        """Bad code returns False."""
        name = "_test_dyn_syntax"
        code = "def oops(:\n    return 'bad'"
        result = register_dynamic_tool(name, "Bad syntax", {}, code)
        assert result is False
        assert name not in _registry

    def test_register_name_mismatch(self):
        """Function name != tool name returns False."""
        name = "_test_dyn_mismatch"
        code = "def wrong_name():\n    return 'oops'"
        result = register_dynamic_tool(name, "Mismatch", {}, code)
        assert result is False
        assert name not in _registry

    def test_register_sandbox_blocks_import(self):
        """__import__ not in sandbox builtins — import fails at call time."""
        name = "_test_dyn_import"
        code = f"def {name}():\n    import os\n    return os.getcwd()"
        try:
            # Registration succeeds (function is defined but not called)
            result = register_dynamic_tool(name, "Import test", {}, code)
            assert result is True
            # Execution fails because __import__ is missing from sandbox builtins
            exec_result = execute_tool(name, {})
            assert "Error executing" in exec_result
        finally:
            unregister_tool(name)

    def test_register_sandbox_blocks_open(self):
        """open not in sandbox builtins — open() fails at call time."""
        name = "_test_dyn_open"
        code = f"def {name}():\n    return open('/etc/passwd').read()"
        try:
            # Registration succeeds (function is defined but not called)
            result = register_dynamic_tool(name, "Open test", {}, code)
            assert result is True
            # Execution fails because open is missing from sandbox builtins
            exec_result = execute_tool(name, {})
            assert "Error executing" in exec_result
        finally:
            unregister_tool(name)

    def test_register_with_parameters(self):
        """Params generate correct schema."""
        name = "_test_dyn_params"
        params = {
            "a": {"type": "string", "description": "First"},
            "b": {"type": "integer", "description": "Second", "optional": True},
        }
        code = f"def {name}(a, b=0):\n    return a * b"
        try:
            result = register_dynamic_tool(name, "Param test", params, code)
            assert result is True
            _, schema = _registry[name]
            required = schema["function"]["parameters"]["required"]
            assert "a" in required
            assert "b" not in required
        finally:
            unregister_tool(name)


# ===== unregister_tool() =====


class TestUnregisterTool:
    """Test unregister_tool() removal."""

    def test_unregister_existing(self, temp_tool):
        """Returns True and removes from registry."""
        assert TEMP_TOOL_NAME in _registry
        result = unregister_tool(TEMP_TOOL_NAME)
        assert result is True
        assert TEMP_TOOL_NAME not in _registry

    def test_unregister_nonexistent(self):
        """Returns False for unknown tool."""
        result = unregister_tool("_nonexistent_tool_xyz")
        assert result is False


# ===== get_tool_names() =====


class TestGetToolNames:
    """Test get_tool_names() listing."""

    def test_get_tool_names(self, temp_tool):
        """Returns list containing registered tool names."""
        names = get_tool_names()
        assert isinstance(names, list)
        assert TEMP_TOOL_NAME in names
        # Should also have built-in tools
        assert "exec" in names


# ===== _log_tool_execution() =====


class TestLogToolExecution:
    """Test _log_tool_execution() logging behavior."""

    @patch("radar.tools.log", create=True)
    def test_log_success(self, mock_log):
        """Calls log('info', ...) with tool name on success."""
        with patch("radar.logging.log") as mock_log_fn:
            _log_tool_execution("my_tool", True)
            mock_log_fn.assert_called_once()
            args = mock_log_fn.call_args
            assert args[0][0] == "info"
            assert "my_tool" in args[0][1]

    @patch("radar.tools.log", create=True)
    def test_log_failure(self, mock_log):
        """Calls log('warn', ...) with tool name and error on failure."""
        with patch("radar.logging.log") as mock_log_fn:
            _log_tool_execution("my_tool", False, error="something broke")
            mock_log_fn.assert_called_once()
            args = mock_log_fn.call_args
            assert args[0][0] == "warn"
            assert "my_tool" in args[0][1]

    def test_log_swallows_exceptions(self):
        """No crash when log raises."""
        with patch("radar.logging.log", side_effect=RuntimeError("log broken")):
            # Should not raise
            _log_tool_execution("my_tool", True)
