"""Tests for tool auto-discovery and external tool loading."""

from pathlib import Path

import pytest

from radar.tools import (
    _registry,
    _static_tools,
    _external_tools,
    get_tool_names,
    is_dynamic_tool,
    load_external_tools,
    register_dynamic_tool,
    unregister_tool,
)


# ===== Built-in discovery =====


class TestBuiltinDiscovery:
    """Test that built-in tools are auto-discovered at import time."""

    def test_static_tools_populated(self):
        """_static_tools should be populated by _discover_tools() at import time."""
        assert len(_static_tools) > 0

    def test_known_tools_registered(self):
        """All known built-in tools should be registered."""
        expected = {
            "exec",
            "github",
            "list_directory",
            "notify",
            "pdf_extract",
            "read_file",
            "recall",
            "remember",
            "weather",
            "web_search",
            "write_file",
            "create_tool",
            "debug_tool",
            "rollback_tool",
            "suggest_personality_update",
            "analyze_feedback",
            "schedule_task",
            "list_scheduled_tasks",
            "cancel_task",
        }
        registered = set(get_tool_names())
        # All expected tools should be in the registry
        assert expected.issubset(registered), f"Missing tools: {expected - registered}"

    def test_static_tools_matches_registry(self):
        """_static_tools should contain all tools discovered from the package."""
        # Every tool in _static_tools should be in the registry
        for name in _static_tools:
            assert name in _registry, f"{name} in _static_tools but not in registry"

    def test_static_tools_are_not_dynamic(self):
        """Built-in tools should not be classified as dynamic."""
        for name in _static_tools:
            assert not is_dynamic_tool(name), f"{name} incorrectly classified as dynamic"


# ===== is_dynamic_tool =====


class TestIsDynamicTool:
    """Test is_dynamic_tool() classification."""

    def test_builtin_not_dynamic(self):
        assert not is_dynamic_tool("exec")
        assert not is_dynamic_tool("weather")
        assert not is_dynamic_tool("recall")

    def test_unregistered_not_dynamic(self):
        assert not is_dynamic_tool("nonexistent_tool_xyz")

    def test_dynamically_registered_is_dynamic(self):
        """A tool registered via register_dynamic_tool should be classified as dynamic."""
        name = "_test_dynamic_tool_abc"
        try:
            code = f"def {name}(): return 'test'"
            register_dynamic_tool(name, "test", {}, code)
            assert is_dynamic_tool(name)
        finally:
            unregister_tool(name)


# ===== External tool loading =====


class TestExternalToolLoading:
    """Test load_external_tools() for user-local tools."""

    def test_load_valid_tool(self, tmp_path):
        """A valid tool file in an external directory should register."""
        tool_file = tmp_path / "hello_tool.py"
        tool_file.write_text(
            'from radar.tools import tool\n\n'
            '@tool(name="hello_ext", description="Say hello", parameters={})\n'
            'def hello_ext() -> str:\n'
            '    return "Hello from external!"\n'
        )

        try:
            loaded = load_external_tools([str(tmp_path)])
            assert "hello_tool" in loaded
            assert "hello_ext" in _registry

            # Execute it
            func, _ = _registry["hello_ext"]
            assert func() == "Hello from external!"
        finally:
            unregister_tool("hello_ext")

    def test_skips_underscore_prefixed(self, tmp_path):
        """Files starting with _ should be skipped."""
        helper = tmp_path / "_helper.py"
        helper.write_text(
            'from radar.tools import tool\n\n'
            '@tool(name="_should_not_register", description="No", parameters={})\n'
            'def _should_not_register() -> str:\n'
            '    return "nope"\n'
        )

        loaded = load_external_tools([str(tmp_path)])
        assert len(loaded) == 0
        assert "_should_not_register" not in _registry

    def test_missing_directory_skipped(self, tmp_path):
        """Non-existent directories should be silently skipped."""
        fake_dir = tmp_path / "nonexistent"
        loaded = load_external_tools([str(fake_dir)])
        assert loaded == []

    def test_multiple_directories(self, tmp_path):
        """Tools from multiple directories should all be loaded."""
        dir_a = tmp_path / "a"
        dir_a.mkdir()
        dir_b = tmp_path / "b"
        dir_b.mkdir()

        (dir_a / "tool_a.py").write_text(
            'from radar.tools import tool\n\n'
            '@tool(name="ext_a", description="Tool A", parameters={})\n'
            'def ext_a() -> str:\n'
            '    return "A"\n'
        )
        (dir_b / "tool_b.py").write_text(
            'from radar.tools import tool\n\n'
            '@tool(name="ext_b", description="Tool B", parameters={})\n'
            'def ext_b() -> str:\n'
            '    return "B"\n'
        )

        try:
            loaded = load_external_tools([str(dir_a), str(dir_b)])
            assert "tool_a" in loaded
            assert "tool_b" in loaded
            assert "ext_a" in _registry
            assert "ext_b" in _registry
        finally:
            unregister_tool("ext_a")
            unregister_tool("ext_b")

    def test_empty_directory(self, tmp_path):
        """An empty directory should return no loaded tools."""
        loaded = load_external_tools([str(tmp_path)])
        assert loaded == []

    def test_external_tool_not_dynamic(self, tmp_path):
        """External tools tracked in _external_tools should not be classified as dynamic."""
        tool_file = tmp_path / "ext_check.py"
        tool_file.write_text(
            'from radar.tools import tool\n\n'
            '@tool(name="ext_check_tool", description="Check", parameters={})\n'
            'def ext_check_tool() -> str:\n'
            '    return "check"\n'
        )

        try:
            snapshot = set(_registry.keys())
            load_external_tools([str(tmp_path)])
            _external_tools.update(set(_registry.keys()) - snapshot - _static_tools)

            assert not is_dynamic_tool("ext_check_tool")
        finally:
            _external_tools.discard("ext_check_tool")
            unregister_tool("ext_check_tool")


# ===== Config integration =====


class TestToolsConfig:
    """Test tools configuration for extra_dirs."""

    def test_extra_dirs_default_empty(self):
        from radar.config import ToolsConfig

        tc = ToolsConfig()
        assert tc.extra_dirs == []

    def test_extra_dirs_from_dict(self):
        from radar.config import Config

        config = Config.from_dict(
            {"tools": {"extra_dirs": ["/tmp/my-tools", "~/custom-tools"]}}
        )
        assert config.tools.extra_dirs == ["/tmp/my-tools", "~/custom-tools"]

    def test_data_paths_tools_dir(self, isolated_data_dir):
        from radar.config import get_data_paths

        paths = get_data_paths()
        tools_dir = paths.tools
        assert tools_dir == isolated_data_dir / "tools"
        assert tools_dir.is_dir()
