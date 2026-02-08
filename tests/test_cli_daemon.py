"""Tests for daemon mode and systemd service commands."""

import os
import signal
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from click.testing import CliRunner

from radar.cli import (
    SYSTEMD_UNIT_TEMPLATE,
    _daemonize,
    _get_unit_path,
    _is_daemon_running,
    cli,
)


@pytest.fixture
def runner():
    return CliRunner()


# ===== _daemonize() =====


class TestDaemonize:
    """Tests for the double-fork daemonize helper."""

    @patch("radar.cli.os.dup2")
    @patch("builtins.open")
    @patch("radar.cli.os.setsid")
    @patch("radar.cli.os.fork")
    def test_first_fork_parent_exits(self, mock_fork, mock_setsid, mock_open, mock_dup2):
        """First fork parent (pid > 0) calls sys.exit(0)."""
        mock_fork.return_value = 42  # Parent gets child PID
        with pytest.raises(SystemExit) as exc:
            _daemonize(Path("/tmp/test.log"))
        assert exc.value.code == 0
        mock_fork.assert_called_once()
        mock_setsid.assert_not_called()

    @patch("radar.cli.os.dup2")
    @patch("builtins.open")
    @patch("radar.cli.os.setsid")
    @patch("radar.cli.os.fork")
    def test_second_fork_parent_exits(self, mock_fork, mock_setsid, mock_open, mock_dup2):
        """Second fork parent exits after setsid."""
        mock_fork.side_effect = [0, 42]  # Child in first fork, parent in second
        mock_open.return_value = MagicMock(fileno=MagicMock(return_value=99))
        with pytest.raises(SystemExit) as exc:
            _daemonize(Path("/tmp/test.log"))
        assert exc.value.code == 0
        assert mock_fork.call_count == 2
        mock_setsid.assert_called_once()

    @patch("radar.cli.os.dup2")
    @patch("builtins.open")
    @patch("radar.cli.os.setsid")
    @patch("radar.cli.os.fork")
    def test_grandchild_redirects_fds(self, mock_fork, mock_setsid, mock_open, mock_dup2):
        """Grandchild process redirects stdin/stdout/stderr."""
        mock_fork.side_effect = [0, 0]  # Child in both forks
        devnull_fd = MagicMock(fileno=MagicMock(return_value=10))
        log_fd = MagicMock(fileno=MagicMock(return_value=11))
        mock_open.side_effect = [devnull_fd, log_fd]

        # Mock sys.stdin/stdout/stderr since pytest replaces them with pseudofiles
        mock_stdin = MagicMock(fileno=MagicMock(return_value=0))
        mock_stdout = MagicMock(fileno=MagicMock(return_value=1))
        mock_stderr = MagicMock(fileno=MagicMock(return_value=2))
        with patch("radar.cli.sys.stdin", mock_stdin), \
             patch("radar.cli.sys.stdout", mock_stdout), \
             patch("radar.cli.sys.stderr", mock_stderr):
            _daemonize(Path("/tmp/test.log"))

        # Should open devnull for stdin and log file for stdout/stderr
        assert mock_open.call_count == 2
        assert mock_dup2.call_count == 3


# ===== start --foreground =====


