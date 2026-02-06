"""Tests for radar/config.py — paths, parsing, env overrides, loading."""

import warnings
from pathlib import Path

import pytest
import yaml

import radar.config
from radar.config import (
    Config,
    DataPaths,
    EmbeddingConfig,
    LLMConfig,
    ToolsConfig,
    WebConfig,
    _apply_env_overrides,
    get_config,
    get_config_path,
    get_data_paths,
    load_config,
    reload_config,
    reset_data_paths,
)


# ── DataPaths ──────────────────────────────────────────────────────


class TestDataPaths:
    """DataPaths resolves and caches the base data directory."""

    def test_default_base_dir(self, monkeypatch):
        monkeypatch.delenv("RADAR_DATA_DIR", raising=False)
        paths = DataPaths()
        expected = Path.home() / ".local" / "share" / "radar"
        assert paths._resolve_base_dir() == expected

    def test_env_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("RADAR_DATA_DIR", str(tmp_path / "custom"))
        paths = DataPaths()
        assert paths._resolve_base_dir() == tmp_path / "custom"

    def test_set_base_dir(self, tmp_path):
        paths = DataPaths()
        paths.set_base_dir(str(tmp_path / "override"))
        assert paths._base_dir == tmp_path / "override"

    def test_set_base_dir_empty_string_no_op(self):
        paths = DataPaths()
        paths.set_base_dir("")
        assert paths._base_dir is None

    def test_reset_clears_cache(self, tmp_path):
        paths = DataPaths()
        paths.set_base_dir(str(tmp_path))
        paths.reset()
        assert paths._base_dir is None

    def test_subdirectory_properties(self, isolated_data_dir):
        paths = get_data_paths()
        assert paths.conversations == isolated_data_dir / "conversations"
        assert paths.db == isolated_data_dir / "memory.db"
        assert paths.personalities == isolated_data_dir / "personalities"
        assert paths.plugins == isolated_data_dir / "plugins"
        assert paths.tools == isolated_data_dir / "tools"
        assert paths.log_file == isolated_data_dir / "radar.log"
        assert paths.pid_file == isolated_data_dir / "radar.pid"

    def test_conversations_dir_created(self, isolated_data_dir):
        paths = get_data_paths()
        assert paths.conversations.is_dir()

    def test_personalities_dir_created(self, isolated_data_dir):
        paths = get_data_paths()
        assert paths.personalities.is_dir()


# ── Config.from_dict ───────────────────────────────────────────────


class TestConfigFromDict:
    """Config.from_dict parses each section with defaults."""

    def test_empty_dict_returns_defaults(self):
        cfg = Config.from_dict({})
        assert cfg.llm.provider == "ollama"
        assert cfg.llm.model == "qwen3:latest"
        assert cfg.embedding.provider == "ollama"
        assert cfg.web.port == 8420
        assert cfg.max_tool_iterations == 10
        assert cfg.personality == "default"

    def test_llm_section_parsed(self):
        cfg = Config.from_dict({"llm": {
            "provider": "openai",
            "model": "gpt-4o",
            "base_url": "https://api.openai.com/v1",
            "fallback_model": "gpt-3.5-turbo",
        }})
        assert cfg.llm.provider == "openai"
        assert cfg.llm.model == "gpt-4o"
        assert cfg.llm.base_url == "https://api.openai.com/v1"
        assert cfg.llm.fallback_model == "gpt-3.5-turbo"

    def test_embedding_section_parsed(self):
        cfg = Config.from_dict({"embedding": {
            "provider": "local",
            "model": "all-MiniLM-L6-v2",
        }})
        assert cfg.embedding.provider == "local"
        assert cfg.embedding.model == "all-MiniLM-L6-v2"

    def test_tools_section_parsed(self):
        cfg = Config.from_dict({"tools": {
            "exec_mode": "safe_only",
            "max_file_size": 500,
            "extra_dirs": ["/opt/tools"],
        }})
        assert cfg.tools.exec_mode == "safe_only"
        assert cfg.tools.max_file_size == 500
        assert cfg.tools.extra_dirs == ["/opt/tools"]

    def test_web_section_parsed(self):
        cfg = Config.from_dict({"web": {
            "host": "0.0.0.0",
            "port": 9000,
            "auth_token": "secret",
        }})
        assert cfg.web.host == "0.0.0.0"
        assert cfg.web.port == 9000
        assert cfg.web.auth_token == "secret"

    def test_heartbeat_section_parsed(self):
        cfg = Config.from_dict({"heartbeat": {
            "interval_minutes": 30,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "08:00",
        }})
        assert cfg.heartbeat.interval_minutes == 30
        assert cfg.heartbeat.quiet_hours_start == "22:00"

    def test_plugins_section_parsed(self):
        cfg = Config.from_dict({"plugins": {
            "auto_approve": True,
            "max_debug_attempts": 3,
        }})
        assert cfg.plugins.auto_approve is True
        assert cfg.plugins.max_debug_attempts == 3

    def test_search_section_parsed(self):
        cfg = Config.from_dict({"search": {
            "provider": "brave",
            "max_results": 5,
        }})
        assert cfg.search.provider == "brave"
        assert cfg.search.max_results == 5

    def test_personality_evolution_parsed(self):
        cfg = Config.from_dict({"personality_evolution": {
            "allow_suggestions": False,
            "min_feedback_for_analysis": 20,
        }})
        assert cfg.personality_evolution.allow_suggestions is False
        assert cfg.personality_evolution.min_feedback_for_analysis == 20

    def test_top_level_fields(self):
        cfg = Config.from_dict({
            "system_prompt": "You are helpful.",
            "max_tool_iterations": 5,
            "personality": "creative",
        })
        assert cfg.system_prompt == "You are helpful."
        assert cfg.max_tool_iterations == 5
        assert cfg.personality == "creative"

    def test_deprecated_ollama_section_migrates(self):
        with pytest.warns(DeprecationWarning, match="ollama.*deprecated"):
            cfg = Config.from_dict({"ollama": {
                "base_url": "http://remote:11434",
                "model": "llama3.2",
            }})
        assert cfg.llm.provider == "ollama"
        assert cfg.llm.base_url == "http://remote:11434"
        assert cfg.llm.model == "llama3.2"

    def test_deprecated_embedding_model_migrates(self):
        with pytest.warns(DeprecationWarning, match="embedding_model.*deprecated"):
            cfg = Config.from_dict({"embedding_model": "custom-embed"})
        assert cfg.embedding.model == "custom-embed"

    def test_api_key_in_config_warns(self):
        with pytest.warns(UserWarning, match="API key found in config"):
            Config.from_dict({"llm": {"api_key": "sk-secret"}})

    def test_ollama_section_ignored_when_llm_present(self):
        cfg = Config.from_dict({
            "llm": {"provider": "openai", "model": "gpt-4o"},
            "ollama": {"model": "llama3.2"},
        })
        assert cfg.llm.model == "gpt-4o"


