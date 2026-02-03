"""Configuration management for Radar."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class OllamaConfig:
    """Ollama API configuration."""

    base_url: str = "http://localhost:11434"
    model: str = "qwen3:latest"


@dataclass
class NotifyConfig:
    """Notification (ntfy) configuration."""

    url: str = "https://ntfy.sh"
    topic: str = ""


@dataclass
class ToolsConfig:
    """Tools configuration."""

    max_file_size: int = 102400  # 100KB
    exec_timeout: int = 30


@dataclass
class HeartbeatConfig:
    """Heartbeat/scheduler configuration."""

    interval_minutes: int = 15
    quiet_hours_start: str = "23:00"
    quiet_hours_end: str = "07:00"


@dataclass
class WebConfig:
    """Web server configuration."""

    host: str = "127.0.0.1"
    port: int = 8420


@dataclass
class Config:
    """Main configuration container."""

    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    notifications: NotifyConfig = field(default_factory=NotifyConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    heartbeat: HeartbeatConfig = field(default_factory=HeartbeatConfig)
    web: WebConfig = field(default_factory=WebConfig)
    system_prompt: str = ""
    max_tool_iterations: int = 10
    embedding_model: str = "nomic-embed-text"
    watch_paths: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        """Create Config from dictionary."""
        ollama_data = data.get("ollama", {})
        notify_data = data.get("notifications", {})
        tools_data = data.get("tools", {})
        heartbeat_data = data.get("heartbeat", {})
        web_data = data.get("web", {})

        return cls(
            ollama=OllamaConfig(
                base_url=ollama_data.get("base_url", OllamaConfig.base_url),
                model=ollama_data.get("model", OllamaConfig.model),
            ),
            notifications=NotifyConfig(
                url=notify_data.get("url", NotifyConfig.url),
                topic=notify_data.get("topic", NotifyConfig.topic),
            ),
            tools=ToolsConfig(
                max_file_size=tools_data.get("max_file_size", ToolsConfig.max_file_size),
                exec_timeout=tools_data.get("exec_timeout", ToolsConfig.exec_timeout),
            ),
            heartbeat=HeartbeatConfig(
                interval_minutes=heartbeat_data.get("interval_minutes", HeartbeatConfig.interval_minutes),
                quiet_hours_start=heartbeat_data.get("quiet_hours_start", HeartbeatConfig.quiet_hours_start),
                quiet_hours_end=heartbeat_data.get("quiet_hours_end", HeartbeatConfig.quiet_hours_end),
            ),
            web=WebConfig(
                host=web_data.get("host", WebConfig.host),
                port=web_data.get("port", WebConfig.port),
            ),
            system_prompt=data.get("system_prompt", ""),
            max_tool_iterations=data.get("max_tool_iterations", 10),
            embedding_model=data.get("embedding_model", "nomic-embed-text"),
            watch_paths=data.get("watch_paths", []),
        )


def _apply_env_overrides(config: Config) -> Config:
    """Apply environment variable overrides."""
    if url := os.environ.get("RADAR_OLLAMA_URL"):
        config.ollama.base_url = url
    if model := os.environ.get("RADAR_OLLAMA_MODEL"):
        config.ollama.model = model
    if ntfy_url := os.environ.get("RADAR_NTFY_URL"):
        config.notifications.url = ntfy_url
    if ntfy_topic := os.environ.get("RADAR_NTFY_TOPIC"):
        config.notifications.topic = ntfy_topic
    if embedding_model := os.environ.get("RADAR_EMBEDDING_MODEL"):
        config.embedding_model = embedding_model
    if web_host := os.environ.get("RADAR_WEB_HOST"):
        config.web.host = web_host
    if web_port := os.environ.get("RADAR_WEB_PORT"):
        config.web.port = int(web_port)
    return config


def get_config_path() -> Path | None:
    """Get the path to the config file if it exists."""
    config_paths = [
        Path.cwd() / "radar.yaml",
        Path.home() / ".config" / "radar" / "radar.yaml",
    ]
    for path in config_paths:
        if path.exists():
            return path
    return None


def load_config() -> Config:
    """Load configuration from file with fallbacks."""
    config_path = get_config_path()

    if config_path:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        config = Config.from_dict(data)
        return _apply_env_overrides(config)

    # Return defaults if no config file found
    return _apply_env_overrides(Config())


# Global config instance
_config: Config | None = None


def get_config() -> Config:
    """Get the global config instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> Config:
    """Reload configuration from file."""
    global _config
    _config = load_config()
    return _config
