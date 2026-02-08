"""Tests for personality front matter parsing and tool/model filtering."""

from unittest.mock import patch, MagicMock

import pytest

from radar.agent import PersonalityConfig, parse_personality


# ===== Parsing Tests =====


class TestParsePersonality:
    """Tests for parse_personality()."""

    def test_no_front_matter(self):
        raw = "# My Personality\n\nJust a regular prompt."
        pc = parse_personality(raw)
        assert pc.content == raw
        assert pc.model is None
        assert pc.fallback_model is None
        assert pc.tools_include is None
        assert pc.tools_exclude is None
        assert pc.provider is None
        assert pc.base_url is None
        assert pc.api_key_env is None

    def test_model_and_fallback_parsed(self):
        raw = "---\nmodel: qwen3:30b-a3b\nfallback_model: qwen3:latest\n---\n# Dev\n\nPrompt body."
        pc = parse_personality(raw)
        assert pc.model == "qwen3:30b-a3b"
        assert pc.fallback_model == "qwen3:latest"
        assert pc.content == "# Dev\n\nPrompt body."

    def test_tools_include_parsed(self):
        raw = "---\ntools:\n  include:\n    - github\n    - weather\n---\n# Body"
        pc = parse_personality(raw)
        assert pc.tools_include == ["github", "weather"]
        assert pc.tools_exclude is None

    def test_tools_exclude_parsed(self):
        raw = "---\ntools:\n  exclude:\n    - exec\n    - write_file\n---\n# Body"
        pc = parse_personality(raw)
        assert pc.tools_exclude == ["exec", "write_file"]
        assert pc.tools_include is None

    def test_both_include_and_exclude_raises(self):
        raw = "---\ntools:\n  include:\n    - github\n  exclude:\n    - exec\n---\n# Body"
        with pytest.raises(ValueError, match="cannot specify both"):
            parse_personality(raw)

    def test_invalid_yaml_graceful_fallback(self):
        raw = "---\n: invalid: yaml: [broken\n---\n# Body"
        pc = parse_personality(raw)
        # Malformed YAML — returns entire raw content as body
        assert pc.content == raw
        assert pc.model is None

    def test_no_closing_fence_graceful_fallback(self):
        raw = "---\nmodel: test\n# No closing fence here"
        pc = parse_personality(raw)
        # No closing --- — returns entire content as body
        assert pc.content == raw
        assert pc.model is None

    def test_empty_front_matter(self):
        raw = "---\n---\n# Empty front matter\n\nBody text."
        pc = parse_personality(raw)
        assert pc.content == "# Empty front matter\n\nBody text."
        assert pc.model is None

    def test_model_only(self):
        raw = "---\nmodel: llama3.2\n---\n# Simple"
        pc = parse_personality(raw)
        assert pc.model == "llama3.2"
        assert pc.fallback_model is None
        assert pc.tools_include is None
        assert pc.tools_exclude is None
        assert pc.content == "# Simple"

    def test_non_string_model_ignored(self):
        raw = "---\nmodel: 42\n---\n# Body"
        pc = parse_personality(raw)
        assert pc.model is None

    def test_empty_tools_section(self):
        raw = "---\ntools:\n---\n# Body"
        pc = parse_personality(raw)
        assert pc.tools_include is None
        assert pc.tools_exclude is None

    def test_front_matter_stripped_from_content(self):
        raw = "---\nmodel: test-model\ntools:\n  include:\n    - weather\n---\n# Weather Bot\n\nI only do weather."
        pc = parse_personality(raw)
        assert "---" not in pc.content
        assert "model:" not in pc.content
        assert pc.content.startswith("# Weather Bot")

    def test_provider_and_base_url_parsed(self):
        raw = "---\nprovider: openai\nbase_url: https://api.openai.com/v1\napi_key_env: OPENAI_API_KEY\nmodel: gpt-4o\n---\n# Cloud"
        pc = parse_personality(raw)
        assert pc.provider == "openai"
        assert pc.base_url == "https://api.openai.com/v1"
        assert pc.api_key_env == "OPENAI_API_KEY"
        assert pc.model == "gpt-4o"

    def test_provider_only_parsed(self):
        raw = "---\nprovider: openai\nmodel: gpt-4o\n---\n# Cloud"
        pc = parse_personality(raw)
        assert pc.provider == "openai"
        assert pc.base_url is None
        assert pc.api_key_env is None
        assert pc.model == "gpt-4o"

    def test_non_string_provider_ignored(self):
        raw = "---\nprovider: 42\n---\n# Body"
        pc = parse_personality(raw)
        assert pc.provider is None

    def test_non_string_base_url_ignored(self):
        raw = "---\nbase_url: 8080\n---\n# Body"
        pc = parse_personality(raw)
        assert pc.base_url is None

    def test_non_string_api_key_env_ignored(self):
        raw = "---\napi_key_env: 123\n---\n# Body"
        pc = parse_personality(raw)
        assert pc.api_key_env is None