class TestStartForeground:
    """Tests for the --foreground flag on radar start."""

    @patch("radar.cli.get_config")
    @patch("radar.cli._is_daemon_running", return_value=(False, None))
    @patch("radar.cli.get_data_paths")
    def test_foreground_flag_skips_daemonize(self, mock_paths, mock_running, mock_config, runner, tmp_path):
        """--foreground should not call _daemonize."""
        pid_file = tmp_path / "radar.pid"
        mock_paths.return_value = MagicMock(
            pid_file=pid_file,
            log_file=tmp_path / "radar.log",
        )
        mock_config.return_value = MagicMock(
            web=MagicMock(host="127.0.0.1", port=8420, auth_token=""),
            heartbeat=MagicMock(interval_minutes=15),
            watch_paths=[],
        )

        with patch("radar.cli._daemonize") as mock_daemon, \
             patch("radar.web.run_server", side_effect=KeyboardInterrupt):
            result = runner.invoke(cli, ["start", "--foreground"])

            mock_daemon.assert_not_called()

    @patch("radar.cli.get_config")
    @patch("radar.cli._is_daemon_running", return_value=(False, None))
    @patch("radar.cli.get_data_paths")
    def test_daemon_mode_calls_daemonize(self, mock_paths, mock_running, mock_config, runner, tmp_path):
        """Without --foreground, _daemonize should be called."""
        pid_file = tmp_path / "radar.pid"
        mock_paths.return_value = MagicMock(
            pid_file=pid_file,
            log_file=tmp_path / "radar.log",
        )
        mock_config.return_value = MagicMock(
            web=MagicMock(host="127.0.0.1", port=8420, auth_token=""),
            heartbeat=MagicMock(interval_minutes=15),
            watch_paths=[],
        )

        with patch("radar.cli._daemonize") as mock_daemon, \
             patch.dict("sys.modules", {
                "radar.scheduler": MagicMock(),
                "radar.watchers": MagicMock(),
                "radar.logging": MagicMock(),
             }):
            with patch("radar.web.run_server", side_effect=KeyboardInterrupt):
                result = runner.invoke(cli, ["start"])

            mock_daemon.assert_called_once()

    @patch("radar.cli.get_config")
    @patch("radar.cli._is_daemon_running", return_value=(True, 1234))
    def test_start_rejects_when_already_running(self, mock_running, mock_config, runner):
        """Start should fail if daemon is already running."""
        mock_config.return_value = MagicMock(
            web=MagicMock(host="127.0.0.1", port=8420, auth_token=""),
        )
        result = runner.invoke(cli, ["start"])
        assert result.exit_code == 1
        assert "already running" in result.output


# ===== stop wait loop =====


class TestStopWaitLoop:
    """Tests for the stop command's wait-for-exit loop."""

    @patch("radar.cli.get_data_paths")
    @patch("radar.cli.time.sleep")
    @patch("radar.cli.os.kill")
    @patch("radar.cli._is_daemon_running", return_value=(True, 1234))
    def test_stop_waits_for_exit(self, mock_running, mock_kill, mock_sleep, mock_paths, runner, tmp_path):
        """Stop should poll until process exits."""
        pid_file = tmp_path / "radar.pid"
        pid_file.write_text("1234")
        mock_paths.return_value = MagicMock(pid_file=pid_file)

        # First kill sends SIGTERM, second kill (poll) finds process, third poll gets ProcessLookupError
        mock_kill.side_effect = [
            None,  # SIGTERM succeeds
            None,  # First poll - still running
            ProcessLookupError,  # Second poll - gone
        ]

        result = runner.invoke(cli, ["stop"])
        assert result.exit_code == 0
        assert "Daemon stopped" in result.output

        # Verify SIGTERM was sent, then polled with signal 0
        assert mock_kill.call_args_list[0] == call(1234, signal.SIGTERM)
        assert mock_kill.call_args_list[1] == call(1234, 0)

    @patch("radar.cli.get_data_paths")
    @patch("radar.cli.os.kill")
    @patch("radar.cli._is_daemon_running", return_value=(True, 1234))
    def test_stop_handles_already_dead(self, mock_running, mock_kill, mock_paths, runner, tmp_path):
        """Stop should handle process already gone."""
        pid_file = tmp_path / "radar.pid"
        pid_file.write_text("1234")
        mock_paths.return_value = MagicMock(pid_file=pid_file)

        mock_kill.side_effect = ProcessLookupError

        result = runner.invoke(cli, ["stop"])
        assert result.exit_code == 0
        assert "Process not found" in result.output

    @patch("radar.cli._is_daemon_running", return_value=(False, None))
    def test_stop_when_not_running(self, mock_running, runner):
        """Stop should fail if daemon isn't running."""
        result = runner.invoke(cli, ["stop"])
        assert result.exit_code == 1
        assert "not running" in result.output


# ===== service commands =====


