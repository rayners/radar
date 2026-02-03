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
class Config:
    """Main configuration container."""

    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    notifications: NotifyConfig = field(default_factory=NotifyConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    system_prompt: str = ""
    max_tool_iterations: int = 10
    embedding_model: str = "nomic-embed-text"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        """Create Config from dictionary."""
        ollama_data = data.get("ollama", {})
        notify_data = data.get("notifications", {})
        tools_data = data.get("tools", {})

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
            system_prompt=data.get("system_prompt", ""),
            max_tool_iterations=data.get("max_tool_iterations", 10),
            embedding_model=data.get("embedding_model", "nomic-embed-text"),
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
    return config


def load_config() -> Config:
    """Load configuration from file with fallbacks."""
    config_paths = [
        Path.cwd() / "radar.yaml",
        Path.home() / ".config" / "radar" / "radar.yaml",
    ]

    for path in config_paths:
        if path.exists():
            with open(path) as f:
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
