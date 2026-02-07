"""Plugin lifecycle management - loading, creating, approving, versioning."""

import json
import shutil
from datetime import datetime
from pathlib import Path

import yaml

from radar.config import get_data_paths
from radar.plugins.models import Plugin, PluginManifest, PromptVariableDefinition, TestCase, ToolDefinition, ToolError
from radar.plugins.runner import TestRunner
from radar.plugins.validator import CodeValidator
from radar.plugins.versions import VersionManager


class PluginLoader:
    """Loads and manages plugins from filesystem."""

    def __init__(self, plugins_dir: Path | None = None):
        """Initialize with plugins directory."""
        if plugins_dir is None:
            plugins_dir = get_data_paths().plugins

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
                    tools_list = manifest.get("tools", [])
                    tool_count = len(tools_list) if tools_list else 1
                    plugins.append(
                        {
                            "name": manifest.get("name", plugin_dir.name),
                            "description": manifest.get("description", ""),
                            "version": manifest.get("version", "1.0.0"),
                            "author": manifest.get("author", "unknown"),
                            "trust_level": manifest.get("trust_level", "sandbox"),
                            "enabled": enabled_link.exists(),
                            "status": "available",
                            "tool_count": tool_count,
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
                        tools_list = manifest.get("tools", [])
                        tool_count = len(tools_list) if tools_list else 1
                        plugins.append(
                            {
                                "name": manifest.get("name", plugin_dir.name),
                                "description": manifest.get("description", ""),
                                "version": manifest.get("version", "1.0.0"),
                                "author": manifest.get("author", "unknown"),
                                "trust_level": manifest.get("trust_level", "sandbox"),
                                "enabled": False,
                                "status": "pending",
                                "tool_count": tool_count,
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

                    tools_list = manifest.get("tools", [])
                    tool_count = len(tools_list) if tools_list else 1

                    pending.append(
                        {
                            "name": manifest.get("name", plugin_dir.name),
                            "description": manifest.get("description", ""),
                            "author": manifest.get("author", "unknown"),
                            "created_at": manifest.get("created_at", ""),
                            "trust_level": manifest.get("trust_level", "sandbox"),
                            "tool_count": tool_count,
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
        # LLM-generated plugins are always sandboxed
        tool_def = ToolDefinition(name=name, description=description, parameters=parameters)
        manifest = PluginManifest(
            name=name,
            description=description,
            author="llm-generated",
            trust_level="sandbox",
            created_at=datetime.now().isoformat(),
            tools=[tool_def],
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
        """Approve a pending plugin.

        For local trust plugins, auto-approve settings are always ignored --
        they must be explicitly approved by a human.
        """
        import logging

        pending_path = self.pending_dir / name
        if not pending_path.exists():
            return False, f"Plugin '{name}' not found in pending"

        # Check trust level
        manifest_file = pending_path / "manifest.yaml"
        trust_level = "sandbox"
        if manifest_file.exists():
            with open(manifest_file) as f:
                manifest_data = yaml.safe_load(f) or {}
            trust_level = manifest_data.get("trust_level", "sandbox")

        if trust_level == "local":
            logging.getLogger("radar.plugins").warning(
                "Approving local-trust plugin '%s' -- it will have full Python access", name
            )

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

    def install_plugin(self, source_dir: str | Path) -> tuple[bool, str]:
        """Install a plugin from a local directory.

        Copies the source directory to pending_review for human approval.

        Args:
            source_dir: Path to the plugin directory (must have manifest.yaml and tool.py)

        Returns:
            (success, message)
        """
        source = Path(source_dir).expanduser().resolve()

        if not source.is_dir():
            return False, f"Source is not a directory: {source}"

        manifest_file = source / "manifest.yaml"
        code_file = source / "tool.py"

        if not manifest_file.exists():
            return False, f"Missing manifest.yaml in {source}"
        if not code_file.exists():
            return False, f"Missing tool.py in {source}"

        # Read manifest for name and trust level
        with open(manifest_file) as f:
            manifest_data = yaml.safe_load(f) or {}

        plugin_name = manifest_data.get("name")
        if not plugin_name:
            return False, "Manifest must specify a 'name' field"

        trust_level = manifest_data.get("trust_level", "sandbox")

        # Check for conflicts
        if (self.available_dir / plugin_name).exists():
            return False, f"Plugin '{plugin_name}' already exists in available"

        # Copy to pending_review
        dest = self.pending_dir / plugin_name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(str(source), str(dest))

        tools_list = manifest_data.get("tools", [])
        tool_count = len(tools_list) if tools_list else 1

        return True, (
            f"Plugin '{plugin_name}' ({trust_level} trust, {tool_count} tool(s)) "
            f"installed to pending review"
        )

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

    def get_widgets(self) -> list[dict]:
        """Get widget configs from enabled plugins with widget capability.

        Returns list of {name, title, template_content, position, refresh_interval}.
        """
        widgets = []

        # Ensure plugins are loaded
        if not self._plugins:
            self.load_all()

        for plugin in self._plugins.values():
            if (
                "widget" in plugin.manifest.capabilities
                and plugin.manifest.widget
                and plugin.path
            ):
                widget_cfg = plugin.manifest.widget
                template_name = widget_cfg.get("template", "")
                template_file = (plugin.path / template_name).resolve()
                # Prevent path traversal — template must stay within plugin dir
                if not str(template_file).startswith(str(plugin.path.resolve())):
                    continue
                template_content = ""
                if template_file.exists():
                    template_content = template_file.read_text()

                widgets.append({
                    "name": plugin.name,
                    "title": widget_cfg.get("title", plugin.name),
                    "template_content": template_content,
                    "position": widget_cfg.get("position", "default"),
                    "refresh_interval": widget_cfg.get("refresh_interval", 0),
                })

        return widgets

    def get_bundled_personalities(self) -> list[dict]:
        """Scan enabled plugins for bundled personality files.

        Returns list of {name, content, plugin_name}.
        """
        personalities = []

        # Ensure plugins are loaded
        if not self._plugins:
            self.load_all()

        for plugin in self._plugins.values():
            if not plugin.path:
                continue
            personalities_dir = plugin.path / "personalities"
            if not personalities_dir.is_dir():
                continue
            for md_file in sorted(personalities_dir.glob("*.md")):
                personalities.append({
                    "name": md_file.stem,
                    "content": md_file.read_text(),
                    "plugin_name": plugin.name,
                })

        return personalities

    def get_prompt_variable_values(self) -> dict[str, str]:
        """Get prompt variable values from enabled plugins.

        Called on every prompt build (not cached) so that plugin functions
        always return fresh, current values.

        Iterates plugins with `prompt_variables` capability, loads their
        variable functions, calls each one, and returns a flat dict of
        name -> string value. Errors are logged and skipped.
        """
        import logging

        logger = logging.getLogger("radar.plugins")
        values: dict[str, str] = {}

        # Ensure plugins are loaded
        if not self._plugins:
            self.load_all()

        for plugin in self._plugins.values():
            if "prompt_variables" not in plugin.manifest.capabilities:
                continue
            if not plugin.manifest.prompt_variables:
                continue

            funcs = self._load_prompt_variable_functions(plugin)
            for pv_def in plugin.manifest.prompt_variables:
                func = funcs.get(pv_def.name)
                if func is None:
                    logger.warning(
                        "Plugin '%s' declares prompt variable '%s' but "
                        "no matching function found in tool.py",
                        plugin.name, pv_def.name,
                    )
                    continue
                try:
                    result = func()
                    values[pv_def.name] = str(result)
                except Exception:
                    logger.warning(
                        "Plugin '%s' prompt variable '%s' raised an error",
                        plugin.name, pv_def.name,
                        exc_info=True,
                    )

        return values

    def _load_prompt_variable_functions(self, plugin: Plugin) -> dict:
        """Load prompt variable callable functions from a plugin.

        Dispatches by trust level (same pattern as tool registration):
        - sandbox: compile and run in restricted namespace
        - local: load via importlib
        """
        import importlib.util
        import types

        funcs: dict = {}
        if not plugin.path:
            return funcs

        code_file = plugin.path / "tool.py"
        if not code_file.exists():
            return funcs

        if plugin.manifest.trust_level == "local":
            spec = importlib.util.spec_from_file_location(
                f"radar_plugin_pv_{plugin.name}", code_file
            )
            if not spec or not spec.loader:
                return funcs
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception:
                return funcs
            for pv_def in plugin.manifest.prompt_variables:
                func = getattr(module, pv_def.name, None)
                if func and callable(func):
                    funcs[pv_def.name] = func
        else:
            # Sandbox: restricted namespace
            safe_builtins = {
                "True": True, "False": False, "None": None,
                "abs": abs, "all": all, "any": any, "bool": bool, "chr": chr,
                "dict": dict, "divmod": divmod, "enumerate": enumerate,
                "filter": filter, "float": float, "format": format,
                "frozenset": frozenset, "hash": hash, "hex": hex, "int": int,
                "isinstance": isinstance, "issubclass": issubclass, "iter": iter,
                "len": len, "list": list, "map": map, "max": max, "min": min,
                "next": next, "oct": oct, "ord": ord, "pow": pow, "print": print,
                "range": range, "repr": repr, "reversed": reversed, "round": round,
                "set": set, "slice": slice, "sorted": sorted, "str": str,
                "sum": sum, "tuple": tuple, "type": type, "zip": zip,
            }
            code = code_file.read_text()
            namespace: dict = {"__builtins__": safe_builtins}
            try:
                compiled = compile(code, str(code_file), "exec")
                exec(compiled, namespace)  # noqa: S102 — validated plugin code
            except Exception:
                return funcs
            for pv_def in plugin.manifest.prompt_variables:
                func = namespace.get(pv_def.name)
                if isinstance(func, types.FunctionType):
                    funcs[pv_def.name] = func

        return funcs

    def _load_plugin_scripts(self, plugin_dir: Path) -> dict:
        """Load helper script modules from plugin's scripts/ directory.

        Validates each script with CodeValidator and executes valid ones
        in a restricted namespace with safe builtins (same restrictions as
        register_dynamic_tool).
        Returns merged namespace dict containing only functions.
        """
        import types

        scripts_dir = plugin_dir / "scripts"
        if not scripts_dir.is_dir():
            return {}

        # Same safe builtins used by register_dynamic_tool — no open/import/eval
        safe_builtins = {
            "True": True, "False": False, "None": None,
            "abs": abs, "all": all, "any": any, "bool": bool, "chr": chr,
            "dict": dict, "divmod": divmod, "enumerate": enumerate,
            "filter": filter, "float": float, "format": format,
            "frozenset": frozenset, "hash": hash, "hex": hex, "int": int,
            "isinstance": isinstance, "issubclass": issubclass, "iter": iter,
            "len": len, "list": list, "map": map, "max": max, "min": min,
            "next": next, "oct": oct, "ord": ord, "pow": pow, "print": print,
            "range": range, "repr": repr, "reversed": reversed, "round": round,
            "set": set, "slice": slice, "sorted": sorted, "str": str,
            "sum": sum, "tuple": tuple, "type": type, "zip": zip,
        }

        namespace = {}
        for script_file in sorted(scripts_dir.glob("*.py")):
            code = script_file.read_text()
            is_valid, _issues = self.validator.validate(code)
            if not is_valid:
                continue

            # Execute in restricted namespace with safe builtins only
            script_ns: dict = {"__builtins__": safe_builtins}
            try:
                compiled = compile(code, str(script_file), "exec")
                exec(compiled, script_ns)  # noqa: S102 — validated plugin code
            except Exception:
                continue

            # Collect only functions (no dunder keys)
            for key, value in script_ns.items():
                if isinstance(value, types.FunctionType) and not key.startswith("_"):
                    namespace[key] = value

        return namespace

    def _get_tool_definitions(
        self, plugin_dir: Path, manifest: PluginManifest,
    ) -> list[ToolDefinition]:
        """Get tool definitions for a plugin.

        If the manifest has a non-empty tools list, use it.
        Otherwise fall back to reading schema.yaml (backward compat).
        """
        if manifest.tools:
            return manifest.tools

        # Fallback: read schema.yaml for single-tool plugins
        schema_file = plugin_dir / "schema.yaml"
        if schema_file.exists():
            with open(schema_file) as f:
                schema = yaml.safe_load(f) or {}
            return [ToolDefinition(
                name=schema.get("name", manifest.name),
                description=schema.get("description", manifest.description),
                parameters=schema.get("parameters", {}),
            )]

        # Last resort: use manifest name
        return [ToolDefinition(
            name=manifest.name,
            description=manifest.description,
        )]

    def _register_plugin(self, name: str) -> bool:
        """Register a plugin's tools.

        Dispatches based on trust level:
        - sandbox: exec code in restricted namespace (current behavior)
        - local: importlib load with full Python access

        Plugins without the "tool" capability skip tool registration.
        """
        available_path = self.available_dir / name
        manifest_file = available_path / "manifest.yaml"

        if not manifest_file.exists():
            return False

        with open(manifest_file) as f:
            manifest_data = yaml.safe_load(f) or {}
        manifest = PluginManifest.from_dict(manifest_data)

        # Skip tool registration if plugin doesn't have the "tool" capability
        if "tool" not in manifest.capabilities:
            return True

        code_file = available_path / "tool.py"
        if not code_file.exists():
            return False

        tool_defs = self._get_tool_definitions(available_path, manifest)

        if manifest.trust_level == "local":
            return self._register_local_plugin(name, code_file, tool_defs)
        else:
            return self._register_sandbox_plugin(name, available_path, code_file, tool_defs)

    def _register_sandbox_plugin(
        self,
        plugin_name: str,
        plugin_dir: Path,
        code_file: Path,
        tool_defs: list[ToolDefinition],
    ) -> bool:
        """Register sandbox-trust plugin tools via exec in restricted namespace."""
        from radar.tools import register_dynamic_tool, track_plugin_tool

        code = code_file.read_text()
        helpers = self._load_plugin_scripts(plugin_dir)

        success = True
        for td in tool_defs:
            ok = register_dynamic_tool(
                name=td.name,
                description=td.description,
                parameters=td.parameters,
                code=code,
                extra_namespace=helpers if helpers else None,
            )
            if ok:
                track_plugin_tool(plugin_name, td.name)
            else:
                success = False
        return success

    def _register_local_plugin(
        self,
        plugin_name: str,
        code_file: Path,
        tool_defs: list[ToolDefinition],
    ) -> bool:
        """Register local-trust plugin tools via importlib (full Python access)."""
        import importlib.util

        from radar.tools import register_local_tool

        spec = importlib.util.spec_from_file_location(
            f"radar_plugin_{plugin_name}", code_file
        )
        if not spec or not spec.loader:
            return False

        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception:
            return False

        success = True
        for td in tool_defs:
            func = getattr(module, td.name, None)
            if func is None:
                success = False
                continue
            register_local_tool(
                name=td.name,
                description=td.description,
                parameters=td.parameters,
                func=func,
                plugin_name=plugin_name,
            )
        return success

    def _unregister_plugin(self, name: str) -> bool:
        """Unregister all tools belonging to a plugin."""
        from radar.tools import unregister_plugin_tools, unregister_tool

        # Try the tracked plugin tools first
        removed = unregister_plugin_tools(name)
        if removed:
            return True
        # Fallback: single-tool plugin where name == tool name
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