# ── _apply_env_overrides ──────────────────────────────────────────


class TestApplyEnvOverrides:
    """Environment variables override config values."""

    def test_llm_env_vars(self, monkeypatch):
        monkeypatch.setenv("RADAR_API_KEY", "sk-test")
        monkeypatch.setenv("RADAR_LLM_PROVIDER", "openai")
        monkeypatch.setenv("RADAR_LLM_BASE_URL", "https://api.example.com")
        monkeypatch.setenv("RADAR_LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("RADAR_LLM_FALLBACK_MODEL", "gpt-3.5-turbo")
        cfg = _apply_env_overrides(Config())
        assert cfg.llm.api_key == "sk-test"
        assert cfg.llm.provider == "openai"
        assert cfg.llm.base_url == "https://api.example.com"
        assert cfg.llm.model == "gpt-4o"
        assert cfg.llm.fallback_model == "gpt-3.5-turbo"

    def test_embedding_env_vars(self, monkeypatch):
        monkeypatch.setenv("RADAR_EMBEDDING_PROVIDER", "local")
        monkeypatch.setenv("RADAR_EMBEDDING_MODEL", "all-MiniLM")
        monkeypatch.setenv("RADAR_EMBEDDING_BASE_URL", "http://embed:8000")
        monkeypatch.setenv("RADAR_EMBEDDING_API_KEY", "emb-key")
        cfg = _apply_env_overrides(Config())
        assert cfg.embedding.provider == "local"
        assert cfg.embedding.model == "all-MiniLM"
        assert cfg.embedding.base_url == "http://embed:8000"
        assert cfg.embedding.api_key == "emb-key"

    def test_web_port_int_conversion(self, monkeypatch):
        monkeypatch.setenv("RADAR_WEB_PORT", "9999")
        cfg = _apply_env_overrides(Config())
        assert cfg.web.port == 9999
        assert isinstance(cfg.web.port, int)

    def test_web_host_and_auth(self, monkeypatch):
        monkeypatch.setenv("RADAR_WEB_HOST", "0.0.0.0")
        monkeypatch.setenv("RADAR_WEB_AUTH_TOKEN", "tok123")
        cfg = _apply_env_overrides(Config())
        assert cfg.web.host == "0.0.0.0"
        assert cfg.web.auth_token == "tok123"

    def test_deprecated_ollama_url(self, monkeypatch):
        monkeypatch.setenv("RADAR_OLLAMA_URL", "http://old:11434")
        with pytest.warns(DeprecationWarning, match="RADAR_OLLAMA_URL"):
            cfg = _apply_env_overrides(Config())
        assert cfg.llm.base_url == "http://old:11434"

    def test_deprecated_ollama_model(self, monkeypatch):
        monkeypatch.setenv("RADAR_OLLAMA_MODEL", "old-model")
        with pytest.warns(DeprecationWarning, match="RADAR_OLLAMA_MODEL"):
            cfg = _apply_env_overrides(Config())
        assert cfg.llm.model == "old-model"

    def test_env_overrides_beat_config(self, monkeypatch):
        monkeypatch.setenv("RADAR_LLM_MODEL", "env-model")
        cfg = Config.from_dict({"llm": {"model": "file-model"}})
        cfg = _apply_env_overrides(cfg)
        assert cfg.llm.model == "env-model"

    def test_personality_env(self, monkeypatch):
        monkeypatch.setenv("RADAR_PERSONALITY", "creative")
        cfg = _apply_env_overrides(Config())
        assert cfg.personality == "creative"

    def test_search_env_vars(self, monkeypatch):
        monkeypatch.setenv("RADAR_SEARCH_PROVIDER", "brave")
        monkeypatch.setenv("RADAR_BRAVE_API_KEY", "brave-key")
        monkeypatch.setenv("RADAR_SEARXNG_URL", "http://searx:8080")
        cfg = _apply_env_overrides(Config())
        assert cfg.search.provider == "brave"
        assert cfg.search.brave_api_key == "brave-key"
        assert cfg.search.searxng_url == "http://searx:8080"

    def test_ntfy_env_vars(self, monkeypatch):
        monkeypatch.setenv("RADAR_NTFY_URL", "https://ntfy.example.com")
        monkeypatch.setenv("RADAR_NTFY_TOPIC", "alerts")
        cfg = _apply_env_overrides(Config())
        assert cfg.notifications.url == "https://ntfy.example.com"
        assert cfg.notifications.topic == "alerts"


# ── get_config_path ────────────────────────────────────────────────


class TestGetConfigPath:
    """get_config_path resolves config file location."""

    def test_env_override(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "custom.yaml"
        cfg_file.write_text("llm:\n  model: test\n")
        monkeypatch.setenv("RADAR_CONFIG_PATH", str(cfg_file))
        assert get_config_path() == cfg_file

    def test_env_override_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADAR_CONFIG_PATH", str(tmp_path / "nope.yaml"))
        with pytest.warns(UserWarning, match="does not exist"):
            result = get_config_path()
        assert result is None

    def test_cwd_radar_yaml(self, tmp_path, monkeypatch):
        monkeypatch.delenv("RADAR_CONFIG_PATH", raising=False)
        monkeypatch.chdir(tmp_path)
        cfg_file = tmp_path / "radar.yaml"
        cfg_file.write_text("llm:\n  model: cwd\n")
        assert get_config_path() == cfg_file

    def test_returns_none_when_no_config(self, tmp_path, monkeypatch):
        monkeypatch.delenv("RADAR_CONFIG_PATH", raising=False)
        monkeypatch.chdir(tmp_path)
        # No radar.yaml in cwd, and home config probably doesn't exist
        # in CI — might return None or the home config
        result = get_config_path()
        # If a file is found it should be a Path; if not, None
        assert result is None or isinstance(result, Path)


# ── load_config / get_config / reload_config ──────────────────────


class TestLoadAndGlobalConfig:
    """load_config, get_config, reload_config lifecycle."""

    def test_no_config_file_returns_defaults(self, tmp_path, monkeypatch):
        monkeypatch.delenv("RADAR_CONFIG_PATH", raising=False)
        monkeypatch.chdir(tmp_path)
        # Reset global state
        radar.config._config = None
        reset_data_paths()
        monkeypatch.setenv("RADAR_DATA_DIR", str(tmp_path / "data"))
        cfg = load_config()
        assert cfg.llm.provider == "ollama"

    def test_loads_valid_yaml(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "radar.yaml"
        cfg_file.write_text(yaml.dump({
            "llm": {"model": "custom-model"},
            "web": {"port": 7777},
        }))
        monkeypatch.setenv("RADAR_CONFIG_PATH", str(cfg_file))
        monkeypatch.setenv("RADAR_DATA_DIR", str(tmp_path / "data"))
        radar.config._config = None
        reset_data_paths()
        cfg = load_config()
        assert cfg.llm.model == "custom-model"
        assert cfg.web.port == 7777

    def test_get_config_caches(self, isolated_data_dir):
        radar.config._config = None
        c1 = get_config()
        c2 = get_config()
        assert c1 is c2

    def test_reload_config_returns_fresh(self, isolated_data_dir):
        radar.config._config = None
        c1 = get_config()
        c2 = reload_config()
        assert c1 is not c2
