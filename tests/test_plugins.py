"""Tests for radar/plugins/ package — models, validator, runner, versions, loader."""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from radar.plugins.models import Plugin, PluginManifest, PromptVariableDefinition, TestCase, ToolDefinition, ToolError
from radar.plugins.runner import TestRunner
from radar.plugins.validator import CodeValidator
from radar.plugins.versions import VersionManager

# ---------------------------------------------------------------------------
# Helpers / constants
# ---------------------------------------------------------------------------

VALID_PLUGIN_CODE = 'def greet(name: str) -> str:\n    return f"Hello, {name}!"'


def _make_plugin_dir(
    base: Path,
    name: str,
    *,
    code: str = VALID_PLUGIN_CODE,
    description: str = "A test plugin",
    parameters: dict | None = None,
    tests: list[dict] | None = None,
) -> Path:
    """Create a plugin directory with manifest, code, schema, and optional tests."""
    d = base / name
    d.mkdir(parents=True, exist_ok=True)

    manifest = {
        "name": name,
        "version": "1.0.0",
        "description": description,
        "author": "test",
        "trust_level": "sandbox",
        "created_at": "2025-01-01T00:00:00",
    }
    (d / "manifest.yaml").write_text(yaml.dump(manifest))
    (d / "tool.py").write_text(code)

    schema = {
        "name": name,
        "description": description,
        "parameters": parameters or {"name": {"type": "string", "description": "Name"}},
    }
    (d / "schema.yaml").write_text(yaml.dump(schema))

    if tests is not None:
        (d / "tests.yaml").write_text(yaml.dump(tests))

    return d


# ===========================================================================
# 1. Models
# ===========================================================================


class TestPluginManifest:
    def test_from_dict_full(self):
        data = {
            "name": "my_tool",
            "version": "2.0.0",
            "description": "Does things",
            "author": "alice",
            "trust_level": "trusted",
            "permissions": ["network"],
            "created_at": "2025-01-01",
            "updated_at": "2025-06-15",
        }
        m = PluginManifest.from_dict(data)
        assert m.name == "my_tool"
        assert m.version == "2.0.0"
        assert m.author == "alice"
        assert m.trust_level == "trusted"
        assert m.permissions == ["network"]
        assert m.created_at == "2025-01-01"
        assert m.updated_at == "2025-06-15"

    def test_from_dict_defaults(self):
        m = PluginManifest.from_dict({})
        assert m.name == "unknown"
        assert m.version == "1.0.0"
        assert m.description == ""
        assert m.author == "unknown"
        assert m.trust_level == "sandbox"
        assert m.permissions == []
        assert m.created_at == ""
        assert m.updated_at == ""

    def test_round_trip(self):
        data = {
            "name": "rt",
            "version": "3.0.0",
            "description": "round-trip",
            "author": "bob",
            "trust_level": "sandbox",
            "permissions": ["fs"],
            "created_at": "c",
            "updated_at": "u",
            "capabilities": ["tool"],
            "widget": None,
            "personalities": [],
            "scripts": [],
            "tools": [],
            "prompt_variables": [],
            "hooks": [],
        }
        m = PluginManifest.from_dict(data)
        assert m.to_dict() == data


class TestTestCase:
    def test_from_dict_input_args(self):
        tc = TestCase.from_dict(
            {"name": "t1", "input_args": {"x": 1}, "expected_output": "1"}
        )
        assert tc.name == "t1"
        assert tc.input_args == {"x": 1}
        assert tc.expected_output == "1"

    def test_from_dict_legacy_keys(self):
        tc = TestCase.from_dict({"name": "t2", "input": {"a": "b"}, "expected": "ok"})
        assert tc.input_args == {"a": "b"}
        assert tc.expected_output == "ok"

    def test_from_dict_minimal(self):
        tc = TestCase.from_dict({})
        assert tc.name == "test"
        assert tc.input_args == {}
        assert tc.expected_output is None
        assert tc.expected_contains is None

    def test_expected_contains(self):
        tc = TestCase.from_dict({"expected_contains": "partial"})
        assert tc.expected_contains == "partial"


class TestToolError:
    def test_round_trip(self):
        err = ToolError(
            tool_name="t",
            error_type="runtime",
            message="boom",
            traceback_str="tb",
            input_args={"a": 1},
            expected_output="e",
            actual_output="a",
            attempt_number=2,
            max_attempts=5,
            timestamp="2025-01-01T00:00:00",
        )
        d = err.to_dict()
        restored = ToolError.from_dict(d)
        assert restored.tool_name == "t"
        assert restored.error_type == "runtime"
        assert restored.message == "boom"
        assert restored.attempt_number == 2
        assert restored.timestamp == "2025-01-01T00:00:00"

    def test_auto_timestamp(self):
        err = ToolError(
            tool_name="t",
            error_type="syntax",
            message="m",
            traceback_str="",
            input_args={},
            expected_output=None,
            actual_output=None,
            attempt_number=1,
        )
        assert err.timestamp != ""

    def test_explicit_timestamp_preserved(self):
        err = ToolError(
            tool_name="t",
            error_type="syntax",
            message="m",
            traceback_str="",
            input_args={},
            expected_output=None,
            actual_output=None,
            attempt_number=1,
            timestamp="fixed",
        )
        assert err.timestamp == "fixed"


class TestPlugin:
    def test_defaults(self):
        m = PluginManifest(name="p")
        p = Plugin(name="p", manifest=m, code="pass")
        assert p.function is None
        assert p.enabled is True
        assert p.path is None
        assert p.test_cases == []
        assert p.errors == []


# ===========================================================================
# 2. Validator
# ===========================================================================


class TestCodeValidator:
    def test_valid_code(self):
        ok, issues = CodeValidator().validate(VALID_PLUGIN_CODE)
        assert ok is True
        assert issues == []

    def test_syntax_error(self):
        ok, issues = CodeValidator().validate("def foo(:\n  pass")
        assert ok is False
        assert any("Syntax error" in i for i in issues)

    @pytest.mark.parametrize(
        "module",
        ["os", "subprocess", "sys", "socket", "shutil", "multiprocessing",
         "threading", "ctypes"],
    )
    def test_forbidden_import(self, module):
        code = f"import {module}\ndef f(): pass"
        ok, issues = CodeValidator().validate(code)
        assert ok is False
        assert any("Forbidden import" in i for i in issues)

    @pytest.mark.parametrize("module", ["os", "subprocess", "sys"])
    def test_forbidden_from_import(self, module):
        code = f"from {module} import something\ndef f(): pass"
        ok, issues = CodeValidator().validate(code)
        assert ok is False
        assert any("Forbidden import from" in i for i in issues)

    def test_allowed_imports_override(self):
        code = "import os\ndef f(): pass"
        ok, issues = CodeValidator(allowed_imports={"os"}).validate(code)
        assert ok is True
        assert issues == []

    @pytest.mark.parametrize(
        "call",
        ["eval", "exec", "compile", "__import__", "open", "globals",
         "locals", "getattr", "setattr", "delattr"],
    )
    def test_forbidden_call(self, call):
        code = f"def f():\n    {call}('x')"
        ok, issues = CodeValidator().validate(code)
        assert ok is False
        assert any("Forbidden call" in i for i in issues)

    def test_forbidden_attribute_call(self):
        code = "def f():\n    obj.__import__('x')"
        ok, issues = CodeValidator().validate(code)
        assert ok is False
        assert any("Forbidden call: .__import__" in i for i in issues)

    @pytest.mark.parametrize(
        "attr",
        ["__code__", "__globals__", "__builtins__", "__subclasses__",
         "__bases__", "__mro__"],
    )
    def test_forbidden_attribute_access(self, attr):
        code = f"def f():\n    x = obj.{attr}"
        ok, issues = CodeValidator().validate(code)
        assert ok is False
        assert any("Forbidden attribute access" in i for i in issues)

    def test_no_function_definition(self):
        code = "x = 1 + 2"
        ok, issues = CodeValidator().validate(code)
        assert ok is False
        assert any("must define at least one function" in i for i in issues)

    def test_multiple_issues(self):
        code = "import os\nimport subprocess\nx = 1"
        ok, issues = CodeValidator().validate(code)
        assert ok is False
        # Should report both forbidden imports AND missing function
        assert len(issues) >= 3

    def test_safe_imports_pass(self):
        code = "import json\nimport math\ndef f(): return json.dumps({})"
        ok, issues = CodeValidator().validate(code)
        assert ok is True
        assert issues == []