class TestServiceInstall:
    """Tests for radar service install."""

    @patch("radar.cli.subprocess.run")
    @patch("radar.cli.shutil.which", return_value="/usr/local/bin/radar")
    @patch("radar.cli.get_data_paths")
    @patch("radar.cli.get_config")
    def test_generates_unit_file(self, mock_config, mock_paths, mock_which, mock_run, tmp_path):
        """Install should write a valid systemd unit file."""
        unit_dir = tmp_path / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        unit_path = unit_dir / "radar.service"

        mock_config.return_value = MagicMock(
            web=MagicMock(host="127.0.0.1", port=8420),
        )
        mock_paths.return_value = MagicMock(base=tmp_path / "data")
        mock_run.return_value = MagicMock(returncode=0)

        with patch("radar.cli._get_unit_path", return_value=unit_path):
            runner = CliRunner()
            result = runner.invoke(cli, ["service", "install"])

        assert result.exit_code == 0
        assert unit_path.exists()

        content = unit_path.read_text()
        assert "/usr/local/bin/radar start --foreground" in content
        assert "Type=simple" in content
        assert "Restart=on-failure" in content
        assert "WantedBy=default.target" in content

    @patch("radar.cli.subprocess.run")
    @patch("radar.cli.shutil.which", return_value="/usr/local/bin/radar")
    @patch("radar.cli.get_data_paths")
    @patch("radar.cli.get_config")
    def test_install_runs_systemctl_commands(self, mock_config, mock_paths, mock_which, mock_run, tmp_path):
        """Install should daemon-reload, enable, and start."""
        unit_dir = tmp_path / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        unit_path = unit_dir / "radar.service"

        mock_config.return_value = MagicMock(
            web=MagicMock(host="127.0.0.1", port=8420),
        )
        mock_paths.return_value = MagicMock(base=tmp_path / "data")
        mock_run.return_value = MagicMock(returncode=0)

        with patch("radar.cli._get_unit_path", return_value=unit_path):
            runner = CliRunner()
            result = runner.invoke(cli, ["service", "install"])

        assert result.exit_code == 0
        systemctl_calls = [c for c in mock_run.call_args_list]
        assert call(["systemctl", "--user", "daemon-reload"], check=True) in systemctl_calls
        assert call(["systemctl", "--user", "enable", "radar.service"], check=True) in systemctl_calls
        assert call(["systemctl", "--user", "start", "radar.service"], check=True) in systemctl_calls

    @patch("radar.cli.subprocess.run")
    @patch("radar.cli.shutil.which", return_value="/usr/local/bin/radar")
    @patch("radar.cli.get_data_paths")
    @patch("radar.cli.get_config")
    def test_install_custom_host_port(self, mock_config, mock_paths, mock_which, mock_run, tmp_path):
        """Install with custom host/port should use them in ExecStart."""
        unit_dir = tmp_path / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        unit_path = unit_dir / "radar.service"

        mock_config.return_value = MagicMock(
            web=MagicMock(host="127.0.0.1", port=8420),
        )
        mock_paths.return_value = MagicMock(base=tmp_path / "data")
        mock_run.return_value = MagicMock(returncode=0)

        with patch("radar.cli._get_unit_path", return_value=unit_path):
            runner = CliRunner()
            result = runner.invoke(cli, ["service", "install", "-h", "0.0.0.0", "-p", "9000"])

        content = unit_path.read_text()
        assert "-h 0.0.0.0 -p 9000" in content

    def test_install_fails_without_radar_binary(self):
        """Install should fail if radar binary is not in PATH."""
        with patch("radar.cli.shutil.which", return_value=None):
            runner = CliRunner()
            result = runner.invoke(cli, ["service", "install"])
        assert result.exit_code == 1
        assert "Could not find" in result.output


class TestServiceUninstall:
    """Tests for radar service uninstall."""

    @patch("radar.cli.subprocess.run")
    def test_uninstall_removes_unit(self, mock_run, tmp_path):
        """Uninstall should stop, disable, remove, and reload."""
        unit_dir = tmp_path / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        unit_path = unit_dir / "radar.service"
        unit_path.write_text("[Unit]\nDescription=Test\n")

        mock_run.return_value = MagicMock(returncode=0)

        with patch("radar.cli._get_unit_path", return_value=unit_path):
            runner = CliRunner()
            result = runner.invoke(cli, ["service", "uninstall"])

        assert result.exit_code == 0
        assert not unit_path.exists()
        assert "uninstalled" in result.output

        systemctl_calls = [c for c in mock_run.call_args_list]
        assert call(["systemctl", "--user", "stop", "radar.service"], check=False) in systemctl_calls
        assert call(["systemctl", "--user", "disable", "radar.service"], check=False) in systemctl_calls
        assert call(["systemctl", "--user", "daemon-reload"], check=True) in systemctl_calls

    def test_uninstall_when_not_installed(self, tmp_path):
        """Uninstall should fail if unit file doesn't exist."""
        unit_path = tmp_path / "nonexistent" / "radar.service"

        with patch("radar.cli._get_unit_path", return_value=unit_path):
            runner = CliRunner()
            result = runner.invoke(cli, ["service", "uninstall"])

        assert result.exit_code == 1
        assert "not installed" in result.output