# ===== Tool Filtering Tests =====


class TestToolFiltering:
    """Tests for get_tools_schema() include/exclude params."""

    def test_include_filters_tools(self):
        from radar.tools import get_tools_schema, _registry

        all_names = set(_registry.keys())
        assert len(all_names) > 1, "Need multiple tools for this test"

        # Pick two tool names
        names = list(all_names)[:2]
        result = get_tools_schema(include=names)
        result_names = {t["function"]["name"] for t in result}
        assert result_names == set(names)

    def test_exclude_filters_tools(self):
        from radar.tools import get_tools_schema, _registry

        all_names = set(_registry.keys())
        assert len(all_names) > 1, "Need multiple tools for this test"

        exclude_name = list(all_names)[0]
        result = get_tools_schema(exclude=[exclude_name])
        result_names = {t["function"]["name"] for t in result}
        assert exclude_name not in result_names
        assert len(result_names) == len(all_names) - 1

    def test_no_filter_returns_all(self):
        from radar.tools import get_tools_schema, _registry

        result = get_tools_schema()
        assert len(result) == len(_registry)

    def test_include_nonexistent_tool(self):
        from radar.tools import get_tools_schema

        result = get_tools_schema(include=["nonexistent_tool_xyz"])
        assert result == []


# ===== Integration Tests (mocked) =====


class TestIntegration:
    """Integration tests for personality config flowing through ask()/run()."""

    @patch("radar.agent.chat")
    @patch("radar.agent.load_personality")
    @patch("radar.agent.get_config")
    def test_ask_passes_model_override(self, mock_config, mock_load, mock_chat):
        from radar.agent import ask

        mock_config.return_value = MagicMock(personality="default")
        mock_load.return_value = "---\nmodel: custom-model\nfallback_model: fallback-m\n---\n# Test"
        mock_chat.return_value = ({"role": "assistant", "content": "hi"}, [])

        ask("hello")

        mock_chat.assert_called_once()
        _, kwargs = mock_chat.call_args
        assert kwargs["model_override"] == "custom-model"
        assert kwargs["fallback_model_override"] == "fallback-m"

    @patch("radar.agent.chat")
    @patch("radar.agent.load_personality")
    @patch("radar.agent.get_config")
    def test_ask_passes_tool_filter(self, mock_config, mock_load, mock_chat):
        from radar.agent import ask

        mock_config.return_value = MagicMock(personality="default")
        mock_load.return_value = "---\ntools:\n  include:\n    - weather\n---\n# Test"
        mock_chat.return_value = ({"role": "assistant", "content": "hi"}, [])

        ask("hello")

        mock_chat.assert_called_once()
        _, kwargs = mock_chat.call_args
        assert kwargs["tools_include"] == ["weather"]
        assert kwargs["tools_exclude"] is None

    @patch("radar.agent.chat")
    @patch("radar.agent.load_personality")
    @patch("radar.agent.get_config")
    def test_system_prompt_has_no_front_matter(self, mock_config, mock_load, mock_chat):
        from radar.agent import ask

        mock_config.return_value = MagicMock(personality="default")
        mock_load.return_value = "---\nmodel: test\n---\n# Clean Prompt\n\nBody here."
        mock_chat.return_value = ({"role": "assistant", "content": "hi"}, [])

        ask("hello")

        # Check the system message content
        call_args = mock_chat.call_args
        messages = call_args[0][0]
        system_content = messages[0]["content"]
        assert "---" not in system_content
        assert "model:" not in system_content
        assert "Clean Prompt" in system_content

    @patch("radar.agent.chat")
    @patch("radar.agent.load_personality")
    @patch("radar.agent.get_config")
    def test_ask_no_front_matter_passes_none(self, mock_config, mock_load, mock_chat):
        from radar.agent import ask

        mock_config.return_value = MagicMock(personality="default")
        mock_load.return_value = "# Plain\n\nNo front matter."
        mock_chat.return_value = ({"role": "assistant", "content": "hi"}, [])

        ask("hello")

        _, kwargs = mock_chat.call_args
        assert kwargs["model_override"] is None
        assert kwargs["fallback_model_override"] is None
        assert kwargs["tools_include"] is None
        assert kwargs["tools_exclude"] is None
        assert kwargs["provider_override"] is None
        assert kwargs["base_url_override"] is None
        assert kwargs["api_key_override"] is None

    @patch("radar.agent.chat")
    @patch("radar.agent.load_personality")
    @patch("radar.agent.get_config")
    def test_ask_passes_provider_override(self, mock_config, mock_load, mock_chat):
        from radar.agent import ask

        mock_config.return_value = MagicMock(personality="default")
        mock_load.return_value = (
            "---\nprovider: openai\nbase_url: https://api.openai.com/v1\n"
            "api_key_env: TEST_RADAR_KEY\nmodel: gpt-4o\n---\n# Cloud"
        )
        mock_chat.return_value = ({"role": "assistant", "content": "hi"}, [])

        import os
        os.environ["TEST_RADAR_KEY"] = "sk-test-key-123"
        try:
            ask("hello")
        finally:
            del os.environ["TEST_RADAR_KEY"]

        mock_chat.assert_called_once()
        _, kwargs = mock_chat.call_args
        assert kwargs["provider_override"] == "openai"
        assert kwargs["base_url_override"] == "https://api.openai.com/v1"
        assert kwargs["api_key_override"] == "sk-test-key-123"
        assert kwargs["model_override"] == "gpt-4o"

    @patch("radar.agent.chat")
    @patch("radar.agent.load_personality")
    @patch("radar.agent.get_config")
    def test_api_key_env_not_set_passes_none(self, mock_config, mock_load, mock_chat):
        from radar.agent import ask

        mock_config.return_value = MagicMock(personality="default")
        mock_load.return_value = (
            "---\nprovider: openai\napi_key_env: NONEXISTENT_KEY_XYZ\n---\n# Cloud"
        )
        mock_chat.return_value = ({"role": "assistant", "content": "hi"}, [])

        ask("hello")

        _, kwargs = mock_chat.call_args
        assert kwargs["provider_override"] == "openai"
        assert kwargs["api_key_override"] is None


