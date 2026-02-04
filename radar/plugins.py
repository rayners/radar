"""Plugin system for dynamic tool creation and management.

Provides infrastructure for:
- Loading plugins from filesystem
- Validating code via AST analysis
- Running tests in a sandbox
- Managing plugin versions
- Tracking errors for debugging
"""

import ast
import hashlib
import json
import shutil
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import yaml


# ===== Data Classes =====


@dataclass
class PluginManifest:
    """Plugin manifest describing a tool."""

    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = "unknown"
    trust_level: str = "sandbox"  # "sandbox" or "trusted"
    permissions: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "PluginManifest":
        """Create manifest from dictionary."""
        return cls(
            name=data.get("name", "unknown"),
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            author=data.get("author", "unknown"),
            trust_level=data.get("trust_level", "sandbox"),
            permissions=data.get("permissions", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    def to_dict(self) -> dict:
        """Convert manifest to dictionary."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "trust_level": self.trust_level,
            "permissions": self.permissions,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class TestCase:
    """A test case for a plugin."""

    name: str
    input_args: dict
    expected_output: str | None = None  # None means just check no exception
    expected_contains: str | None = None  # Output should contain this

    @classmethod
    def from_dict(cls, data: dict) -> "TestCase":
        """Create test case from dictionary."""
        return cls(
            name=data.get("name", "test"),
            input_args=data.get("input_args", data.get("input", {})),
            expected_output=data.get("expected_output", data.get("expected")),
            expected_contains=data.get("expected_contains"),
        )


@dataclass
class ToolError:
    """Error information for debugging failed tools."""

    tool_name: str
    error_type: str  # "syntax", "runtime", "test_failure", "validation"
    message: str
    traceback_str: str
    input_args: dict
    expected_output: str | None
    actual_output: str | None
    attempt_number: int
    max_attempts: int = 5
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "tool_name": self.tool_name,
            "error_type": self.error_type,
            "message": self.message,
            "traceback": self.traceback_str,
            "input_args": self.input_args,
            "expected_output": self.expected_output,
            "actual_output": self.actual_output,
            "attempt_number": self.attempt_number,
            "max_attempts": self.max_attempts,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ToolError":
        """Create from dictionary."""
        return cls(
            tool_name=data["tool_name"],
            error_type=data["error_type"],
            message=data["message"],
            traceback_str=data.get("traceback", ""),
            input_args=data.get("input_args", {}),
            expected_output=data.get("expected_output"),
            actual_output=data.get("actual_output"),
            attempt_number=data.get("attempt_number", 1),
            max_attempts=data.get("max_attempts", 5),
            timestamp=data.get("timestamp", ""),
        )


@dataclass
class Plugin:
    """A loaded plugin."""

    name: str
    manifest: PluginManifest
    code: str
    function: Callable | None = None
    enabled: bool = True
    path: Path | None = None
    test_cases: list[TestCase] = field(default_factory=list)
    errors: list[ToolError] = field(default_factory=list)


# ===== Code Validator =====


class CodeValidator:
    """Validates plugin code using AST analysis."""

    # Forbidden imports that could be dangerous
    FORBIDDEN_IMPORTS = {
        "os",
        "subprocess",
        "sys",
        "socket",
        "shutil",
        "multiprocessing",
        "threading",
        "ctypes",
        "pickle",
        "marshal",
    }

    # Forbidden function calls
    FORBIDDEN_CALLS = {
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "globals",
        "locals",
        "getattr",
        "setattr",
        "delattr",
    }

    # Forbidden attribute access patterns
    FORBIDDEN_ATTRIBUTES = {
        "__code__",
        "__globals__",
        "__builtins__",
        "__subclasses__",
        "__bases__",
        "__mro__",
    }

    def __init__(self, allowed_imports: set[str] | None = None):
        """Initialize validator with optional allowed imports."""
        self.allowed_imports = allowed_imports or set()

    def validate(self, code: str) -> tuple[bool, list[str]]:
        """Validate code and return (is_valid, list of issues)."""
        issues = []

        # Try to parse the code
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, [f"Syntax error: {e}"]

        # Check for forbidden patterns
        for node in ast.walk(tree):
            # Check imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name.split(".")[0]
                    if module in self.FORBIDDEN_IMPORTS and module not in self.allowed_imports:
                        issues.append(f"Forbidden import: {alias.name}")

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module = node.module.split(".")[0]
                    if module in self.FORBIDDEN_IMPORTS and module not in self.allowed_imports:
                        issues.append(f"Forbidden import from: {node.module}")

            # Check function calls
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in self.FORBIDDEN_CALLS:
                        issues.append(f"Forbidden call: {node.func.id}()")
                elif isinstance(node.func, ast.Attribute):
                    # Check for things like obj.__import__()
                    if node.func.attr in self.FORBIDDEN_CALLS:
                        issues.append(f"Forbidden call: .{node.func.attr}()")

            # Check attribute access
            elif isinstance(node, ast.Attribute):
                if node.attr in self.FORBIDDEN_ATTRIBUTES:
                    issues.append(f"Forbidden attribute access: {node.attr}")

        # Check for function definition
        has_function = any(isinstance(node, ast.FunctionDef) for node in ast.walk(tree))
        if not has_function:
            issues.append("Code must define at least one function")

        return len(issues) == 0, issues


# ===== Test Runner =====


class TestRunner:
    """Runs tests for plugins in a sandboxed environment."""

    def __init__(self, timeout_seconds: int = 10):
        """Initialize test runner with timeout."""
        self.timeout_seconds = timeout_seconds

    def run_tests(
        self, code: str, test_cases: list[TestCase], function_name: str
    ) -> tuple[bool, list[dict]]:
        """Run test cases against the code.

        Returns (all_passed, list of test results).
        """
        results = []

        # Create a restricted namespace for execution
        namespace = self._create_safe_namespace()

        # Execute the code to define the function
        # Note: This uses exec() intentionally for sandboxed plugin execution
        # The code has been validated by CodeValidator before reaching here
        try:
            exec(code, namespace)  # nosec: validated code execution
        except Exception as e:
            return False, [
                {
                    "name": "code_execution",
                    "passed": False,
                    "error": f"Failed to execute code: {e}",
                    "traceback": traceback.format_exc(),
                }
            ]

        # Get the function
        if function_name not in namespace:
            return False, [
                {
                    "name": "function_check",
                    "passed": False,
                    "error": f"Function '{function_name}' not defined in code",
                }
            ]

        func = namespace[function_name]

        # Run each test case
        all_passed = True
        for test in test_cases:
            result = self._run_single_test(func, test)
            results.append(result)
            if not result["passed"]:
                all_passed = False

        return all_passed, results

    def _run_single_test(self, func: Callable, test: TestCase) -> dict:
        """Run a single test case."""
        result = {
            "name": test.name,
            "input": test.input_args,
            "passed": False,
            "output": None,
            "error": None,
            "traceback": None,
        }

        try:
            output = func(**test.input_args)
            result["output"] = str(output) if output is not None else None

            # Check expected output
            if test.expected_output is not None:
                if str(output) == test.expected_output:
                    result["passed"] = True
                else:
                    result["error"] = f"Expected '{test.expected_output}', got '{output}'"
            elif test.expected_contains is not None:
                if test.expected_contains in str(output):
                    result["passed"] = True
                else:
                    result["error"] = f"Output doesn't contain '{test.expected_contains}'"
            else:
                # No expected output, just check it ran without error
                result["passed"] = True

        except Exception as e:
            result["error"] = str(e)
            result["traceback"] = traceback.format_exc()

        return result

    def _create_safe_namespace(self) -> dict:
        """Create a restricted namespace for code execution."""
        # Start with basic builtins
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
            "print": print,  # Allow print for debugging
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

        return {"__builtins__": safe_builtins}


# ===== Version Manager =====


class VersionManager:
    """Manages plugin versions for rollback capability."""

    def __init__(self, versions_dir: Path):
        """Initialize with versions directory."""
        self.versions_dir = versions_dir
        self.versions_dir.mkdir(parents=True, exist_ok=True)

    def save_version(self, plugin_name: str, code: str, manifest: PluginManifest) -> str:
        """Save a new version of a plugin. Returns version string."""
        plugin_versions_dir = self.versions_dir / plugin_name
        plugin_versions_dir.mkdir(parents=True, exist_ok=True)

        # Find next version number
        existing_versions = list(plugin_versions_dir.glob("v*.py"))
        next_version = len(existing_versions) + 1
        version_str = f"v{next_version}"

        # Save the code
        code_file = plugin_versions_dir / f"{version_str}.py"
        code_file.write_text(code)

        # Save the manifest
        manifest_file = plugin_versions_dir / f"{version_str}.yaml"
        manifest.version = version_str
        manifest.updated_at = datetime.now().isoformat()
        with open(manifest_file, "w") as f:
            yaml.dump(manifest.to_dict(), f)

        return version_str

    def get_versions(self, plugin_name: str) -> list[dict]:
        """Get list of versions for a plugin."""
        plugin_versions_dir = self.versions_dir / plugin_name
        if not plugin_versions_dir.exists():
            return []

        versions = []
        for code_file in sorted(plugin_versions_dir.glob("v*.py")):
            version_str = code_file.stem
            manifest_file = plugin_versions_dir / f"{version_str}.yaml"

            version_info = {"version": version_str, "code_file": str(code_file)}

            if manifest_file.exists():
                with open(manifest_file) as f:
                    manifest_data = yaml.safe_load(f) or {}
                version_info["manifest"] = manifest_data
                version_info["created_at"] = manifest_data.get("updated_at", "")

            versions.append(version_info)

        return versions

    def get_version(self, plugin_name: str, version: str) -> tuple[str, PluginManifest] | None:
        """Get a specific version's code and manifest."""
        plugin_versions_dir = self.versions_dir / plugin_name
        code_file = plugin_versions_dir / f"{version}.py"
        manifest_file = plugin_versions_dir / f"{version}.yaml"

        if not code_file.exists():
            return None

        code = code_file.read_text()

        if manifest_file.exists():
            with open(manifest_file) as f:
                manifest_data = yaml.safe_load(f) or {}
            manifest = PluginManifest.from_dict(manifest_data)
        else:
            manifest = PluginManifest(name=plugin_name, version=version)

        return code, manifest


# ===== Plugin Loader =====


class PluginLoader:
    """Loads and manages plugins from filesystem."""

    def __init__(self, plugins_dir: Path | None = None):
        """Initialize with plugins directory."""
        if plugins_dir is None:
            data_dir = Path.home() / ".local" / "share" / "radar"
            plugins_dir = data_dir / "plugins"

        self.plugins_dir = plugins_dir
        self.enabled_dir = plugins_dir / "enabled"
        self.available_dir = plugins_dir / "available"
        self.pending_dir = plugins_dir / "pending_review"
        self.failed_dir = plugins_dir / "failed"
        self.versions_dir = plugins_dir / "versions"
        self.errors_dir = plugins_dir / "errors"

        # Create directories
        for d in [
            self.enabled_dir,
            self.available_dir,
            self.pending_dir,
            self.failed_dir,
            self.versions_dir,
            self.errors_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)

        self.validator = CodeValidator()
        self.test_runner = TestRunner()
        self.version_manager = VersionManager(self.versions_dir)

        # Loaded plugins
        self._plugins: dict[str, Plugin] = {}

    def load_all(self) -> list[Plugin]:
        """Load all enabled plugins."""
        plugins = []

        for plugin_dir in self.enabled_dir.iterdir():
            if plugin_dir.is_dir():
                plugin = self._load_plugin(plugin_dir)
                if plugin:
                    plugins.append(plugin)
                    self._plugins[plugin.name] = plugin
            elif plugin_dir.is_symlink():
                # Follow symlink to actual plugin
                target = plugin_dir.resolve()
                if target.is_dir():
                    plugin = self._load_plugin(target)
                    if plugin:
                        plugins.append(plugin)
                        self._plugins[plugin.name] = plugin

        return plugins

    def _load_plugin(self, plugin_dir: Path) -> Plugin | None:
        """Load a single plugin from directory."""
        manifest_file = plugin_dir / "manifest.yaml"
        code_file = plugin_dir / "tool.py"
        tests_file = plugin_dir / "tests.yaml"

        if not manifest_file.exists() or not code_file.exists():
            return None

        # Load manifest
        with open(manifest_file) as f:
            manifest_data = yaml.safe_load(f) or {}
        manifest = PluginManifest.from_dict(manifest_data)

        # Load code
        code = code_file.read_text()

        # Load tests
        test_cases = []
        if tests_file.exists():
            with open(tests_file) as f:
                tests_data = yaml.safe_load(f) or []
            test_cases = [TestCase.from_dict(t) for t in tests_data]

        # Load any saved errors
        errors = self._load_errors(manifest.name)

        return Plugin(
            name=manifest.name,
            manifest=manifest,
            code=code,
            enabled=True,
            path=plugin_dir,
            test_cases=test_cases,
            errors=errors,
        )

    def get_plugin(self, name: str) -> Plugin | None:
        """Get a loaded plugin by name."""
        return self._plugins.get(name)

    def list_plugins(self, include_pending: bool = False) -> list[dict]:
        """List all plugins with their status."""
        plugins = []

        # Available plugins
        for plugin_dir in self.available_dir.iterdir():
            if plugin_dir.is_dir():
                manifest_file = plugin_dir / "manifest.yaml"
                if manifest_file.exists():
                    with open(manifest_file) as f:
                        manifest = yaml.safe_load(f) or {}
                    # Check if enabled
                    enabled_link = self.enabled_dir / plugin_dir.name
                    plugins.append(
                        {
                            "name": manifest.get("name", plugin_dir.name),
                            "description": manifest.get("description", ""),
                            "version": manifest.get("version", "1.0.0"),
                            "author": manifest.get("author", "unknown"),
                            "trust_level": manifest.get("trust_level", "sandbox"),
                            "enabled": enabled_link.exists(),
                            "status": "available",
                        }
                    )

        # Pending plugins
        if include_pending:
            for plugin_dir in self.pending_dir.iterdir():
                if plugin_dir.is_dir():
                    manifest_file = plugin_dir / "manifest.yaml"
                    if manifest_file.exists():
                        with open(manifest_file) as f:
                            manifest = yaml.safe_load(f) or {}
                        plugins.append(
                            {
                                "name": manifest.get("name", plugin_dir.name),
                                "description": manifest.get("description", ""),
                                "version": manifest.get("version", "1.0.0"),
                                "author": manifest.get("author", "unknown"),
                                "trust_level": manifest.get("trust_level", "sandbox"),
                                "enabled": False,
                                "status": "pending",
                            }
                        )

        return plugins

    def list_pending(self) -> list[dict]:
        """List plugins pending review."""
        pending = []

        for plugin_dir in self.pending_dir.iterdir():
            if plugin_dir.is_dir():
                manifest_file = plugin_dir / "manifest.yaml"
                code_file = plugin_dir / "tool.py"

                if manifest_file.exists():
                    with open(manifest_file) as f:
                        manifest = yaml.safe_load(f) or {}

                    code = ""
                    if code_file.exists():
                        code = code_file.read_text()

                    pending.append(
                        {
                            "name": manifest.get("name", plugin_dir.name),
                            "description": manifest.get("description", ""),
                            "author": manifest.get("author", "unknown"),
                            "created_at": manifest.get("created_at", ""),
                            "code": code,
                            "path": str(plugin_dir),
                        }
                    )

        return pending

    def create_plugin(
        self,
        name: str,
        description: str,
        parameters: dict,
        code: str,
        test_cases: list[dict],
        auto_approve: bool = False,
    ) -> tuple[bool, str, dict | None]:
        """Create a new plugin.

        Returns (success, message, error_details).
        """
        from radar.config import get_config

        config = get_config()
        max_code_size = getattr(config.plugins, "max_code_size_bytes", 10000)

        # Check code size
        if len(code.encode("utf-8")) > max_code_size:
            return False, f"Code exceeds maximum size of {max_code_size} bytes", None

        # Validate code
        is_valid, issues = self.validator.validate(code)
        if not is_valid:
            return False, f"Code validation failed: {', '.join(issues)}", {"issues": issues}

        # Parse test cases
        tests = [TestCase.from_dict(t) for t in test_cases]

        # Run tests
        all_passed, test_results = self.test_runner.run_tests(code, tests, name)

        # Create manifest (needed whether tests pass or fail)
        manifest = PluginManifest(
            name=name,
            description=description,
            author="llm-generated",
            trust_level="sandbox",
            created_at=datetime.now().isoformat(),
        )

        if not all_passed:
            # Store error for debugging
            failed_test = next((r for r in test_results if not r["passed"]), None)
            if failed_test:
                error = ToolError(
                    tool_name=name,
                    error_type="test_failure",
                    message=failed_test.get("error", "Test failed"),
                    traceback_str=failed_test.get("traceback", ""),
                    input_args=failed_test.get("input", {}),
                    expected_output=str(tests[0].expected_output) if tests else None,
                    actual_output=failed_test.get("output"),
                    attempt_number=1,
                )
                self._save_error(name, error)

            # Save the failing plugin to pending_review so debug_tool can fix it
            dest_dir = self.pending_dir / name
            dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir / "manifest.yaml").write_text(yaml.dump(manifest.to_dict()))
            (dest_dir / "tool.py").write_text(code)
            if test_cases:
                (dest_dir / "tests.yaml").write_text(yaml.dump(test_cases))
            # Save tool schema for when it's eventually fixed
            schema = {"name": name, "description": description, "parameters": parameters}
            (dest_dir / "schema.yaml").write_text(yaml.dump(schema))

            return (
                False,
                "Tests failed. Plugin saved to pending_review for debugging.",
                {"test_results": test_results, "error": error.to_dict() if failed_test else None},
            )

        # Tests passed - determine destination
        if auto_approve:
            dest_dir = self.available_dir / name
        else:
            dest_dir = self.pending_dir / name

        dest_dir.mkdir(parents=True, exist_ok=True)

        # Save files
        (dest_dir / "manifest.yaml").write_text(yaml.dump(manifest.to_dict()))
        (dest_dir / "tool.py").write_text(code)

        # Save tests
        if test_cases:
            (dest_dir / "tests.yaml").write_text(yaml.dump(test_cases))

        # Save tool schema for registration
        schema = {
            "name": name,
            "description": description,
            "parameters": parameters,
        }
        (dest_dir / "schema.yaml").write_text(yaml.dump(schema))

        # Save version
        self.version_manager.save_version(name, code, manifest)

        if auto_approve:
            # Enable it
            self.enable_plugin(name)
            return True, f"Plugin '{name}' created and enabled", None
        else:
            return True, f"Plugin '{name}' created and pending review", None

    def approve_plugin(self, name: str) -> tuple[bool, str]:
        """Approve a pending plugin."""
        pending_path = self.pending_dir / name
        if not pending_path.exists():
            return False, f"Plugin '{name}' not found in pending"

        # Move to available
        available_path = self.available_dir / name
        if available_path.exists():
            shutil.rmtree(available_path)
        shutil.move(str(pending_path), str(available_path))

        # Enable it
        self.enable_plugin(name)

        return True, f"Plugin '{name}' approved and enabled"

    def reject_plugin(self, name: str, reason: str = "") -> tuple[bool, str]:
        """Reject a pending plugin."""
        pending_path = self.pending_dir / name
        if not pending_path.exists():
            return False, f"Plugin '{name}' not found in pending"

        # Move to failed with reason
        failed_path = self.failed_dir / name
        if failed_path.exists():
            shutil.rmtree(failed_path)
        shutil.move(str(pending_path), str(failed_path))

        # Save rejection reason
        if reason:
            (failed_path / "rejection_reason.txt").write_text(reason)

        return True, f"Plugin '{name}' rejected"

    def enable_plugin(self, name: str) -> tuple[bool, str]:
        """Enable a plugin."""
        available_path = self.available_dir / name
        if not available_path.exists():
            return False, f"Plugin '{name}' not found"

        enabled_link = self.enabled_dir / name

        # Create symlink if not exists
        if not enabled_link.exists():
            enabled_link.symlink_to(available_path)

        # Register the tool
        self._register_plugin(name)

        return True, f"Plugin '{name}' enabled"

    def disable_plugin(self, name: str) -> tuple[bool, str]:
        """Disable a plugin."""
        enabled_link = self.enabled_dir / name
        if enabled_link.exists() or enabled_link.is_symlink():
            enabled_link.unlink()

        # Unregister the tool
        self._unregister_plugin(name)

        return True, f"Plugin '{name}' disabled"

    def _register_plugin(self, name: str) -> bool:
        """Register a plugin as a tool."""
        available_path = self.available_dir / name
        code_file = available_path / "tool.py"
        schema_file = available_path / "schema.yaml"

        if not code_file.exists() or not schema_file.exists():
            return False

        code = code_file.read_text()
        with open(schema_file) as f:
            schema = yaml.safe_load(f) or {}

        # Import the registration function
        from radar.tools import register_dynamic_tool

        return register_dynamic_tool(
            name=schema.get("name", name),
            description=schema.get("description", ""),
            parameters=schema.get("parameters", {}),
            code=code,
        )

    def _unregister_plugin(self, name: str) -> bool:
        """Unregister a plugin from tools."""
        from radar.tools import unregister_tool

        return unregister_tool(name)

    def rollback_plugin(self, name: str, version: str) -> tuple[bool, str]:
        """Rollback a plugin to a previous version."""
        result = self.version_manager.get_version(name, version)
        if result is None:
            return False, f"Version '{version}' not found for plugin '{name}'"

        code, manifest = result
        available_path = self.available_dir / name

        if not available_path.exists():
            return False, f"Plugin '{name}' not found"

        # Update the code
        (available_path / "tool.py").write_text(code)
        (available_path / "manifest.yaml").write_text(yaml.dump(manifest.to_dict()))

        # Re-register if enabled
        enabled_link = self.enabled_dir / name
        if enabled_link.exists():
            self._register_plugin(name)

        return True, f"Plugin '{name}' rolled back to {version}"

    def update_plugin_code(self, name: str, new_code: str) -> tuple[bool, str, dict | None]:
        """Update a plugin's code (for debugging/fixing)."""
        # Find the plugin
        paths_to_check = [
            self.pending_dir / name,
            self.available_dir / name,
        ]

        plugin_path = None
        for p in paths_to_check:
            if p.exists():
                plugin_path = p
                break

        if plugin_path is None:
            return False, f"Plugin '{name}' not found", None

        # Load existing data
        manifest_file = plugin_path / "manifest.yaml"
        schema_file = plugin_path / "schema.yaml"
        tests_file = plugin_path / "tests.yaml"

        if not manifest_file.exists():
            return False, "Plugin manifest not found", None

        with open(manifest_file) as f:
            manifest_data = yaml.safe_load(f) or {}
        manifest = PluginManifest.from_dict(manifest_data)

        # Validate new code
        is_valid, issues = self.validator.validate(new_code)
        if not is_valid:
            return False, f"Code validation failed: {', '.join(issues)}", {"issues": issues}

        # Load and run tests
        test_cases = []
        if tests_file.exists():
            with open(tests_file) as f:
                tests_data = yaml.safe_load(f) or []
            test_cases = [TestCase.from_dict(t) for t in tests_data]

        if test_cases:
            all_passed, test_results = self.test_runner.run_tests(new_code, test_cases, name)

            if not all_passed:
                # Get current attempt count
                errors = self._load_errors(name)
                attempt = len(errors) + 1

                failed_test = next((r for r in test_results if not r["passed"]), None)
                if failed_test:
                    error = ToolError(
                        tool_name=name,
                        error_type="test_failure",
                        message=failed_test.get("error", "Test failed"),
                        traceback_str=failed_test.get("traceback", ""),
                        input_args=failed_test.get("input", {}),
                        expected_output=str(test_cases[0].expected_output) if test_cases else None,
                        actual_output=failed_test.get("output"),
                        attempt_number=attempt,
                    )
                    self._save_error(name, error)

                return (
                    False,
                    f"Tests failed (attempt {attempt})",
                    {"test_results": test_results, "attempt": attempt},
                )

        # Save new version
        self.version_manager.save_version(name, new_code, manifest)

        # Update the code file
        (plugin_path / "tool.py").write_text(new_code)

        # Clear errors on success
        self._clear_errors(name)

        # Re-register if enabled
        enabled_link = self.enabled_dir / name
        if enabled_link.exists():
            self._register_plugin(name)

        return True, f"Plugin '{name}' updated successfully", None

    def _save_error(self, plugin_name: str, error: ToolError) -> None:
        """Save an error for a plugin."""
        errors_file = self.errors_dir / f"{plugin_name}.json"

        errors = []
        if errors_file.exists():
            with open(errors_file) as f:
                errors = json.load(f)

        errors.append(error.to_dict())

        with open(errors_file, "w") as f:
            json.dump(errors, f, indent=2)

    def _load_errors(self, plugin_name: str) -> list[ToolError]:
        """Load errors for a plugin."""
        errors_file = self.errors_dir / f"{plugin_name}.json"

        if not errors_file.exists():
            return []

        with open(errors_file) as f:
            errors_data = json.load(f)

        return [ToolError.from_dict(e) for e in errors_data]

    def _clear_errors(self, plugin_name: str) -> None:
        """Clear errors for a plugin."""
        errors_file = self.errors_dir / f"{plugin_name}.json"
        if errors_file.exists():
            errors_file.unlink()

    def get_last_error(self, plugin_name: str) -> ToolError | None:
        """Get the last error for a plugin."""
        errors = self._load_errors(plugin_name)
        return errors[-1] if errors else None

    def get_error_count(self, plugin_name: str) -> int:
        """Get the number of errors/attempts for a plugin."""
        return len(self._load_errors(plugin_name))


# ===== Global instance =====

_loader: PluginLoader | None = None


def get_plugin_loader() -> PluginLoader:
    """Get the global plugin loader instance."""
    global _loader
    if _loader is None:
        _loader = PluginLoader()
    return _loader