class TestServiceStatus:
    """Tests for radar service status."""

    @patch("radar.cli.subprocess.run")
    def test_status_shows_output(self, mock_run):
        """Status should show systemctl output."""
        mock_run.return_value = MagicMock(
            stdout="● radar.service - Radar AI Assistant\n   Active: active (running)",
            stderr="",
            returncode=0,
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["service", "status"])
        assert "radar.service" in result.output

    @patch("radar.cli.subprocess.run")
    def test_status_returns_systemctl_exit_code(self, mock_run):
        """Status should forward systemctl's exit code."""
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="Unit radar.service could not be found.",
            returncode=4,
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["service", "status"])
        assert result.exit_code == 4


# ===== unit template =====


class TestUnitTemplate:
    """Tests for the systemd unit template."""

    def test_template_has_required_sections(self):
        """Unit template should have Unit, Service, and Install sections."""
        assert "[Unit]" in SYSTEMD_UNIT_TEMPLATE
        assert "[Service]" in SYSTEMD_UNIT_TEMPLATE
        assert "[Install]" in SYSTEMD_UNIT_TEMPLATE

    def test_template_format_placeholders(self):
        """Template should accept exec_start and data_dir placeholders."""
        result = SYSTEMD_UNIT_TEMPLATE.format(
            exec_start="/usr/bin/radar start --foreground",
            data_dir="/home/user/.local/share/radar",
        )
        assert "/usr/bin/radar start --foreground" in result
        assert "RADAR_DATA_DIR=/home/user/.local/share/radar" in result


# ===== _get_unit_path =====


class TestGetUnitPath:
    """Tests for unit path helper."""

    def test_returns_systemd_user_path(self):
        """Should return path under ~/.config/systemd/user/."""
        path = _get_unit_path()
        assert path.name == "radar.service"
        assert "systemd" in str(path)
        assert "user" in str(path)


# ===== delete command =====


class TestDeleteCommand:
    """Tests for radar delete."""

    @patch("radar.memory.get_messages", return_value=[{"content": "hello"}])
    @patch("radar.memory.delete_conversation", return_value=(True, "Conversation abc deleted"))
    def test_delete_with_force(self, mock_del, mock_msgs, runner):
        result = runner.invoke(cli, ["delete", "abc", "--force"])
        assert result.exit_code == 0
        assert "deleted" in result.output.lower()
        mock_del.assert_called_once_with("abc")

    @patch("radar.memory.get_messages", return_value=[])
    @patch("radar.memory.delete_conversation", return_value=(False, "Conversation xyz not found"))
    def test_nonexistent_conversation(self, mock_del, mock_msgs, runner):
        result = runner.invoke(cli, ["delete", "xyz", "--force"])
        assert result.exit_code == 1
        assert "not found" in result.output

    @patch("radar.memory.get_messages", return_value=[{"content": "hello"}])
    @patch("radar.memory.delete_conversation", return_value=(True, "Conversation abc deleted"))
    def test_delete_with_confirmation_yes(self, mock_del, mock_msgs, runner):
        result = runner.invoke(cli, ["delete", "abc"], input="y\n")
        assert result.exit_code == 0
        assert "deleted" in result.output.lower()

    @patch("radar.memory.get_messages", return_value=[{"content": "hello"}])
    @patch("radar.memory.delete_conversation")
    def test_delete_aborted(self, mock_del, mock_msgs, runner):
        result = runner.invoke(cli, ["delete", "abc"], input="n\n")
        assert result.exit_code == 1
        mock_del.assert_not_called()

    @patch("radar.memory.get_messages", return_value=[{"content": "heartbeat"}])
    @patch("radar.memory.delete_conversation", return_value=(False, "Cannot delete the heartbeat conversation"))
    def test_heartbeat_rejection(self, mock_del, mock_msgs, runner):
        result = runner.invoke(cli, ["delete", "hb-id", "--force"])
        assert result.exit_code == 1
        assert "heartbeat" in result.output.lower()