# ===== Feedback Front Matter Preservation =====


class TestPreserveFrontMatter:
    """Tests for _preserve_front_matter() in feedback.py."""

    def test_preserves_front_matter_on_modify(self):
        from radar.feedback import _preserve_front_matter

        original = "---\nmodel: test\ntools:\n  include:\n    - weather\n---\n# Old Body"
        new_body = "# New Body\n\nUpdated content."

        result = _preserve_front_matter(original, new_body)
        assert result.startswith("---")
        assert "model: test" in result
        assert "# New Body" in result
        assert "# Old Body" not in result

    def test_no_front_matter_in_original(self):
        from radar.feedback import _preserve_front_matter

        original = "# No front matter\n\nJust text."
        new_body = "# New body"

        result = _preserve_front_matter(original, new_body)
        assert result == new_body

    def test_new_body_has_own_front_matter(self):
        from radar.feedback import _preserve_front_matter

        original = "---\nmodel: old\n---\n# Old"
        new_body = "---\nmodel: new\n---\n# New"

        result = _preserve_front_matter(original, new_body)
        assert result == new_body  # New body's front matter takes precedence

    def test_malformed_original_no_closing(self):
        from radar.feedback import _preserve_front_matter

        original = "---\nmodel: test\n# No closing"
        new_body = "# New body"

        result = _preserve_front_matter(original, new_body)
        assert result == new_body  # Can't extract front matter, pass through


# ===== Web Route Helper =====


class TestExtractPersonalityInfo:
    """Tests for _extract_personality_info() in personalities routes."""

    def test_plain_personality(self):
        from radar.web.routes.personalities import _extract_personality_info

        info = _extract_personality_info("# Test\n\nA helpful assistant.")
        assert info["description"] == "A helpful assistant."
        assert "model" not in info
        assert "tools_filter" not in info

    def test_personality_with_model(self):
        from radar.web.routes.personalities import _extract_personality_info

        content = "---\nmodel: gpt-4o\n---\n# GPT\n\nUses GPT-4o."
        info = _extract_personality_info(content)
        assert info["model"] == "gpt-4o"
        assert info["description"] == "Uses GPT-4o."

    def test_personality_with_tools_include(self):
        from radar.web.routes.personalities import _extract_personality_info

        content = "---\ntools:\n  include:\n    - weather\n    - github\n---\n# Filtered\n\nLimited tools."
        info = _extract_personality_info(content)
        assert "tools_filter" in info
        assert "include" in info["tools_filter"]
        assert "weather" in info["tools_filter"]

    def test_personality_with_provider(self):
        from radar.web.routes.personalities import _extract_personality_info

        content = "---\nprovider: openai\nbase_url: https://api.openai.com/v1\nmodel: gpt-4o\n---\n# Cloud\n\nCloud assistant."
        info = _extract_personality_info(content)
        assert info["provider"] == "openai"
        assert info["base_url"] == "https://api.openai.com/v1"
        assert info["model"] == "gpt-4o"

    def test_personality_without_provider(self):
        from radar.web.routes.personalities import _extract_personality_info

        content = "---\nmodel: qwen3:latest\n---\n# Local\n\nLocal assistant."
        info = _extract_personality_info(content)
        assert "provider" not in info
        assert "base_url" not in info
