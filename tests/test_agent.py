"""Tests for radar/agent.py — personality loading, prompt building, run/ask."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from radar.agent import (
    DEFAULT_PERSONALITY,
    PersonalityConfig,
    _build_system_prompt,
    _render_personality_template,
    ask,
    load_personality,
    run,
)


class TestLoadPersonality:
    """load_personality resolves files by name or path."""

    def test_loads_from_explicit_path(self, tmp_path):
        p = tmp_path / "custom.md"
        p.write_text("# Custom\nBe creative.")
        content = load_personality(str(p))
        assert "Be creative." in content

    def test_loads_by_name(self, personalities_dir):
        (personalities_dir / "funny.md").write_text("# Funny\nBe funny.")
        content = load_personality("funny")
        assert "Be funny." in content

    def test_falls_back_to_default(self, personalities_dir):
        content = load_personality("nonexistent_xyz")
        assert content == DEFAULT_PERSONALITY

    def test_creates_default_md_if_missing(self, personalities_dir):
        default_file = personalities_dir / "default.md"
        assert not default_file.exists()
        load_personality("default")
        assert default_file.exists()
        assert default_file.read_text() == DEFAULT_PERSONALITY

    def test_loads_existing_default(self, personalities_dir):
        default_file = personalities_dir / "default.md"
        default_file.write_text("# My Default\nCustom default.")
        content = load_personality("default")
        assert "Custom default." in content


class TestBuildSystemPrompt:
    """_build_system_prompt injects time, memories, and personality config."""

    @patch("radar.agent.get_config")
    def test_replaces_current_time(self, mock_config, personalities_dir):
        mock_config.return_value = MagicMock(personality="default")
        (personalities_dir / "default.md").write_text(
            "Current time: {current_time}"
        )
        with patch("radar.semantic.search_memories", side_effect=Exception("no db")):
            prompt, pc = _build_system_prompt()
        assert "{current_time}" not in prompt
        # Should contain a date-like string
        assert "202" in prompt  # Year prefix

    @patch("radar.agent.get_config")
    def test_injects_semantic_memories(self, mock_config, personalities_dir):
        mock_config.return_value = MagicMock(personality="default")
        (personalities_dir / "default.md").write_text("# Default")
        memories = [{"content": "User likes Python"}]
        with patch("radar.semantic.search_memories", return_value=memories):
            prompt, _ = _build_system_prompt()
        assert "User likes Python" in prompt

    @patch("radar.agent.get_config")
    def test_silent_on_memory_failure(self, mock_config, personalities_dir):
        mock_config.return_value = MagicMock(personality="default")
        (personalities_dir / "default.md").write_text("# Default")
        with patch("radar.semantic.search_memories", side_effect=Exception("boom")):
            prompt, _ = _build_system_prompt()
        # Should not raise
        assert "Default" in prompt

    @patch("radar.agent.get_config")
    def test_respects_personality_override(self, mock_config, personalities_dir):
        mock_config.return_value = MagicMock(personality="default")
        (personalities_dir / "creative.md").write_text("# Creative\nBe creative.")
        with patch("radar.semantic.search_memories", side_effect=Exception):
            prompt, _ = _build_system_prompt(personality_override="creative")
        assert "Be creative." in prompt

    @patch("radar.agent.get_config")
    def test_returns_personality_config_with_front_matter(self, mock_config, personalities_dir):
        mock_config.return_value = MagicMock(personality="default")
        (personalities_dir / "special.md").write_text(
            "---\nmodel: gpt-4o\ntools:\n  include:\n    - weather\n---\n# Special"
        )
        with patch("radar.semantic.search_memories", side_effect=Exception):
            _, pc = _build_system_prompt(personality_override="special")
        assert pc.model == "gpt-4o"
        assert pc.tools_include == ["weather"]


class TestRun:
    """run() orchestrates conversation, messages, and LLM call."""

    @patch("radar.agent.chat")
    @patch("radar.agent.get_messages", return_value=[])
    @patch("radar.agent.add_message")
    @patch("radar.agent.create_conversation", return_value="conv-123")
    @patch("radar.agent._build_system_prompt")
    def test_creates_conversation_when_none(self, mock_prompt, mock_create,
                                             mock_add, mock_get_msgs, mock_chat):
        mock_prompt.return_value = ("system prompt", PersonalityConfig(content=""))
        mock_chat.return_value = ({"role": "assistant", "content": "hi"}, [])
        text, cid = run("hello")
        assert cid == "conv-123"
        mock_create.assert_called_once()

    @patch("radar.agent.chat")
    @patch("radar.agent.get_messages", return_value=[])
    @patch("radar.agent.add_message")
    @patch("radar.agent.create_conversation")
    @patch("radar.agent._build_system_prompt")
    def test_reuses_existing_conversation(self, mock_prompt, mock_create,
                                           mock_add, mock_get_msgs, mock_chat):
        mock_prompt.return_value = ("prompt", PersonalityConfig(content=""))
        mock_chat.return_value = ({"role": "assistant", "content": "ok"}, [])
        _, cid = run("hello", conversation_id="existing-456")
        assert cid == "existing-456"
        mock_create.assert_not_called()

    @patch("radar.agent.chat")
    @patch("radar.agent.get_messages", return_value=[])
    @patch("radar.agent.add_message")
    @patch("radar.agent.create_conversation", return_value="c1")
    @patch("radar.agent._build_system_prompt")
    def test_stores_user_message(self, mock_prompt, mock_create,
                                  mock_add, mock_get_msgs, mock_chat):
        mock_prompt.return_value = ("prompt", PersonalityConfig(content=""))
        mock_chat.return_value = ({"role": "assistant", "content": "reply"}, [])
        run("test message")
        # First add_message call should be the user message
        first_call = mock_add.call_args_list[0]
        assert first_call[0] == ("c1", "user", "test message")

    @patch("radar.agent.chat")
    @patch("radar.agent.get_messages", return_value=[])
    @patch("radar.agent.add_message")
    @patch("radar.agent.create_conversation", return_value="c1")
    @patch("radar.agent._build_system_prompt")
    def test_stores_new_messages_from_chat(self, mock_prompt, mock_create,
                                            mock_add, mock_get_msgs, mock_chat):
        mock_prompt.return_value = ("prompt", PersonalityConfig(content=""))
        # chat returns 2 new messages beyond what was sent
        system_msg = {"role": "system", "content": "prompt"}
        user_msg = {"role": "user", "content": "hi"}
        assistant_msg = {"role": "assistant", "content": "response"}
        mock_chat.return_value = (
            assistant_msg,
            [system_msg, user_msg, assistant_msg],  # all_messages
        )
        # get_messages returns 1 stored message (user), so api_messages = system + user = 2
        mock_get_msgs.return_value = [{"role": "user", "content": "hi"}]
        run("hi", conversation_id="c1")
        # Should store the assistant message (new_messages = all_messages[2:])
        # add_message calls: 1 for user + 1 for assistant
        assert mock_add.call_count == 2

    @patch("radar.agent.chat")
    @patch("radar.agent.get_messages", return_value=[])
    @patch("radar.agent.add_message")
    @patch("radar.agent.create_conversation", return_value="c1")
    @patch("radar.agent._build_system_prompt")
    def test_passes_personality_config_to_chat(self, mock_prompt, mock_create,
                                                mock_add, mock_get_msgs, mock_chat):
        pc = PersonalityConfig(
            content="", model="custom-model",
            tools_include=["weather"], fallback_model="fallback",
        )
        mock_prompt.return_value = ("prompt", pc)
        mock_chat.return_value = ({"role": "assistant", "content": "ok"}, [])
        run("test")
        call_kwargs = mock_chat.call_args[1]
        assert call_kwargs["model_override"] == "custom-model"
        assert call_kwargs["tools_include"] == ["weather"]
        assert call_kwargs["fallback_model_override"] == "fallback"


class TestAsk:
    """ask() is a one-shot question without conversation persistence."""

    @patch("radar.agent.chat")
    @patch("radar.agent._build_system_prompt")
    def test_returns_content_string(self, mock_prompt, mock_chat):
        mock_prompt.return_value = ("prompt", PersonalityConfig(content=""))
        mock_chat.return_value = ({"role": "assistant", "content": "42"}, [])
        result = ask("What is 6*7?")
        assert result == "42"

    @patch("radar.agent.chat")
    @patch("radar.agent._build_system_prompt")
    def test_passes_personality(self, mock_prompt, mock_chat):
        mock_prompt.return_value = ("prompt", PersonalityConfig(content=""))
        mock_chat.return_value = ({"role": "assistant", "content": "ok"}, [])
        ask("hi", personality="creative")
        mock_prompt.assert_called_once_with("creative")

    @patch("radar.agent.chat")
    @patch("radar.agent._build_system_prompt")
    def test_sends_system_and_user_messages(self, mock_prompt, mock_chat):
        mock_prompt.return_value = ("sys prompt", PersonalityConfig(content=""))
        mock_chat.return_value = ({"role": "assistant", "content": "ok"}, [])
        ask("hello")
        messages = mock_chat.call_args[0][0]
        assert messages[0] == {"role": "system", "content": "sys prompt"}
        assert messages[1] == {"role": "user", "content": "hello"}

    @patch("radar.agent.chat")
    @patch("radar.agent._build_system_prompt")
    def test_passes_personality_config_to_chat(self, mock_prompt, mock_chat):
        pc = PersonalityConfig(
            content="", model="gpt-4o",
            tools_exclude=["exec"], fallback_model="gpt-3.5",
        )
        mock_prompt.return_value = ("prompt", pc)
        mock_chat.return_value = ({"role": "assistant", "content": "ok"}, [])
        ask("test")
        call_kwargs = mock_chat.call_args[1]
        assert call_kwargs["model_override"] == "gpt-4o"
        assert call_kwargs["tools_exclude"] == ["exec"]
        assert call_kwargs["fallback_model_override"] == "gpt-3.5"


class TestRenderPersonalityTemplate:
    """_render_personality_template renders Jinja2 templates safely."""

    def test_jinja2_current_time_renders(self):
        result = _render_personality_template(
            "Time: {{ current_time }}", {"current_time": "2025-01-15 10:00:00"}
        )
        assert result == "Time: 2025-01-15 10:00:00"

    def test_all_builtin_variables_render(self):
        context = {
            "current_time": "2025-01-15 10:00:00",
            "current_date": "2025-01-15",
            "day_of_week": "Wednesday",
        }
        template = "{{ current_time }} | {{ current_date }} | {{ day_of_week }}"
        result = _render_personality_template(template, context)
        assert result == "2025-01-15 10:00:00 | 2025-01-15 | Wednesday"

    def test_undefined_variable_renders_empty(self):
        result = _render_personality_template(
            "Hello {{ undefined_var }}!", {"current_time": "now"}
        )
        assert result == "Hello !"

    def test_plugin_variable_renders(self):
        result = _render_personality_template(
            "Host: {{ hostname }}", {"hostname": "my-machine"}
        )
        assert result == "Host: my-machine"

    def test_mixed_known_and_unknown(self):
        result = _render_personality_template(
            "{{ current_time }} on {{ hostname }} ({{ missing }})",
            {"current_time": "now", "hostname": "box"},
        )
        assert result == "now on box ()"

    def test_plain_text_passes_through(self):
        result = _render_personality_template("No variables here.", {})
        assert result == "No variables here."


class TestBuildSystemPromptJinja2:
    """_build_system_prompt integration with Jinja2 rendering and plugin variables."""

    @patch("radar.agent.get_config")
    def test_jinja2_current_time_replaced(self, mock_config, personalities_dir):
        mock_config.return_value = MagicMock(personality="default")
        (personalities_dir / "default.md").write_text(
            "Time: {{ current_time }}"
        )
        with patch("radar.semantic.search_memories", side_effect=Exception):
            prompt, _ = _build_system_prompt()
        assert "{{ current_time }}" not in prompt
        assert "202" in prompt

    @patch("radar.agent.get_config")
    def test_current_date_and_day_of_week(self, mock_config, personalities_dir):
        mock_config.return_value = MagicMock(personality="default")
        (personalities_dir / "default.md").write_text(
            "Date: {{ current_date }}, Day: {{ day_of_week }}"
        )
        with patch("radar.semantic.search_memories", side_effect=Exception):
            prompt, _ = _build_system_prompt()
        assert "{{ current_date }}" not in prompt
        assert "{{ day_of_week }}" not in prompt
        # Should contain a date-like string and a day name
        assert "202" in prompt

    @patch("radar.agent.get_config")
    def test_plugin_variables_appear_in_prompt(self, mock_config, personalities_dir):
        mock_config.return_value = MagicMock(personality="default")
        (personalities_dir / "default.md").write_text(
            "Host: {{ hostname }}"
        )
        mock_loader = MagicMock()
        mock_loader.get_prompt_variable_values.return_value = {"hostname": "test-box"}
        with (
            patch("radar.semantic.search_memories", side_effect=Exception),
            patch("radar.plugins.get_plugin_loader", return_value=mock_loader),
        ):
            prompt, _ = _build_system_prompt()
        assert "Host: test-box" in prompt

    @patch("radar.agent.get_config")
    def test_plugin_loader_failure_is_silent(self, mock_config, personalities_dir):
        mock_config.return_value = MagicMock(personality="default")
        (personalities_dir / "default.md").write_text(
            "Time: {{ current_time }}"
        )
        with (
            patch("radar.semantic.search_memories", side_effect=Exception),
            patch("radar.plugins.get_plugin_loader", side_effect=Exception("broken")),
        ):
            prompt, _ = _build_system_prompt()
        # Should still render with built-in variables
        assert "202" in prompt

    @patch("radar.agent.get_config")
    def test_builtin_vars_take_precedence_over_plugin(self, mock_config, personalities_dir):
        mock_config.return_value = MagicMock(personality="default")
        (personalities_dir / "default.md").write_text(
            "{{ current_time }}"
        )
        mock_loader = MagicMock()
        # Plugin tries to override current_time
        mock_loader.get_prompt_variable_values.return_value = {"current_time": "HACKED"}
        with (
            patch("radar.semantic.search_memories", side_effect=Exception),
            patch("radar.plugins.get_plugin_loader", return_value=mock_loader),
        ):
            prompt, _ = _build_system_prompt()
        assert "HACKED" not in prompt
        assert "202" in prompt

    @patch("radar.agent.get_config")
    def test_legacy_braces_still_work(self, mock_config, personalities_dir):
        mock_config.return_value = MagicMock(personality="default")
        (personalities_dir / "default.md").write_text(
            "Time: {current_time}"
        )
        with patch("radar.semantic.search_memories", side_effect=Exception):
            prompt, _ = _build_system_prompt()
        assert "{current_time}" not in prompt
        assert "202" in prompt

    @patch("radar.agent.get_config")
    def test_plugin_variables_evaluated_each_call(self, mock_config, personalities_dir):
        """Plugin variable functions are called on every prompt build, not cached."""
        mock_config.return_value = MagicMock(personality="default")
        (personalities_dir / "default.md").write_text("Counter: {{ counter }}")

        call_count = 0

        def incrementing_counter():
            nonlocal call_count
            call_count += 1
            return str(call_count)

        mock_loader = MagicMock()
        mock_loader.get_prompt_variable_values.side_effect = [
            {"counter": incrementing_counter()},
            {"counter": incrementing_counter()},
        ]
        with (
            patch("radar.semantic.search_memories", side_effect=Exception),
            patch("radar.plugins.get_plugin_loader", return_value=mock_loader),
        ):
            prompt1, _ = _build_system_prompt()
            prompt2, _ = _build_system_prompt()

        assert "Counter: 1" in prompt1
        assert "Counter: 2" in prompt2
        assert mock_loader.get_prompt_variable_values.call_count == 2
