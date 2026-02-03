"""Security utilities for Radar tools."""

from pathlib import Path

# Sensitive paths that should never be read or written
SENSITIVE_PATH_PATTERNS = [
    # SSH
    ".ssh",
    # GPG
    ".gnupg",
    ".gpg",
    # Cloud credentials
    ".aws",
    ".azure",
    ".config/gcloud",
    ".kube",
    # Password managers
    ".password-store",
    ".local/share/keyrings",
    # Browser data
    ".mozilla",
    ".chrome",
    ".config/chromium",
    ".config/google-chrome",
    # Application secrets
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".docker/config.json",
    ".git-credentials",
    # Shell history (could contain secrets)
    ".bash_history",
    ".zsh_history",
    ".python_history",
    # Environment files often contain secrets
    ".env",
]

# Additional write-only restrictions (ok to read, not to write)
WRITE_BLOCKED_PATTERNS = [
    # Shell configs (persistence vector)
    ".bashrc",
    ".bash_profile",
    ".zshrc",
    ".zprofile",
    ".profile",
    # Autostart locations
    ".config/autostart",
    ".local/share/applications",
    # Cron
    ".cron",
    ".crontab",
]

# System paths that should never be accessed
SYSTEM_BLOCKED_PATHS = [
    "/etc/passwd",
    "/etc/shadow",
    "/etc/sudoers",
]


def _normalize_path(path: str | Path) -> Path:
    """Normalize and resolve a path."""
    return Path(path).expanduser().resolve()


def _is_under_home(path: Path) -> bool:
    """Check if path is under user's home directory."""
    home = Path.home().resolve()
    try:
        path.relative_to(home)
        return True
    except ValueError:
        return False


def _matches_pattern(path: Path, patterns: list[str]) -> str | None:
    """Check if path matches any blocked pattern. Returns matched pattern or None."""
    path_str = str(path)
    home = str(Path.home().resolve())

    # Check relative to home
    if path_str.startswith(home):
        relative = path_str[len(home):].lstrip("/")
        for pattern in patterns:
            # Check if path starts with pattern or contains it as a component
            if relative.startswith(pattern) or f"/{pattern}" in f"/{relative}":
                return pattern
            # Check if any parent directory matches
            parts = Path(relative).parts
            for i, part in enumerate(parts):
                partial = "/".join(parts[:i+1])
                if partial == pattern or part == pattern:
                    return pattern

    return None


def check_path_security(path: str | Path, operation: str = "read") -> tuple[bool, str]:
    """Check if a path is safe to access.

    Args:
        path: Path to check
        operation: "read" or "write"

    Returns:
        Tuple of (is_safe, reason). If is_safe is False, reason explains why.
    """
    try:
        resolved = _normalize_path(path)
    except (OSError, ValueError) as e:
        return False, f"Invalid path: {e}"

    path_str = str(resolved)

    # Check system paths
    for sys_path in SYSTEM_BLOCKED_PATHS:
        if path_str == sys_path or path_str.startswith(sys_path + "/"):
            return False, f"Access to system path blocked: {sys_path}"

    # Check sensitive patterns (blocked for both read and write)
    matched = _matches_pattern(resolved, SENSITIVE_PATH_PATTERNS)
    if matched:
        return False, f"Access to sensitive path blocked: {matched}"

    # Check write-specific blocks
    if operation == "write":
        matched = _matches_pattern(resolved, WRITE_BLOCKED_PATTERNS)
        if matched:
            return False, f"Write to sensitive path blocked: {matched}"

    return True, ""


def is_path_sensitive(path: str | Path) -> bool:
    """Quick check if a path is sensitive (for warnings)."""
    safe, _ = check_path_security(path, "read")
    return not safe


def get_blocked_patterns() -> dict[str, list[str]]:
    """Get the current blocked patterns (for UI display)."""
    return {
        "sensitive": SENSITIVE_PATH_PATTERNS.copy(),
        "write_blocked": WRITE_BLOCKED_PATTERNS.copy(),
        "system": SYSTEM_BLOCKED_PATHS.copy(),
    }


# Dangerous command patterns for exec tool
DANGEROUS_COMMAND_PATTERNS = [
    # Destructive file operations
    "rm -rf",
    "rm -fr",
    "rmdir",
    "> /dev/",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",  # Fork bomb
    # System modification
    "chmod 777",
    "chmod -R",
    "chown -R",
    "sudo",
    "su ",
    "doas",
    # Network exfiltration
    "curl",
    "wget",
    "nc ",
    "netcat",
    "ncat",
    # Reverse shells
    "/dev/tcp/",
    "/dev/udp/",
    "bash -i",
    "sh -i",
    # Package managers (could install malware)
    "pip install",
    "npm install",
    "apt install",
    "apt-get install",
    "yum install",
    "brew install",
    # Cron/persistence
    "crontab",
    " at ",  # Schedule command (with leading space to avoid matching 'cat')
    "systemctl enable",
    # SSH
    "ssh ",
    "scp ",
    # Process/system
    "kill -9",
    "killall",
    "shutdown",
    "reboot",
    "init ",
]

# Commands that are safe to run without restrictions
SAFE_COMMAND_PREFIXES = [
    "ls",
    "cat",
    "head",
    "tail",
    "grep",
    "find",
    "wc",
    "sort",
    "uniq",
    "echo",
    "pwd",
    "date",
    "whoami",
    "hostname",
    "uname",
    "env",
    "printenv",
    "which",
    "type",
    "file",
    "stat",
    "du",
    "df",
    "free",
    "uptime",
    "ps",
    "top",
    "htop",
    "tree",
    "less",
    "more",
]


def check_command_security(command: str) -> tuple[bool, str, str]:
    """Check if a command is safe to execute.

    Args:
        command: Shell command to check

    Returns:
        Tuple of (is_safe, risk_level, reason)
        risk_level is one of: "safe", "moderate", "dangerous"
    """
    command_lower = command.lower().strip()

    # Check for dangerous patterns
    for pattern in DANGEROUS_COMMAND_PATTERNS:
        if pattern.lower() in command_lower:
            return False, "dangerous", f"Dangerous pattern detected: {pattern}"

    # Check if it's a known safe command
    first_word = command_lower.split()[0] if command_lower else ""
    # Strip path prefix
    if "/" in first_word:
        first_word = first_word.split("/")[-1]

    if first_word in SAFE_COMMAND_PREFIXES:
        return True, "safe", ""

    # Unknown command - moderate risk
    return True, "moderate", "Unknown command - use caution"


def get_dangerous_patterns() -> list[str]:
    """Get list of dangerous command patterns."""
    return DANGEROUS_COMMAND_PATTERNS.copy()