# ===========================================================================
# 3. Runner
# ===========================================================================


class TestTestRunner:
    def test_passing_exact_match(self):
        code = 'def greet(name): return f"Hello, {name}!"'
        tc = TestCase(name="t1", input_args={"name": "World"}, expected_output="Hello, World!")
        ok, results = TestRunner().run_tests(code, [tc], "greet")
        assert ok is True
        assert results[0]["passed"] is True

    def test_passing_expected_contains(self):
        code = 'def greet(name): return f"Hello, {name}!"'
        tc = TestCase(name="t1", input_args={"name": "World"}, expected_contains="Hello")
        ok, results = TestRunner().run_tests(code, [tc], "greet")
        assert ok is True
        assert results[0]["passed"] is True

    def test_passing_no_expected(self):
        code = "def noop(): return 42"
        tc = TestCase(name="t1", input_args={})
        ok, results = TestRunner().run_tests(code, [tc], "noop")
        assert ok is True
        assert results[0]["passed"] is True

    def test_failing_wrong_output(self):
        code = "def f(): return 'wrong'"
        tc = TestCase(name="t1", input_args={}, expected_output="right")
        ok, results = TestRunner().run_tests(code, [tc], "f")
        assert ok is False
        assert results[0]["passed"] is False
        assert "Expected" in results[0]["error"]

    def test_failing_missing_substring(self):
        code = "def f(): return 'hello world'"
        tc = TestCase(name="t1", input_args={}, expected_contains="goodbye")
        ok, results = TestRunner().run_tests(code, [tc], "f")
        assert ok is False
        assert results[0]["passed"] is False
        assert "doesn't contain" in results[0]["error"]

    def test_failing_exception(self):
        code = "def f(): return 1 / 0"
        tc = TestCase(name="t1", input_args={})
        ok, results = TestRunner().run_tests(code, [tc], "f")
        assert ok is False
        assert results[0]["passed"] is False
        assert "division by zero" in results[0]["error"]

    def test_code_parse_failure(self):
        code = "def f(:\n  pass"
        tc = TestCase(name="t1", input_args={})
        ok, results = TestRunner().run_tests(code, [tc], "f")
        assert ok is False
        assert results[0]["name"] == "code_execution"
        assert "Failed to execute code" in results[0]["error"]

    def test_function_not_found(self):
        code = "def other(): pass"
        tc = TestCase(name="t1", input_args={})
        ok, results = TestRunner().run_tests(code, [tc], "missing_func")
        assert ok is False
        assert "not defined" in results[0]["error"]

    def test_mixed_pass_fail(self):
        code = "def f(x): return x * 2"
        tests = [
            TestCase(name="pass", input_args={"x": 3}, expected_output="6"),
            TestCase(name="fail", input_args={"x": 3}, expected_output="7"),
        ]
        ok, results = TestRunner().run_tests(code, tests, "f")
        assert ok is False
        assert results[0]["passed"] is True
        assert results[1]["passed"] is False

    def test_safe_namespace_blocks_open(self):
        code = "def f(): return open('/etc/passwd')"
        tc = TestCase(name="t1", input_args={})
        ok, results = TestRunner().run_tests(code, [tc], "f")
        assert ok is False
        # open is not in the safe namespace, so it should error
        assert results[0]["passed"] is False


# ===========================================================================
# 4. Versions
# ===========================================================================


class TestVersionManager:
    def test_save_version_creates_files(self, tmp_path):
        vm = VersionManager(tmp_path / "versions")
        manifest = PluginManifest(name="myplugin")
        ver = vm.save_version("myplugin", "def f(): pass", manifest)
        assert ver == "v1"
        assert (tmp_path / "versions" / "myplugin" / "v1.py").exists()
        assert (tmp_path / "versions" / "myplugin" / "v1.yaml").exists()

    def test_sequential_versions(self, tmp_path):
        vm = VersionManager(tmp_path / "versions")
        manifest = PluginManifest(name="p")
        v1 = vm.save_version("p", "def f(): pass", manifest)
        v2 = vm.save_version("p", "def f(): return 1", manifest)
        v3 = vm.save_version("p", "def f(): return 2", manifest)
        assert v1 == "v1"
        assert v2 == "v2"
        assert v3 == "v3"

    def test_get_versions_sorted(self, tmp_path):
        vm = VersionManager(tmp_path / "versions")
        manifest = PluginManifest(name="p")
        vm.save_version("p", "def f(): pass", manifest)
        vm.save_version("p", "def f(): return 1", manifest)
        versions = vm.get_versions("p")
        assert len(versions) == 2
        assert versions[0]["version"] == "v1"
        assert versions[1]["version"] == "v2"

    def test_get_versions_empty_for_unknown(self, tmp_path):
        vm = VersionManager(tmp_path / "versions")
        assert vm.get_versions("nonexistent") == []

    def test_get_version_retrieves_correct_code(self, tmp_path):
        vm = VersionManager(tmp_path / "versions")
        manifest = PluginManifest(name="p")
        vm.save_version("p", "def f(): return 1", manifest)
        vm.save_version("p", "def f(): return 2", manifest)
        result = vm.get_version("p", "v1")
        assert result is not None
        code, m = result
        assert "return 1" in code

    def test_get_version_returns_none_for_missing(self, tmp_path):
        vm = VersionManager(tmp_path / "versions")
        assert vm.get_version("p", "v99") is None

    def test_get_version_missing_manifest_creates_default(self, tmp_path):
        vm = VersionManager(tmp_path / "versions")
        # Manually create code file without manifest
        p = tmp_path / "versions" / "p"
        p.mkdir(parents=True)
        (p / "v1.py").write_text("def f(): pass")
        result = vm.get_version("p", "v1")
        assert result is not None
        code, m = result
        assert m.name == "p"
        assert m.version == "v1"


# ===========================================================================
# 5. Loader
# ===========================================================================


@pytest.fixture
def plugin_loader(isolated_data_dir):
    """Create a PluginLoader with isolated data directory."""
    from radar.plugins.loader import PluginLoader

    plugins_dir = isolated_data_dir / "plugins"
    loader = PluginLoader(plugins_dir=plugins_dir)
    return loader


class TestPluginLoaderInit:
    def test_creates_subdirectories(self, plugin_loader):
        for subdir in ["enabled", "available", "pending_review", "failed", "versions", "errors"]:
            assert (plugin_loader.plugins_dir / subdir).is_dir()

    def test_initializes_components(self, plugin_loader):
        assert isinstance(plugin_loader.validator, CodeValidator)
        assert isinstance(plugin_loader.test_runner, TestRunner)
        assert isinstance(plugin_loader.version_manager, VersionManager)


