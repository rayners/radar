"""Tests for radar/plugins/ package — models, validator, runner, versions, loader."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from radar.plugins.models import Plugin, PluginManifest, TestCase, ToolError
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
