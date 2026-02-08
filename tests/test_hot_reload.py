"""Tests for config hot-reload at heartbeat."""

import time as time_mod
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

import radar.config
import radar.scheduler as sched_mod
import radar.tools as tools_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_config_mtime():
    """Reset config mtime tracking before/after each test."""
    old = radar.config._config_mtime
    radar.config._config_mtime = None
    yield
    radar.config._config_mtime = old


@pytest.fixture(autouse=True)
def reset_scheduler_globals():
    """Reset scheduler globals before/after each test."""
    sched_mod._scheduler = None
    sched_mod._event_queue = []
    sched_mod._last_heartbeat = None
    yield
    if sched_mod._scheduler is not None:
        try:
            sched_mod._scheduler.shutdown(wait=False)
        except Exception:
            pass
    sched_mod._scheduler = None
    sched_mod._event_queue = []
    sched_mod._last_heartbeat = None


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """Create a temporary config file and point RADAR_CONFIG_PATH at it."""
    cfg_file = tmp_path / "radar.yaml"
    cfg_file.write_text(yaml.dump({"llm": {"model": "original-model"}}))
    monkeypatch.setenv("RADAR_CONFIG_PATH", str(cfg_file))
    monkeypatch.setenv("RADAR_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir(exist_ok=True)
    radar.config._config = None
    radar.config.reset_data_paths()
    return cfg_file


@pytest.fixture
def tools_dir(tmp_path):
    """Create a temporary external tools directory."""
    d = tmp_path / "ext_tools"
    d.mkdir()
    return d


@pytest.fixture(autouse=True)
def reset_external_tool_tracking():
    """Reset external tool tracking state before/after each test."""
    old_sources = tools_mod._external_tool_sources.copy()
    old_mtimes = tools_mod._external_tool_mtimes.copy()
    old_external = tools_mod._external_tools.copy()
    tools_mod._external_tool_sources.clear()
    tools_mod._external_tool_mtimes.clear()
    yield
    # Unregister any external tools added during the test
    for file_key, names in tools_mod._external_tool_sources.items():
        for name in names:
            tools_mod._registry.pop(name, None)
    tools_mod._external_tool_sources.clear()
    tools_mod._external_tool_mtimes.clear()
    tools_mod._external_tools.clear()
    tools_mod._external_tools.update(old_external)
    tools_mod._external_tool_sources.update(old_sources)
    tools_mod._external_tool_mtimes.update(old_mtimes)


# ---------------------------------------------------------------------------
# config_file_changed()
# ---------------------------------------------------------------------------


class TestConfigFileChanged:
    def test_no_config_file_returns_false(self, monkeypatch):
        monkeypatch.delenv("RADAR_CONFIG_PATH", raising=False)
        monkeypatch.chdir("/tmp")
        assert radar.config.config_file_changed() is False

    def test_first_call_sets_baseline_returns_false(self, config_file):
        assert radar.config._config_mtime is None
        assert radar.config.config_file_changed() is False
        assert radar.config._config_mtime is not None

    def test_unchanged_file_returns_false(self, config_file):
        # First call sets baseline
        radar.config.config_file_changed()
        # Second call — no change
        assert radar.config.config_file_changed() is False

    def test_modified_file_returns_true(self, config_file):
        # Set baseline
        radar.config.config_file_changed()
        # Modify the file (ensure mtime changes)
        time_mod.sleep(0.05)
        config_file.write_text(yaml.dump({"llm": {"model": "new-model"}}))
        assert radar.config.config_file_changed() is True

    def test_os_error_returns_false(self, config_file):
        radar.config.config_file_changed()  # set baseline
        # Patch get_config_path to return a path that will fail on stat()
        fake_path = tmp_path = Path("/nonexistent/radar.yaml")
        with patch("radar.config.get_config_path", return_value=fake_path):
            assert radar.config.config_file_changed() is False


# ---------------------------------------------------------------------------
# reload_config() stamps mtime
# ---------------------------------------------------------------------------


class TestReloadConfigMtime:
    def test_reload_stamps_mtime(self, config_file):
        radar.config._config_mtime = None
        radar.config.reload_config()
        assert radar.config._config_mtime is not None

    def test_get_config_stamps_mtime_on_first_load(self, config_file):
        radar.config._config = None
        radar.config._config_mtime = None
        radar.config.get_config()
        assert radar.config._config_mtime is not None

    def test_reload_after_change_resets_mtime(self, config_file):
        radar.config.reload_config()
        old_mtime = radar.config._config_mtime

        time_mod.sleep(0.05)
        config_file.write_text(yaml.dump({"llm": {"model": "changed"}}))

        radar.config.reload_config()
        assert radar.config._config_mtime != old_mtime


# ---------------------------------------------------------------------------
# _check_config_reload()
# ---------------------------------------------------------------------------


class TestCheckConfigReload:
    def test_no_change_is_noop(self, config_file):
        radar.config.get_config()  # set baseline
        with (
            patch.object(sched_mod, "_log_heartbeat") as m_log,
            patch("radar.hooks.unregister_hooks_by_source") as m_unreg,
        ):
            sched_mod._check_config_reload()
            # Should not log or reload hooks
            m_unreg.assert_not_called()
            # _log_heartbeat not called for "Config file changed"
            for call in m_log.call_args_list:
                assert "changed" not in call[0][0].lower()

    def test_change_triggers_reload(self, config_file):
        radar.config.get_config()  # set baseline

        time_mod.sleep(0.05)
        config_file.write_text(yaml.dump({"llm": {"model": "reloaded"}}))

        with (
            patch.object(sched_mod, "_log_heartbeat") as m_log,
            patch("radar.hooks.unregister_hooks_by_source", return_value=1),
            patch("radar.hooks_builtin.load_config_hooks", return_value=2),
            patch("radar.tools.reload_external_tools", return_value={"added": [], "removed": [], "reloaded": []}),
        ):
            sched_mod._check_config_reload()
            # Should log config change
            log_messages = [call[0][0] for call in m_log.call_args_list]
            assert any("changed" in msg.lower() for msg in log_messages)

    def test_hooks_cleared_and_reregistered(self, config_file):
        radar.config.get_config()  # set baseline

        time_mod.sleep(0.05)
        config_file.write_text(yaml.dump({"llm": {"model": "v2"}}))

        with (
            patch.object(sched_mod, "_log_heartbeat"),
            patch("radar.hooks.unregister_hooks_by_source", return_value=3) as m_unreg,
            patch("radar.hooks_builtin.load_config_hooks", return_value=5) as m_load,
            patch("radar.tools.reload_external_tools", return_value={"added": [], "removed": [], "reloaded": []}),
        ):
            sched_mod._check_config_reload()
            m_unreg.assert_called_once_with("config")
            m_load.assert_called_once()

    def test_external_tools_reloaded(self, config_file):
        radar.config.get_config()  # set baseline

        time_mod.sleep(0.05)
        config_file.write_text(yaml.dump({"llm": {"model": "v3"}}))

        tool_result = {"added": ["new_tool"], "removed": [], "reloaded": []}
        with (
            patch.object(sched_mod, "_log_heartbeat") as m_log,
            patch("radar.hooks.unregister_hooks_by_source", return_value=0),
            patch("radar.hooks_builtin.load_config_hooks", return_value=0),
            patch("radar.tools.reload_external_tools", return_value=tool_result),
        ):
            sched_mod._check_config_reload()
            log_messages = [call[0][0] for call in m_log.call_args_list]
            assert any("external tools" in msg.lower() for msg in log_messages)


# ---------------------------------------------------------------------------
# _heartbeat_tick() calls config reload
# ---------------------------------------------------------------------------


class TestHeartbeatTickConfigReload:
    @pytest.fixture
    def _mock_tick_deps(self):
        """Patch all external dependencies of _heartbeat_tick."""
        with (
            patch.object(sched_mod, "_is_quiet_hours", return_value=False),
            patch.object(sched_mod, "_log_heartbeat"),
            patch.object(sched_mod, "_check_config_reload") as m_reload,
            patch.object(sched_mod, "_get_heartbeat_conversation_id", return_value="conv-1"),
            patch("radar.scheduled_tasks.get_due_tasks", return_value=[]),
            patch("radar.scheduled_tasks.mark_task_executed"),
            patch("radar.tools.calendar._get_reminders", return_value=""),
            patch("radar.agent.run"),
        ):
            yield {"reload": m_reload}

    def test_tick_calls_config_reload(self, _mock_tick_deps):
        sched_mod._heartbeat_tick()
        _mock_tick_deps["reload"].assert_called_once()

    def test_tick_continues_if_reload_raises(self):
        """Config reload errors don't prevent the heartbeat from running."""
        with (
            patch.object(sched_mod, "_is_quiet_hours", return_value=False),
            patch.object(sched_mod, "_log_heartbeat"),
            patch.object(sched_mod, "_check_config_reload", side_effect=RuntimeError("reload fail")),
            patch.object(sched_mod, "_get_heartbeat_conversation_id", return_value="conv-1"),
            patch("radar.scheduled_tasks.get_due_tasks", return_value=[]),
            patch("radar.scheduled_tasks.mark_task_executed"),
            patch("radar.tools.calendar._get_reminders", return_value=""),
            patch("radar.agent.run") as m_run,
        ):
            sched_mod._heartbeat_tick()
            m_run.assert_called_once()

    def test_tick_skips_reload_during_quiet_hours(self):
        """Config reload should not run during quiet hours."""
        with (
            patch.object(sched_mod, "_is_quiet_hours", return_value=True),
            patch.object(sched_mod, "_log_heartbeat"),
            patch.object(sched_mod, "_check_config_reload") as m_reload,
            patch("radar.agent.run") as m_run,
        ):
            sched_mod._heartbeat_tick()
            m_reload.assert_not_called()
            m_run.assert_not_called()


# ---------------------------------------------------------------------------
# reload_external_tools()
# ---------------------------------------------------------------------------

TOOL_TEMPLATE = '''from radar.tools import tool

@tool(
    name="{name}",
    description="Test tool {name}",
    parameters={{"arg": {{"type": "string", "description": "arg"}}}},
)
def {name}(arg: str = "") -> str:
    return "result from {name}"
'''


class TestReloadExternalTools:
    def test_add_new_tool(self, tools_dir, monkeypatch, isolated_data_dir):
        """New .py file in extra_dir gets loaded."""
        monkeypatch.setattr("radar.config.get_config", lambda: MagicMock(
            tools=MagicMock(extra_dirs=[str(tools_dir)]),
        ))
        monkeypatch.setattr("radar.config.get_data_paths", lambda: MagicMock(
            tools=isolated_data_dir / "tools",
        ))
        (isolated_data_dir / "tools").mkdir(exist_ok=True)

        # Write a tool file
        (tools_dir / "greet.py").write_text(TOOL_TEMPLATE.format(name="greet"))

        result = tools_mod.reload_external_tools()
        assert "greet" in result["added"]
        assert "greet" in tools_mod._registry

    def test_remove_deleted_tool(self, tools_dir, monkeypatch, isolated_data_dir):
        """Tool unregistered when its file is deleted."""
        monkeypatch.setattr("radar.config.get_config", lambda: MagicMock(
            tools=MagicMock(extra_dirs=[str(tools_dir)]),
        ))
        monkeypatch.setattr("radar.config.get_data_paths", lambda: MagicMock(
            tools=isolated_data_dir / "tools",
        ))
        (isolated_data_dir / "tools").mkdir(exist_ok=True)

        # Create and load a tool
        tool_file = tools_dir / "ephemeral.py"
        tool_file.write_text(TOOL_TEMPLATE.format(name="ephemeral"))
        tools_mod.reload_external_tools()
        assert "ephemeral" in tools_mod._registry

        # Delete the file and reload
        tool_file.unlink()
        result = tools_mod.reload_external_tools()
        assert "ephemeral" in result["removed"]
        assert "ephemeral" not in tools_mod._registry

    def test_reload_changed_tool(self, tools_dir, monkeypatch, isolated_data_dir):
        """Changed file gets re-imported."""
        monkeypatch.setattr("radar.config.get_config", lambda: MagicMock(
            tools=MagicMock(extra_dirs=[str(tools_dir)]),
        ))
        monkeypatch.setattr("radar.config.get_data_paths", lambda: MagicMock(
            tools=isolated_data_dir / "tools",
        ))
        (isolated_data_dir / "tools").mkdir(exist_ok=True)

        tool_file = tools_dir / "mutable.py"
        tool_file.write_text(TOOL_TEMPLATE.format(name="mutable"))
        tools_mod.reload_external_tools()
        assert "mutable" in tools_mod._registry

        # Modify the file
        time_mod.sleep(0.05)
        tool_file.write_text(TOOL_TEMPLATE.format(name="mutable").replace(
            "result from mutable", "updated result"
        ))

        result = tools_mod.reload_external_tools()
        assert "mutable" in result["reloaded"]
        assert "mutable" in tools_mod._registry

    def test_unchanged_tool_preserved(self, tools_dir, monkeypatch, isolated_data_dir):
        """Unchanged file's function object is the same instance."""
        monkeypatch.setattr("radar.config.get_config", lambda: MagicMock(
            tools=MagicMock(extra_dirs=[str(tools_dir)]),
        ))
        monkeypatch.setattr("radar.config.get_data_paths", lambda: MagicMock(
            tools=isolated_data_dir / "tools",
        ))
        (isolated_data_dir / "tools").mkdir(exist_ok=True)

        tool_file = tools_dir / "stable.py"
        tool_file.write_text(TOOL_TEMPLATE.format(name="stable"))
        tools_mod.reload_external_tools()
        original_func = tools_mod._registry["stable"][0]

        # Reload without changing the file
        result = tools_mod.reload_external_tools()
        assert result["added"] == []
        assert result["removed"] == []
        assert result["reloaded"] == []
        assert tools_mod._registry["stable"][0] is original_func

    def test_skip_underscore_files(self, tools_dir, monkeypatch, isolated_data_dir):
        """Files starting with _ are skipped."""
        monkeypatch.setattr("radar.config.get_config", lambda: MagicMock(
            tools=MagicMock(extra_dirs=[str(tools_dir)]),
        ))
        monkeypatch.setattr("radar.config.get_data_paths", lambda: MagicMock(
            tools=isolated_data_dir / "tools",
        ))
        (isolated_data_dir / "tools").mkdir(exist_ok=True)

        (tools_dir / "_helper.py").write_text(TOOL_TEMPLATE.format(name="_helper"))
        result = tools_mod.reload_external_tools()
        assert result["added"] == []


# ---------------------------------------------------------------------------
# load_external_tools() source tracking
# ---------------------------------------------------------------------------


class TestLoadExternalToolsTracking:
    def test_tracks_sources_and_mtimes(self, tools_dir):
        tool_file = tools_dir / "tracked.py"
        tool_file.write_text(TOOL_TEMPLATE.format(name="tracked"))
        tools_mod.load_external_tools([str(tools_dir)])

        file_key = str(tool_file)
        assert file_key in tools_mod._external_tool_sources
        assert "tracked" in tools_mod._external_tool_sources[file_key]
        assert file_key in tools_mod._external_tool_mtimes