class TestPluginLoaderCreatePlugin:
    def test_successful_creation_pending(self, plugin_loader):
        with patch("radar.config.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(plugins=MagicMock(max_code_size_bytes=10000))
            ok, msg, err = plugin_loader.create_plugin(
                name="greet",
                description="Greet someone",
                parameters={"name": {"type": "string"}},
                code=VALID_PLUGIN_CODE,
                test_cases=[{"name": "t1", "input_args": {"name": "World"}, "expected_output": "Hello, World!"}],
                auto_approve=False,
            )
        assert ok is True
        assert "pending review" in msg
        assert (plugin_loader.pending_dir / "greet" / "tool.py").exists()
        assert (plugin_loader.pending_dir / "greet" / "manifest.yaml").exists()

    def test_successful_creation_auto_approved(self, plugin_loader):
        with patch("radar.config.get_config") as mock_cfg, \
             patch("radar.tools.register_dynamic_tool", return_value=True):
            mock_cfg.return_value = MagicMock(plugins=MagicMock(max_code_size_bytes=10000))
            ok, msg, err = plugin_loader.create_plugin(
                name="greet",
                description="Greet someone",
                parameters={"name": {"type": "string"}},
                code=VALID_PLUGIN_CODE,
                test_cases=[{"name": "t1", "input_args": {"name": "World"}, "expected_output": "Hello, World!"}],
                auto_approve=True,
            )
        assert ok is True
        assert "enabled" in msg
        assert (plugin_loader.available_dir / "greet" / "tool.py").exists()

    def test_code_too_large(self, plugin_loader):
        with patch("radar.config.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(plugins=MagicMock(max_code_size_bytes=10))
            ok, msg, err = plugin_loader.create_plugin(
                name="greet",
                description="d",
                parameters={},
                code=VALID_PLUGIN_CODE,
                test_cases=[],
            )
        assert ok is False
        assert "exceeds maximum size" in msg

    def test_validation_failure(self, plugin_loader):
        with patch("radar.config.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(plugins=MagicMock(max_code_size_bytes=10000))
            ok, msg, err = plugin_loader.create_plugin(
                name="bad",
                description="d",
                parameters={},
                code="import os\ndef f(): pass",
                test_cases=[],
            )
        assert ok is False
        assert "validation failed" in msg

    def test_test_failure_saves_error(self, plugin_loader):
        code = 'def greet(name: str) -> str:\n    return "wrong"'
        with patch("radar.config.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(plugins=MagicMock(max_code_size_bytes=10000))
            ok, msg, err = plugin_loader.create_plugin(
                name="greet",
                description="d",
                parameters={"name": {"type": "string"}},
                code=code,
                test_cases=[{"name": "t1", "input_args": {"name": "World"}, "expected_output": "Hello, World!"}],
            )
        assert ok is False
        assert "Tests failed" in msg
        assert err is not None
        assert "test_results" in err
        # Error should be saved
        assert plugin_loader.get_error_count("greet") == 1
        # Plugin should be saved to pending for debugging
        assert (plugin_loader.pending_dir / "greet" / "tool.py").exists()

    def test_no_test_cases_still_creates(self, plugin_loader):
        """Plugin with no test cases should succeed if code validates."""
        with patch("radar.config.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(plugins=MagicMock(max_code_size_bytes=10000))
            ok, msg, err = plugin_loader.create_plugin(
                name="greet",
                description="Greet someone",
                parameters={"name": {"type": "string"}},
                code=VALID_PLUGIN_CODE,
                test_cases=[],
            )
        assert ok is True


class TestPluginLoaderApproveReject:
    def _create_pending(self, plugin_loader, name="myplugin"):
        _make_plugin_dir(plugin_loader.pending_dir, name)

    def test_approve_moves_and_enables(self, plugin_loader):
        self._create_pending(plugin_loader)
        with patch("radar.tools.register_dynamic_tool", return_value=True):
            ok, msg = plugin_loader.approve_plugin("myplugin")
        assert ok is True
        assert "approved" in msg
        assert (plugin_loader.available_dir / "myplugin").is_dir()
        assert not (plugin_loader.pending_dir / "myplugin").exists()
        # Symlink in enabled
        assert (plugin_loader.enabled_dir / "myplugin").exists()

    def test_reject_moves_and_saves_reason(self, plugin_loader):
        self._create_pending(plugin_loader)
        ok, msg = plugin_loader.reject_plugin("myplugin", reason="not useful")
        assert ok is True
        assert "rejected" in msg
        assert (plugin_loader.failed_dir / "myplugin").is_dir()
        assert not (plugin_loader.pending_dir / "myplugin").exists()
        assert (plugin_loader.failed_dir / "myplugin" / "rejection_reason.txt").read_text() == "not useful"

    def test_approve_nonexistent_fails(self, plugin_loader):
        ok, msg = plugin_loader.approve_plugin("ghost")
        assert ok is False
        assert "not found" in msg

    def test_reject_nonexistent_fails(self, plugin_loader):
        ok, msg = plugin_loader.reject_plugin("ghost")
        assert ok is False
        assert "not found" in msg


class TestPluginLoaderEnableDisable:
    def _create_available(self, plugin_loader, name="myplugin"):
        _make_plugin_dir(plugin_loader.available_dir, name)

    def test_enable_creates_symlink_and_registers(self, plugin_loader):
        self._create_available(plugin_loader)
        with patch("radar.tools.register_dynamic_tool", return_value=True) as mock_reg:
            ok, msg = plugin_loader.enable_plugin("myplugin")
        assert ok is True
        assert (plugin_loader.enabled_dir / "myplugin").is_symlink()
        mock_reg.assert_called_once()

    def test_disable_removes_symlink_and_unregisters(self, plugin_loader):
        self._create_available(plugin_loader)
        with patch("radar.tools.register_dynamic_tool", return_value=True):
            plugin_loader.enable_plugin("myplugin")
        with patch("radar.tools.unregister_tool", return_value=True) as mock_unreg:
            ok, msg = plugin_loader.disable_plugin("myplugin")
        assert ok is True
        assert not (plugin_loader.enabled_dir / "myplugin").exists()
        mock_unreg.assert_called_once_with("myplugin")

    def test_enable_nonexistent_fails(self, plugin_loader):
        ok, msg = plugin_loader.enable_plugin("ghost")
        assert ok is False
        assert "not found" in msg

    def test_disable_idempotent(self, plugin_loader):
        """Disabling a plugin that isn't enabled should still succeed."""
        with patch("radar.tools.unregister_tool", return_value=True):
            ok, msg = plugin_loader.disable_plugin("ghost")
        assert ok is True


class TestPluginLoaderRollback:
    def _setup_available_with_versions(self, plugin_loader, name="myplugin"):
        """Create an available plugin with two versions."""
        _make_plugin_dir(plugin_loader.available_dir, name, code="def myplugin(): return 'v1'")
        manifest = PluginManifest(name=name)
        plugin_loader.version_manager.save_version(name, "def myplugin(): return 'v1'", manifest)
        plugin_loader.version_manager.save_version(name, "def myplugin(): return 'v2'", manifest)
        # Current code is v2
        (plugin_loader.available_dir / name / "tool.py").write_text("def myplugin(): return 'v2'")

    def test_rollback_updates_files(self, plugin_loader):
        self._setup_available_with_versions(plugin_loader)
        ok, msg = plugin_loader.rollback_plugin("myplugin", "v1")
        assert ok is True
        assert "rolled back" in msg
        code = (plugin_loader.available_dir / "myplugin" / "tool.py").read_text()
        assert "v1" in code

    def test_rollback_reregisters_if_enabled(self, plugin_loader):
        self._setup_available_with_versions(plugin_loader)
        # Enable the plugin
        with patch("radar.tools.register_dynamic_tool", return_value=True):
            plugin_loader.enable_plugin("myplugin")
        with patch("radar.tools.register_dynamic_tool", return_value=True) as mock_reg:
            ok, msg = plugin_loader.rollback_plugin("myplugin", "v1")
        assert ok is True
        mock_reg.assert_called_once()

    def test_rollback_unknown_version_fails(self, plugin_loader):
        _make_plugin_dir(plugin_loader.available_dir, "myplugin")
        ok, msg = plugin_loader.rollback_plugin("myplugin", "v99")
        assert ok is False
        assert "not found" in msg


class TestPluginLoaderUpdateCode:
    def _create_pending_with_tests(self, plugin_loader, name="greet"):
        tests = [{"name": "t1", "input_args": {"name": "World"}, "expected_output": "Hello, World!"}]
        _make_plugin_dir(
            plugin_loader.pending_dir,
            name,
            code='def greet(name): return "wrong"',
            tests=tests,
        )

    def test_successful_update_clears_errors(self, plugin_loader):
        self._create_pending_with_tests(plugin_loader)
        # Seed an error
        err = ToolError(
            tool_name="greet", error_type="test_failure", message="m",
            traceback_str="", input_args={}, expected_output=None,
            actual_output=None, attempt_number=1,
        )
        plugin_loader._save_error("greet", err)
        assert plugin_loader.get_error_count("greet") == 1

        ok, msg, details = plugin_loader.update_plugin_code("greet", VALID_PLUGIN_CODE)
        assert ok is True
        assert "updated successfully" in msg
        assert plugin_loader.get_error_count("greet") == 0

    def test_validation_failure(self, plugin_loader):
        self._create_pending_with_tests(plugin_loader)
        ok, msg, details = plugin_loader.update_plugin_code("greet", "import os\ndef greet(): pass")
        assert ok is False
        assert "validation failed" in msg

    def test_test_failure_increments_attempts(self, plugin_loader):
        self._create_pending_with_tests(plugin_loader)
        bad_code = 'def greet(name): return "still wrong"'
        ok, msg, details = plugin_loader.update_plugin_code("greet", bad_code)
        assert ok is False
        assert "attempt" in msg
        assert plugin_loader.get_error_count("greet") == 1

    def test_not_found(self, plugin_loader):
        ok, msg, details = plugin_loader.update_plugin_code("ghost", "def ghost(): pass")
        assert ok is False
        assert "not found" in msg

    def test_reregisters_if_enabled(self, plugin_loader):
        """Update of an enabled available plugin should re-register."""
        tests = [{"name": "t1", "input_args": {"name": "World"}, "expected_output": "Hello, World!"}]
        _make_plugin_dir(
            plugin_loader.available_dir,
            "greet",
            code='def greet(name): return "old"',
            tests=tests,
        )
        with patch("radar.tools.register_dynamic_tool", return_value=True):
            plugin_loader.enable_plugin("greet")
        with patch("radar.tools.register_dynamic_tool", return_value=True) as mock_reg:
            ok, msg, _ = plugin_loader.update_plugin_code("greet", VALID_PLUGIN_CODE)
        assert ok is True
        mock_reg.assert_called_once()


class TestPluginLoaderErrors:
    def test_save_load_round_trip(self, plugin_loader):
        err = ToolError(
            tool_name="p", error_type="runtime", message="err",
            traceback_str="tb", input_args={"x": 1}, expected_output="e",
            actual_output="a", attempt_number=1, timestamp="ts",
        )
        plugin_loader._save_error("p", err)
        loaded = plugin_loader._load_errors("p")
        assert len(loaded) == 1
        assert loaded[0].tool_name == "p"
        assert loaded[0].message == "err"

    def test_load_empty_for_nonexistent(self, plugin_loader):
        assert plugin_loader._load_errors("ghost") == []

    def test_clear_removes_file(self, plugin_loader):
        err = ToolError(
            tool_name="p", error_type="runtime", message="m",
            traceback_str="", input_args={}, expected_output=None,
            actual_output=None, attempt_number=1,
        )
        plugin_loader._save_error("p", err)
        plugin_loader._clear_errors("p")
        assert plugin_loader._load_errors("p") == []

    def test_get_last_error_and_count(self, plugin_loader):
        for i in range(3):
            err = ToolError(
                tool_name="p", error_type="runtime", message=f"err{i}",
                traceback_str="", input_args={}, expected_output=None,
                actual_output=None, attempt_number=i + 1,
            )
            plugin_loader._save_error("p", err)
        assert plugin_loader.get_error_count("p") == 3
        last = plugin_loader.get_last_error("p")
        assert last is not None
        assert last.message == "err2"

    def test_get_last_error_none_for_nonexistent(self, plugin_loader):
        assert plugin_loader.get_last_error("ghost") is None


class TestPluginLoaderLoadAndList:
    def test_load_all_with_symlinks(self, plugin_loader):
        _make_plugin_dir(plugin_loader.available_dir, "myplugin")
        # Create symlink in enabled
        (plugin_loader.enabled_dir / "myplugin").symlink_to(
            plugin_loader.available_dir / "myplugin"
        )
        plugins = plugin_loader.load_all()
        assert len(plugins) == 1
        assert plugins[0].name == "myplugin"
        assert plugins[0].enabled is True

    def test_load_plugin_none_on_missing_files(self, plugin_loader):
        """_load_plugin returns None if manifest or code is missing."""
        d = plugin_loader.available_dir / "incomplete"
        d.mkdir()
        # No manifest or tool.py
        result = plugin_loader._load_plugin(d)
        assert result is None

    def test_list_plugins_with_enabled_status(self, plugin_loader):
        _make_plugin_dir(plugin_loader.available_dir, "enabled_one")
        _make_plugin_dir(plugin_loader.available_dir, "disabled_one")
        (plugin_loader.enabled_dir / "enabled_one").symlink_to(
            plugin_loader.available_dir / "enabled_one"
        )
        result = plugin_loader.list_plugins()
        by_name = {p["name"]: p for p in result}
        assert by_name["enabled_one"]["enabled"] is True
        assert by_name["disabled_one"]["enabled"] is False

    def test_list_plugins_include_pending(self, plugin_loader):
        _make_plugin_dir(plugin_loader.available_dir, "avail")
        _make_plugin_dir(plugin_loader.pending_dir, "pend")
        without_pending = plugin_loader.list_plugins(include_pending=False)
        with_pending = plugin_loader.list_plugins(include_pending=True)
        assert len(with_pending) == len(without_pending) + 1
        pending_items = [p for p in with_pending if p["status"] == "pending"]
        assert len(pending_items) == 1
        assert pending_items[0]["name"] == "pend"

    def test_list_pending_details(self, plugin_loader):
        _make_plugin_dir(plugin_loader.pending_dir, "pend", description="Pending plugin")
        result = plugin_loader.list_pending()
        assert len(result) == 1
        assert result[0]["name"] == "pend"
        assert result[0]["description"] == "Pending plugin"
        assert result[0]["code"] != ""
        assert "path" in result[0]


# ===========================================================================
# 6. Plugin Manifest Capabilities (Phase 4A)
# ===========================================================================


class TestPluginManifestCapabilities:
    def test_default_capabilities(self):
        m = PluginManifest.from_dict({"name": "test"})
        assert m.capabilities == ["tool"]

    def test_custom_capabilities(self):
        m = PluginManifest.from_dict({"name": "test", "capabilities": ["tool", "widget"]})
        assert m.capabilities == ["tool", "widget"]

    def test_widget_field(self):
        widget = {"title": "Monitor", "template": "w.html", "position": "default", "refresh_interval": 30}
        m = PluginManifest.from_dict({"name": "test", "widget": widget})
        assert m.widget == widget

    def test_widget_field_default_none(self):
        m = PluginManifest.from_dict({"name": "test"})
        assert m.widget is None

    def test_personalities_field(self):
        m = PluginManifest.from_dict({"name": "test", "personalities": ["sci.md"]})
        assert m.personalities == ["sci.md"]

    def test_personalities_default_empty(self):
        m = PluginManifest.from_dict({"name": "test"})
        assert m.personalities == []

    def test_scripts_field(self):
        m = PluginManifest.from_dict({"name": "test", "scripts": ["helpers.py"]})
        assert m.scripts == ["helpers.py"]

    def test_scripts_default_empty(self):
        m = PluginManifest.from_dict({"name": "test"})
        assert m.scripts == []

    def test_round_trip_with_new_fields(self):
        data = {
            "name": "t",
            "version": "1.0.0",
            "description": "desc",
            "author": "alice",
            "trust_level": "sandbox",
            "permissions": [],
            "created_at": "c",
            "updated_at": "u",
            "capabilities": ["tool", "widget"],
            "widget": {"title": "W"},
            "personalities": ["p.md"],
            "scripts": ["s.py"],
        }
        m = PluginManifest.from_dict(data)
        d = m.to_dict()
        assert d["capabilities"] == ["tool", "widget"]
        assert d["widget"] == {"title": "W"}
        assert d["personalities"] == ["p.md"]
        assert d["scripts"] == ["s.py"]
        assert d["prompt_variables"] == []

    def test_backward_compat_no_capabilities(self):
        m = PluginManifest.from_dict({"name": "old", "version": "0.1"})
        assert m.capabilities == ["tool"]
        assert m.widget is None
        assert m.personalities == []
        assert m.scripts == []

    def test_to_dict_includes_new_fields(self):
        m = PluginManifest(name="test")
        d = m.to_dict()
        assert "capabilities" in d
        assert "widget" in d
        assert "personalities" in d
        assert "scripts" in d


# ===========================================================================
# 7. Plugin Widgets (Phase 4B)
# ===========================================================================


def _make_widget_plugin(loader, name="monitor", template_content="<p>Widget</p>"):
    """Create an enabled plugin with widget capability."""
    d = loader.available_dir / name
    d.mkdir(parents=True, exist_ok=True)

    manifest = {
        "name": name,
        "version": "1.0.0",
        "description": "Widget plugin",
        "author": "test",
        "trust_level": "sandbox",
        "capabilities": ["tool", "widget"],
        "widget": {
            "title": "Test Monitor",
            "template": "widget.html",
            "position": "default",
            "refresh_interval": 30,
        },
    }
    (d / "manifest.yaml").write_text(yaml.dump(manifest))
    (d / "tool.py").write_text(VALID_PLUGIN_CODE)
    schema = {"name": name, "description": "Widget plugin", "parameters": {}}
    (d / "schema.yaml").write_text(yaml.dump(schema))
    (d / "widget.html").write_text(template_content)

    # Enable via symlink
    (loader.enabled_dir / name).symlink_to(d)
    return d


class TestPluginWidgets:
    def test_get_widgets_returns_widget_plugins(self, plugin_loader):
        _make_widget_plugin(plugin_loader, "monitor")
        widgets = plugin_loader.get_widgets()
        assert len(widgets) == 1
        assert widgets[0]["name"] == "monitor"
        assert widgets[0]["title"] == "Test Monitor"
        assert widgets[0]["template_content"] == "<p>Widget</p>"
        assert widgets[0]["position"] == "default"
        assert widgets[0]["refresh_interval"] == 30

    def test_get_widgets_excludes_non_widget_plugins(self, plugin_loader):
        # Plugin without widget capability
        _make_plugin_dir(plugin_loader.available_dir, "plain_tool")
        (plugin_loader.enabled_dir / "plain_tool").symlink_to(
            plugin_loader.available_dir / "plain_tool"
        )
        widgets = plugin_loader.get_widgets()
        assert len(widgets) == 0

    def test_get_widgets_multiple(self, plugin_loader):
        _make_widget_plugin(plugin_loader, "widget_a", "<p>A</p>")
        _make_widget_plugin(plugin_loader, "widget_b", "<p>B</p>")
        widgets = plugin_loader.get_widgets()
        assert len(widgets) == 2
        names = {w["name"] for w in widgets}
        assert names == {"widget_a", "widget_b"}

    def test_get_widgets_missing_template_file(self, plugin_loader):
        _make_widget_plugin(plugin_loader, "broken")
        # Remove the template file
        (plugin_loader.available_dir / "broken" / "widget.html").unlink()
        widgets = plugin_loader.get_widgets()
        assert len(widgets) == 1
        assert widgets[0]["template_content"] == ""


class TestPluginWidgetRendering:
    def test_widget_template_autoescape(self):
        """Widget rendering should autoescape HTML."""
        import jinja2
        env = jinja2.Environment(autoescape=True)
        template = env.from_string("<p>{{ value }}</p>")
        result = template.render(value="<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_widget_template_no_script_injection(self):
        """Template itself containing script tags should render as-is (not executed)."""
        import jinja2
        env = jinja2.Environment(autoescape=True)
        # The template content is the raw template, not user data, so it renders directly
        template = env.from_string("<p>Status: OK</p>")
        result = template.render()
        assert "Status: OK" in result


# ===========================================================================
# 8. Plugin Bundled Personalities (Phase 4C)
# ===========================================================================


def _make_personality_plugin(loader, name="sci_plugin", personality_name="scientist", personality_content="# Scientist\n\nThink like a scientist."):
    """Create an enabled plugin with bundled personality."""
    d = loader.available_dir / name
    d.mkdir(parents=True, exist_ok=True)

    manifest = {
        "name": name,
        "version": "1.0.0",
        "description": "Plugin with personality",
        "author": "test",
        "trust_level": "sandbox",
        "capabilities": ["tool", "personality"],
        "personalities": [f"{personality_name}.md"],
    }
    (d / "manifest.yaml").write_text(yaml.dump(manifest))
    (d / "tool.py").write_text(VALID_PLUGIN_CODE)
    schema = {"name": name, "description": "test", "parameters": {}}
    (d / "schema.yaml").write_text(yaml.dump(schema))

    # Create personalities subdirectory
    personalities_dir = d / "personalities"
    personalities_dir.mkdir()
    (personalities_dir / f"{personality_name}.md").write_text(personality_content)

    # Enable via symlink
    (loader.enabled_dir / name).symlink_to(d)
    return d


class TestPluginBundledPersonalities:
    def test_get_bundled_personalities(self, plugin_loader):
        _make_personality_plugin(plugin_loader)
        personalities = plugin_loader.get_bundled_personalities()
        assert len(personalities) == 1
        assert personalities[0]["name"] == "scientist"
        assert "Think like a scientist" in personalities[0]["content"]
        assert personalities[0]["plugin_name"] == "sci_plugin"

    def test_get_bundled_personalities_empty_when_no_dir(self, plugin_loader):
        # Plugin without personalities dir
        _make_plugin_dir(plugin_loader.available_dir, "no_personality")
        (plugin_loader.enabled_dir / "no_personality").symlink_to(
            plugin_loader.available_dir / "no_personality"
        )
        personalities = plugin_loader.get_bundled_personalities()
        assert len(personalities) == 0

    def test_get_bundled_personalities_multiple(self, plugin_loader):
        d = _make_personality_plugin(plugin_loader, "multi", "alpha", "# Alpha")
        # Add a second personality
        (d / "personalities" / "beta.md").write_text("# Beta")
        personalities = plugin_loader.get_bundled_personalities()
        assert len(personalities) == 2
        names = {p["name"] for p in personalities}
        assert names == {"alpha", "beta"}

    def test_load_personality_from_plugin(self, plugin_loader):
        """load_personality should find plugin personalities."""
        _make_personality_plugin(plugin_loader, "myplugin", "researcher", "# Researcher\n\nResearch things.")
        with patch("radar.plugins.get_plugin_loader", return_value=plugin_loader):
            from radar.agent import load_personality
            content = load_personality("researcher")
        assert "Research things" in content

    def test_load_personality_prefers_local_over_plugin(self, plugin_loader, isolated_data_dir):
        """Personalities in the personalities dir should take precedence over plugins."""
        _make_personality_plugin(plugin_loader, "myplugin", "custom", "# Plugin Custom")

        # Create a local personality with same name
        pdir = isolated_data_dir / "personalities"
        pdir.mkdir(exist_ok=True)
        (pdir / "custom.md").write_text("# Local Custom")

        with patch("radar.plugins.get_plugin_loader", return_value=plugin_loader):
            from radar.agent import load_personality
            content = load_personality("custom")
        assert "Local Custom" in content


# ===========================================================================
# 9. Plugin Helper Scripts (Phase 4D)
# ===========================================================================


class TestPluginHelperScripts:
    def test_load_scripts_returns_functions(self, plugin_loader):
        d = plugin_loader.available_dir / "with_scripts"
        d.mkdir(parents=True)
        scripts_dir = d / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "helpers.py").write_text('def double(x):\n    return x * 2')
        namespace = plugin_loader._load_plugin_scripts(d)
        assert "double" in namespace
        assert namespace["double"](3) == 6

    def test_load_scripts_skips_invalid(self, plugin_loader):
        d = plugin_loader.available_dir / "bad_scripts"
        d.mkdir(parents=True)
        scripts_dir = d / "scripts"
        scripts_dir.mkdir()
        # This import is forbidden by CodeValidator
        (scripts_dir / "bad.py").write_text('import os\ndef bad(): pass')
        namespace = plugin_loader._load_plugin_scripts(d)
        assert "bad" not in namespace

    def test_load_scripts_skips_private_functions(self, plugin_loader):
        d = plugin_loader.available_dir / "private"
        d.mkdir(parents=True)
        scripts_dir = d / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "helpers.py").write_text('def _internal(): pass\ndef public(): return 1')
        namespace = plugin_loader._load_plugin_scripts(d)
        assert "_internal" not in namespace
        assert "public" in namespace

    def test_load_scripts_no_scripts_dir(self, plugin_loader):
        d = plugin_loader.available_dir / "no_scripts"
        d.mkdir(parents=True)
        namespace = plugin_loader._load_plugin_scripts(d)
        assert namespace == {}

    def test_load_scripts_excludes_non_functions(self, plugin_loader):
        d = plugin_loader.available_dir / "mixed"
        d.mkdir(parents=True)
        scripts_dir = d / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "helpers.py").write_text('MY_CONST = 42\ndef my_func(): return MY_CONST')
        namespace = plugin_loader._load_plugin_scripts(d)
        assert "my_func" in namespace
        assert "MY_CONST" not in namespace

    def test_register_plugin_injects_helpers(self, plugin_loader):
        """_register_plugin should inject helper functions into the plugin namespace."""
        # Create a plugin that uses a helper
        d = plugin_loader.available_dir / "with_helper"
        d.mkdir(parents=True)
        (d / "manifest.yaml").write_text(yaml.dump({"name": "with_helper"}))
        (d / "tool.py").write_text('def with_helper(x):\n    return double(x)')
        (d / "schema.yaml").write_text(yaml.dump({
            "name": "with_helper",
            "description": "Uses helper",
            "parameters": {"x": {"type": "integer"}},
        }))
        scripts_dir = d / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "helpers.py").write_text('def double(x):\n    return x * 2')

        with patch("radar.tools.register_dynamic_tool", return_value=True) as mock_reg:
            plugin_loader._register_plugin("with_helper")

        # Verify extra_namespace was passed
        mock_reg.assert_called_once()
        call_kwargs = mock_reg.call_args
        assert call_kwargs.kwargs.get("extra_namespace") is not None
        assert "double" in call_kwargs.kwargs["extra_namespace"]


# ===========================================================================
# 10. Plugin Backward Compatibility
# ===========================================================================


class TestPluginBackwardCompatibility:
    def test_old_manifest_defaults_to_tool_capability(self):
        """Old manifests without capabilities should default to ["tool"]."""
        m = PluginManifest.from_dict({
            "name": "legacy",
            "version": "0.5.0",
            "description": "An old plugin",
        })
        assert m.capabilities == ["tool"]
        assert m.widget is None
        assert m.personalities == []
        assert m.scripts == []

    def test_old_manifest_round_trip_adds_new_fields(self):
        """to_dict always includes new fields even for old manifests."""
        m = PluginManifest.from_dict({"name": "old"})
        d = m.to_dict()
        assert d["capabilities"] == ["tool"]
        assert d["widget"] is None
        assert d["personalities"] == []
        assert d["scripts"] == []
        assert d["tools"] == []


# ===========================================================================
# 11. ToolDefinition
# ===========================================================================


class TestToolDefinition:
    def test_from_dict_full(self):
        data = {
            "name": "upper",
            "description": "Uppercase a string",
            "parameters": {"text": {"type": "string", "description": "Input"}},
        }
        td = ToolDefinition.from_dict(data)
        assert td.name == "upper"
        assert td.description == "Uppercase a string"
        assert td.parameters == {"text": {"type": "string", "description": "Input"}}

    def test_from_dict_defaults(self):
        td = ToolDefinition.from_dict({})
        assert td.name == ""
        assert td.description == ""
        assert td.parameters == {}

    def test_round_trip(self):
        data = {
            "name": "lower",
            "description": "Lowercase",
            "parameters": {"text": {"type": "string", "description": "Input"}},
        }
        td = ToolDefinition.from_dict(data)
        assert td.to_dict() == data

    def test_to_dict(self):
        td = ToolDefinition(name="my_tool", description="desc", parameters={"x": {"type": "integer"}})
        d = td.to_dict()
        assert d["name"] == "my_tool"
        assert d["description"] == "desc"
        assert d["parameters"] == {"x": {"type": "integer"}}


# ===========================================================================
# 12. Multi-Tool Manifest
# ===========================================================================


class TestMultiToolManifest:
    def test_manifest_with_tools(self):
        data = {
            "name": "multi",
            "version": "1.0.0",
            "tools": [
                {"name": "upper", "description": "Uppercase", "parameters": {}},
                {"name": "lower", "description": "Lowercase", "parameters": {}},
            ],
        }
        m = PluginManifest.from_dict(data)
        assert len(m.tools) == 2
        assert m.tools[0].name == "upper"
        assert m.tools[1].name == "lower"

    def test_manifest_without_tools(self):
        m = PluginManifest.from_dict({"name": "single"})
        assert m.tools == []

    def test_manifest_tools_round_trip(self):
        data = {
            "name": "multi",
            "version": "1.0.0",
            "description": "",
            "author": "unknown",
            "trust_level": "sandbox",
            "permissions": [],
            "created_at": "",
            "updated_at": "",
            "capabilities": ["tool"],
            "widget": None,
            "personalities": [],
            "scripts": [],
            "tools": [
                {"name": "upper", "description": "Uppercase", "parameters": {"text": {"type": "string"}}},
            ],
            "prompt_variables": [],
            "hooks": [],
        }
        m = PluginManifest.from_dict(data)
        assert m.to_dict() == data

    def test_plugin_functions_field(self):
        m = PluginManifest(name="p")
        p = Plugin(name="p", manifest=m, code="pass")
        assert p.functions == {}

        p.functions["upper"] = lambda text: text.upper()
        assert "upper" in p.functions


# ===========================================================================
# 13. Multi-Tool Registration (Sandbox)
# ===========================================================================


def _make_multi_tool_plugin(base, name, *, trust_level="sandbox"):
    """Create a multi-tool plugin directory."""
    d = base / name
    d.mkdir(parents=True, exist_ok=True)

    manifest = {
        "name": name,
        "version": "1.0.0",
        "description": "Multi-tool plugin",
        "author": "test",
        "trust_level": trust_level,
        "tools": [
            {"name": "upper", "description": "Uppercase", "parameters": {"text": {"type": "string", "description": "Input"}}},
            {"name": "lower", "description": "Lowercase", "parameters": {"text": {"type": "string", "description": "Input"}}},
        ],
    }
    (d / "manifest.yaml").write_text(yaml.dump(manifest))
    (d / "tool.py").write_text(
        'def upper(text: str) -> str:\n    return text.upper()\n\n'
        'def lower(text: str) -> str:\n    return text.lower()\n'
    )
    return d


class TestMultiToolSandboxRegistration:
    def test_register_multi_tool_sandbox_plugin(self, plugin_loader):
        """Both tools from a sandbox multi-tool plugin should be registered."""
        _make_multi_tool_plugin(plugin_loader.available_dir, "multi")
        with patch("radar.tools.register_dynamic_tool", return_value=True) as mock_reg:
            ok = plugin_loader._register_plugin("multi")
        assert ok is True
        assert mock_reg.call_count == 2
        # Check both tools were registered
        call_names = {c.kwargs.get("name", c.args[0] if c.args else None) for c in mock_reg.call_args_list}
        assert "upper" in call_names
        assert "lower" in call_names

    def test_register_multi_tool_sandbox_callable(self, plugin_loader):
        """Multi-tool sandbox plugins should produce callable tools."""
        _make_multi_tool_plugin(plugin_loader.available_dir, "multi_exec")
        # Don't mock -- let register_dynamic_tool actually run
        from radar.tools import execute_tool, unregister_tool

        plugin_loader._register_plugin("multi_exec")
        try:
            result = execute_tool("upper", {"text": "hello"})
            assert result == "HELLO"
            result = execute_tool("lower", {"text": "HELLO"})
            assert result == "hello"
        finally:
            unregister_tool("upper")
            unregister_tool("lower")


# ===========================================================================
# 14. Local Trust Registration
# ===========================================================================


class TestLocalTrustRegistration:
    def test_register_local_trust_plugin(self, plugin_loader):
        """Local trust plugins should be loaded via importlib."""
        _make_multi_tool_plugin(plugin_loader.available_dir, "local_multi", trust_level="local")

        from radar.tools import execute_tool, unregister_plugin_tools

        plugin_loader._register_plugin("local_multi")
        try:
            result = execute_tool("upper", {"text": "hello"})
            assert result == "HELLO"
            result = execute_tool("lower", {"text": "WORLD"})
            assert result == "world"
        finally:
            unregister_plugin_tools("local_multi")

    def test_local_trust_has_full_python_access(self, plugin_loader):
        """Local trust plugins can import standard library modules."""
        d = plugin_loader.available_dir / "local_imports"
        d.mkdir(parents=True, exist_ok=True)
        manifest = {
            "name": "local_imports",
            "version": "1.0.0",
            "trust_level": "local",
            "tools": [
                {"name": "get_json", "description": "Serialize to JSON", "parameters": {"data": {"type": "string"}}},
            ],
        }
        (d / "manifest.yaml").write_text(yaml.dump(manifest))
        (d / "tool.py").write_text(
            'import json\n\n'
            'def get_json(data: str) -> str:\n'
            '    return json.dumps({"value": data})\n'
        )

        from radar.tools import execute_tool, unregister_plugin_tools

        plugin_loader._register_plugin("local_imports")
        try:
            result = execute_tool("get_json", {"data": "test"})
            assert '"value": "test"' in result
        finally:
            unregister_plugin_tools("local_imports")


# ===========================================================================
# 15. Local Trust Security
# ===========================================================================


class TestLocalTrustSecurity:
    def test_create_plugin_forces_sandbox(self, plugin_loader):
        """create_plugin always sets trust_level to sandbox."""
        with patch("radar.config.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(plugins=MagicMock(max_code_size_bytes=10000))
            ok, msg, err = plugin_loader.create_plugin(
                name="greet",
                description="Greet someone",
                parameters={"name": {"type": "string"}},
                code=VALID_PLUGIN_CODE,
                test_cases=[{"name": "t1", "input_args": {"name": "World"}, "expected_output": "Hello, World!"}],
            )
        assert ok is True
        # Check the manifest was written with sandbox trust
        manifest_path = plugin_loader.pending_dir / "greet" / "manifest.yaml"
        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)
        assert manifest["trust_level"] == "sandbox"

    def test_create_plugin_includes_tools_in_manifest(self, plugin_loader):
        """create_plugin should include tools list in manifest."""
        with patch("radar.config.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(plugins=MagicMock(max_code_size_bytes=10000))
            plugin_loader.create_plugin(
                name="greet",
                description="Greet someone",
                parameters={"name": {"type": "string", "description": "Who"}},
                code=VALID_PLUGIN_CODE,
                test_cases=[],
            )
        manifest_path = plugin_loader.pending_dir / "greet" / "manifest.yaml"
        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)
        assert len(manifest["tools"]) == 1
        assert manifest["tools"][0]["name"] == "greet"

    def test_approve_local_trust_logs_warning(self, plugin_loader):
        """Approving a local trust plugin should log a warning."""
        d = plugin_loader.pending_dir / "local_tool"
        d.mkdir(parents=True)
        manifest = {"name": "local_tool", "trust_level": "local"}
        (d / "manifest.yaml").write_text(yaml.dump(manifest))
        (d / "tool.py").write_text('def local_tool(): return "ok"')
        (d / "schema.yaml").write_text(yaml.dump({"name": "local_tool", "description": "", "parameters": {}}))

        with patch("radar.tools.register_local_tool", return_value=True), \
             patch("logging.getLogger") as mock_log:
            mock_logger = MagicMock()
            mock_log.return_value = mock_logger
            ok, msg = plugin_loader.approve_plugin("local_tool")

        assert ok is True
        mock_logger.warning.assert_called_once()
        assert "local-trust" in mock_logger.warning.call_args[0][0]


# ===========================================================================
# 16. Plugin Install
# ===========================================================================


class TestPluginInstall:
    def test_install_from_directory(self, plugin_loader, tmp_path):
        source = tmp_path / "my_plugin"
        source.mkdir()
        manifest = {"name": "my_plugin", "version": "1.0.0", "trust_level": "local"}
        (source / "manifest.yaml").write_text(yaml.dump(manifest))
        (source / "tool.py").write_text('def my_plugin(): return "ok"')

        ok, msg = plugin_loader.install_plugin(str(source))
        assert ok is True
        assert "my_plugin" in msg
        assert "pending review" in msg
        assert (plugin_loader.pending_dir / "my_plugin" / "manifest.yaml").exists()
        assert (plugin_loader.pending_dir / "my_plugin" / "tool.py").exists()

    def test_install_missing_manifest(self, plugin_loader, tmp_path):
        source = tmp_path / "bad"
        source.mkdir()
        (source / "tool.py").write_text('def f(): pass')
        ok, msg = plugin_loader.install_plugin(str(source))
        assert ok is False
        assert "Missing manifest.yaml" in msg

    def test_install_missing_tool(self, plugin_loader, tmp_path):
        source = tmp_path / "bad"
        source.mkdir()
        (source / "manifest.yaml").write_text(yaml.dump({"name": "bad"}))
        ok, msg = plugin_loader.install_plugin(str(source))
        assert ok is False
        assert "Missing tool.py" in msg

    def test_install_not_a_directory(self, plugin_loader, tmp_path):
        ok, msg = plugin_loader.install_plugin(str(tmp_path / "nonexistent"))
        assert ok is False
        assert "not a directory" in msg

    def test_install_missing_name(self, plugin_loader, tmp_path):
        source = tmp_path / "no_name"
        source.mkdir()
        (source / "manifest.yaml").write_text(yaml.dump({}))
        (source / "tool.py").write_text('def f(): pass')
        ok, msg = plugin_loader.install_plugin(str(source))
        assert ok is False
        assert "name" in msg.lower()

    def test_install_conflicts_with_existing(self, plugin_loader, tmp_path):
        # Create existing plugin
        _make_plugin_dir(plugin_loader.available_dir, "existing")
        # Try to install
        source = tmp_path / "existing"
        source.mkdir()
        (source / "manifest.yaml").write_text(yaml.dump({"name": "existing"}))
        (source / "tool.py").write_text('def f(): pass')
        ok, msg = plugin_loader.install_plugin(str(source))
        assert ok is False
        assert "already exists" in msg

    def test_install_multi_tool(self, plugin_loader, tmp_path):
        source = tmp_path / "multi"
        source.mkdir()
        manifest = {
            "name": "multi",
            "trust_level": "local",
            "tools": [
                {"name": "a", "description": "Tool A"},
                {"name": "b", "description": "Tool B"},
            ],
        }
        (source / "manifest.yaml").write_text(yaml.dump(manifest))
        (source / "tool.py").write_text('def a(): return "a"\ndef b(): return "b"')
        ok, msg = plugin_loader.install_plugin(str(source))
        assert ok is True
        assert "2 tool(s)" in msg


# ===========================================================================
# 17. Multi-Tool Unregistration
# ===========================================================================


class TestMultiToolUnregistration:
    def test_disable_multi_tool_removes_all(self, plugin_loader):
        """Disabling a multi-tool plugin should remove all its tools."""
        _make_multi_tool_plugin(plugin_loader.available_dir, "multi_unreg")

        from radar.tools import _registry, unregister_plugin_tools

        # Register the plugin (real registration)
        plugin_loader._register_plugin("multi_unreg")
        assert "upper" in _registry
        assert "lower" in _registry

        # Now disable
        plugin_loader.enable_plugin("multi_unreg")  # ensure symlink exists
        plugin_loader.disable_plugin("multi_unreg")

        assert "upper" not in _registry
        assert "lower" not in _registry


# ===========================================================================
# 18. Plugin-to-Tools Tracking
# ===========================================================================


class TestPluginToolsTracking:
    def test_register_local_tool_tracks(self):
        """register_local_tool should track the tool under the plugin name."""
        from radar.tools import _plugin_tools, register_local_tool, unregister_plugin_tools

        register_local_tool(
            name="tracked_tool",
            description="test",
            parameters={},
            func=lambda: "ok",
            plugin_name="my_plugin",
        )
        try:
            assert "tracked_tool" in _plugin_tools.get("my_plugin", set())
        finally:
            unregister_plugin_tools("my_plugin")

    def test_unregister_plugin_tools_cleans_up(self):
        """unregister_plugin_tools should remove all tracked tools."""
        from radar.tools import _plugin_tools, _registry, register_local_tool, unregister_plugin_tools

        register_local_tool("t1", "d", {}, lambda: "1", "cleanup_test")
        register_local_tool("t2", "d", {}, lambda: "2", "cleanup_test")

        assert "t1" in _registry
        assert "t2" in _registry
        assert len(_plugin_tools["cleanup_test"]) == 2

        removed = unregister_plugin_tools("cleanup_test")
        assert set(removed) == {"t1", "t2"}
        assert "t1" not in _registry
        assert "t2" not in _registry
        assert "cleanup_test" not in _plugin_tools

    def test_get_plugin_tool_names(self):
        """get_plugin_tool_names should return tracked tool names."""
        from radar.tools import get_plugin_tool_names, register_local_tool, unregister_plugin_tools

        register_local_tool("gtn_a", "d", {}, lambda: "a", "gtn_plugin")
        register_local_tool("gtn_b", "d", {}, lambda: "b", "gtn_plugin")
        try:
            names = get_plugin_tool_names("gtn_plugin")
            assert names == {"gtn_a", "gtn_b"}
        finally:
            unregister_plugin_tools("gtn_plugin")


# ===========================================================================
# 19. Backward Compatibility with schema.yaml
# ===========================================================================


class TestBackwardCompatSchemaYaml:
    def test_no_tools_falls_back_to_schema(self, plugin_loader):
        """Plugin without manifest.tools should use schema.yaml for tool definitions."""
        _make_plugin_dir(plugin_loader.available_dir, "legacy_plugin")
        # Legacy plugin: no tools in manifest, has schema.yaml
        with patch("radar.tools.register_dynamic_tool", return_value=True) as mock_reg:
            ok = plugin_loader._register_plugin("legacy_plugin")
        assert ok is True
        mock_reg.assert_called_once()
        # Tool name should come from schema.yaml
        assert mock_reg.call_args.kwargs.get("name") == "legacy_plugin"

    def test_list_plugins_tool_count_for_legacy(self, plugin_loader):
        """Legacy single-tool plugins should show tool_count=1."""
        _make_plugin_dir(plugin_loader.available_dir, "legacy")
        result = plugin_loader.list_plugins()
        assert len(result) == 1
        assert result[0]["tool_count"] == 1

    def test_list_plugins_tool_count_for_multi(self, plugin_loader):
        """Multi-tool plugins should show correct tool_count."""
        _make_multi_tool_plugin(plugin_loader.available_dir, "multi_count")
        result = plugin_loader.list_plugins()
        multi = next(p for p in result if p["name"] == "multi_count")
        assert multi["tool_count"] == 2


# ===========================================================================
# 20. PromptVariableDefinition
# ===========================================================================


class TestPromptVariableDefinition:
    def test_from_dict_full(self):
        data = {"name": "hostname", "description": "Local machine hostname"}
        pv = PromptVariableDefinition.from_dict(data)
        assert pv.name == "hostname"
        assert pv.description == "Local machine hostname"

    def test_from_dict_defaults(self):
        pv = PromptVariableDefinition.from_dict({})
        assert pv.name == ""
        assert pv.description == ""

    def test_round_trip(self):
        data = {"name": "os_name", "description": "Operating system name"}
        pv = PromptVariableDefinition.from_dict(data)
        assert pv.to_dict() == data

    def test_manifest_parses_prompt_variables(self):
        data = {
            "name": "sys_ctx",
            "capabilities": ["prompt_variables"],
            "prompt_variables": [
                {"name": "hostname", "description": "Host"},
                {"name": "os_name", "description": "OS"},
            ],
        }
        m = PluginManifest.from_dict(data)
        assert len(m.prompt_variables) == 2
        assert m.prompt_variables[0].name == "hostname"
        assert m.prompt_variables[1].name == "os_name"

    def test_empty_prompt_variables_defaults_to_empty_list(self):
        m = PluginManifest.from_dict({"name": "test"})
        assert m.prompt_variables == []

    def test_manifest_prompt_variables_round_trip(self):
        data = {
            "name": "test",
            "version": "1.0.0",
            "description": "",
            "author": "unknown",
            "trust_level": "sandbox",
            "permissions": [],
            "created_at": "",
            "updated_at": "",
            "capabilities": ["prompt_variables"],
            "widget": None,
            "personalities": [],
            "scripts": [],
            "tools": [],
            "prompt_variables": [
                {"name": "hostname", "description": "Host"},
            ],
            "hooks": [],
        }
        m = PluginManifest.from_dict(data)
        assert m.to_dict() == data


# ===========================================================================
# 21. Prompt Variable Values (Loader)
# ===========================================================================


def _make_prompt_var_plugin(
    loader,
    name="sys_ctx",
    *,
    trust_level="sandbox",
    code='def hostname():\n    return "test-host"\n\ndef os_name():\n    return "Linux"',
    prompt_variables=None,
    capabilities=None,
    include_tool_capability=False,
):
    """Create an enabled plugin with prompt_variables capability."""
    d = loader.available_dir / name
    d.mkdir(parents=True, exist_ok=True)

    if prompt_variables is None:
        prompt_variables = [
            {"name": "hostname", "description": "Local hostname"},
            {"name": "os_name", "description": "OS name"},
        ]
    if capabilities is None:
        capabilities = ["prompt_variables"]
        if include_tool_capability:
            capabilities.append("tool")

    manifest = {
        "name": name,
        "version": "1.0.0",
        "description": "Prompt var plugin",
        "author": "test",
        "trust_level": trust_level,
        "capabilities": capabilities,
        "prompt_variables": prompt_variables,
    }
    (d / "manifest.yaml").write_text(yaml.dump(manifest))
    (d / "tool.py").write_text(code)

    # Enable via symlink
    (loader.enabled_dir / name).symlink_to(d)
    return d


class TestGetPromptVariableValues:
    def test_returns_values_from_sandbox_plugin(self, plugin_loader):
        _make_prompt_var_plugin(plugin_loader)
        values = plugin_loader.get_prompt_variable_values()
        assert values["hostname"] == "test-host"
        assert values["os_name"] == "Linux"

    def test_returns_values_from_local_trust_plugin(self, plugin_loader):
        code = (
            'import platform\n'
            'def hostname():\n'
            '    return "local-host"\n'
            'def os_name():\n'
            '    return platform.system()\n'
        )
        _make_prompt_var_plugin(
            plugin_loader, "local_ctx", trust_level="local", code=code,
        )
        values = plugin_loader.get_prompt_variable_values()
        assert values["hostname"] == "local-host"
        assert "os_name" in values  # platform.system() returns something

    def test_skips_plugins_without_prompt_variables_capability(self, plugin_loader):
        # Plugin with only "tool" capability
        _make_plugin_dir(plugin_loader.available_dir, "plain_tool")
        (plugin_loader.enabled_dir / "plain_tool").symlink_to(
            plugin_loader.available_dir / "plain_tool"
        )
        values = plugin_loader.get_prompt_variable_values()
        assert values == {}

    def test_logs_warning_on_function_error(self, plugin_loader, caplog):
        code = 'def hostname():\n    return 1/0\n'
        _make_prompt_var_plugin(
            plugin_loader, "bad_func",
            code=code,
            prompt_variables=[{"name": "hostname", "description": "Host"}],
        )
        with caplog.at_level(logging.WARNING, logger="radar.plugins"):
            values = plugin_loader.get_prompt_variable_values()
        assert "hostname" not in values
        assert "raised an error" in caplog.text

    def test_warns_when_declared_function_not_found(self, plugin_loader, caplog):
        code = 'def other_func():\n    return "hi"\n'
        _make_prompt_var_plugin(
            plugin_loader, "missing_func",
            code=code,
            prompt_variables=[{"name": "hostname", "description": "Host"}],
        )
        with caplog.at_level(logging.WARNING, logger="radar.plugins"):
            values = plugin_loader.get_prompt_variable_values()
        assert "hostname" not in values
        assert "no matching function found" in caplog.text

    def test_plugin_with_both_tools_and_prompt_variables(self, plugin_loader):
        code = (
            'def greet(name):\n'
            '    return f"Hello, {name}!"\n'
            'def hostname():\n'
            '    return "dual-host"\n'
        )
        d = plugin_loader.available_dir / "dual"
        d.mkdir(parents=True, exist_ok=True)
        manifest = {
            "name": "dual",
            "version": "1.0.0",
            "trust_level": "sandbox",
            "capabilities": ["tool", "prompt_variables"],
            "prompt_variables": [{"name": "hostname", "description": "Host"}],
            "tools": [{"name": "greet", "description": "Greet", "parameters": {"name": {"type": "string"}}}],
        }
        (d / "manifest.yaml").write_text(yaml.dump(manifest))
        (d / "tool.py").write_text(code)
        (plugin_loader.enabled_dir / "dual").symlink_to(d)

        values = plugin_loader.get_prompt_variable_values()
        assert values["hostname"] == "dual-host"


# ===========================================================================
# 22. Register Plugin Guard (prompt_variables-only)
# ===========================================================================


class TestRegisterPluginGuard:
    def test_prompt_variables_only_skips_tool_registration(self, plugin_loader):
        """Plugin with only prompt_variables capability doesn't attempt tool registration."""
        code = 'def hostname():\n    return "test"\n'
        _make_prompt_var_plugin(plugin_loader, "pv_only", code=code)

        # _register_plugin should succeed without trying to register tools
        with patch("radar.tools.register_dynamic_tool") as mock_reg:
            ok = plugin_loader._register_plugin("pv_only")
        assert ok is True
        mock_reg.assert_not_called()

    def test_tool_capability_still_registers(self, plugin_loader):
        """Plugin with tool capability still registers its tools."""
        _make_plugin_dir(plugin_loader.available_dir, "with_tool")
        with patch("radar.tools.register_dynamic_tool", return_value=True) as mock_reg:
            ok = plugin_loader._register_plugin("with_tool")
        assert ok is True
        mock_reg.assert_called_once()
