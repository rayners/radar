"""Integration tests exercising the agent -> LLM -> tool loop with a mock LLM."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_system_prompt():
    """Return a minimal system prompt (avoids semantic memory lookup)."""
    from radar.agent import PersonalityConfig
    return "You are a test assistant.", PersonalityConfig(content="You are a test assistant.")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSimpleQA:
    """User message -> LLM response with no tool calls."""

    def test_simple_qa_no_tools(self, mock_llm, isolated_data_dir):
        """Agent.run() returns the LLM's response and stores messages."""
        mock_llm.add_response(content="The capital of France is Paris.")

        with patch("radar.agent._build_system_prompt", return_value=_simple_system_prompt()):
            from radar.agent import run
            response_text, conv_id = run("What is the capital of France?")

        assert response_text == "The capital of France is Paris."
        assert conv_id  # non-empty conversation ID

        # Verify the LLM received the correct messages
        sent_messages = mock_llm.get_sent_messages()
        assert sent_messages[0]["role"] == "system"
        assert sent_messages[1]["role"] == "user"
        assert sent_messages[1]["content"] == "What is the capital of France?"

        # Verify conversation was stored
        from radar.memory import get_messages
        stored = get_messages(conv_id)
        roles = [m["role"] for m in stored]
        assert roles == ["user", "assistant"]
        assert stored[0]["content"] == "What is the capital of France?"
        assert stored[1]["content"] == "The capital of France is Paris."

    def test_simple_qa_empty_response(self, mock_llm, isolated_data_dir):
        """Agent handles an empty-string response from the LLM."""
        mock_llm.add_response(content="")

        with patch("radar.agent._build_system_prompt", return_value=_simple_system_prompt()):
            from radar.agent import run
            response_text, conv_id = run("Hello")

        assert response_text == ""


class TestToolCallFlow:
    """LLM requests a tool -> tool executes -> LLM gets result -> final response."""

    def test_tool_call_flow(self, mock_llm, isolated_data_dir):
        """Full tool call loop: LLM calls tool, gets result, produces final answer."""
        # First response: LLM wants to call a tool
        mock_llm.add_response(
            content="",
            tool_calls=[{
                "function": {
                    "name": "weather",
                    "arguments": {"location": "Seattle"},
                },
            }],
        )
        # Second response: LLM produces final answer after seeing tool result
        mock_llm.add_response(content="It is sunny and 72F in Seattle.")

        with (
            patch("radar.agent._build_system_prompt", return_value=_simple_system_prompt()),
            patch("radar.llm.execute_tool", return_value="Sunny, 72F") as mock_exec,
        ):
            from radar.agent import run
            response_text, conv_id = run("What's the weather in Seattle?")

        assert response_text == "It is sunny and 72F in Seattle."
        mock_exec.assert_called_once_with("weather", {"location": "Seattle"})

        # Two LLM calls: one that returned tool_calls, one that returned final answer
        assert mock_llm._call_count == 2

        # Verify the second call included the tool result message
        second_call_messages = mock_llm.get_sent_messages(-1)
        tool_messages = [m for m in second_call_messages if m["role"] == "tool"]
        assert len(tool_messages) == 1
        assert tool_messages[0]["content"] == "Sunny, 72F"

    def test_multiple_tool_calls_in_one_response(self, mock_llm, isolated_data_dir):
        """LLM can request multiple tool calls in a single response."""
        mock_llm.add_response(
            content="",
            tool_calls=[
                {"function": {"name": "weather", "arguments": {"location": "Seattle"}}},
                {"function": {"name": "weather", "arguments": {"location": "Portland"}}},
            ],
        )
        mock_llm.add_response(content="Seattle is sunny, Portland is rainy.")

        call_count = 0

        def mock_execute(name, args):
            nonlocal call_count
            call_count += 1
            if args.get("location") == "Seattle":
                return "Sunny, 72F"
            return "Rainy, 55F"

        with (
            patch("radar.agent._build_system_prompt", return_value=_simple_system_prompt()),
            patch("radar.llm.execute_tool", side_effect=mock_execute),
        ):
            from radar.agent import run
            response_text, _ = run("Weather in Seattle and Portland?")

        assert response_text == "Seattle is sunny, Portland is rainy."
        assert call_count == 2


class TestMultiTurnConversation:
    """Two sequential run() calls with the same conversation_id."""

    def test_multi_turn_conversation(self, mock_llm, isolated_data_dir):
        """Messages accumulate across multiple turns in the same conversation."""
        # Turn 1
        mock_llm.add_response(content="Hello! How can I help?")

        with patch("radar.agent._build_system_prompt", return_value=_simple_system_prompt()):
            from radar.agent import run
            resp1, conv_id = run("Hello")

        assert resp1 == "Hello! How can I help?"

        # Turn 2 (same conversation)
        mock_llm.add_response(content="I'm doing well, thanks for asking!")

        with patch("radar.agent._build_system_prompt", return_value=_simple_system_prompt()):
            resp2, conv_id2 = run("How are you?", conversation_id=conv_id)

        assert resp2 == "I'm doing well, thanks for asking!"
        assert conv_id2 == conv_id

        # The second LLM call should include the full conversation history
        second_call_messages = mock_llm.get_sent_messages(-1)
        # system + user("Hello") + assistant("Hello!...") + user("How are you?")
        roles = [m["role"] for m in second_call_messages]
        assert roles == ["system", "user", "assistant", "user"]
        assert second_call_messages[1]["content"] == "Hello"
        assert second_call_messages[3]["content"] == "How are you?"

        # Verify all messages stored
        from radar.memory import get_messages
        stored = get_messages(conv_id)
        stored_roles = [m["role"] for m in stored]
        assert stored_roles == ["user", "assistant", "user", "assistant"]


class TestMessageStorage:
    """Verify JSONL file content on disk matches expectations."""

    def test_message_storage_matches_expectations(self, mock_llm, isolated_data_dir):
        """JSONL file contains exactly the expected messages with correct fields."""
        mock_llm.add_response(content="42 is the answer.")

        with patch("radar.agent._build_system_prompt", return_value=_simple_system_prompt()):
            from radar.agent import run
            _, conv_id = run("What is the meaning of life?")

        # Read the raw JSONL file
        conv_file = isolated_data_dir / "conversations" / f"{conv_id}.jsonl"
        assert conv_file.exists()

        lines = [line.strip() for line in conv_file.read_text().splitlines() if line.strip()]
        assert len(lines) == 2

        msg1 = json.loads(lines[0])
        assert msg1["role"] == "user"
        assert msg1["content"] == "What is the meaning of life?"
        assert "timestamp" in msg1

        msg2 = json.loads(lines[1])
        assert msg2["role"] == "assistant"
        assert msg2["content"] == "42 is the answer."
        assert "timestamp" in msg2

    def test_tool_call_messages_stored(self, mock_llm, isolated_data_dir):
        """Tool call and tool result messages are stored in JSONL."""
        mock_llm.add_response(
            content="",
            tool_calls=[{
                "function": {
                    "name": "remember",
                    "arguments": {"content": "test fact"},
                },
            }],
        )
        mock_llm.add_response(content="Noted!")

        with (
            patch("radar.agent._build_system_prompt", return_value=_simple_system_prompt()),
            patch("radar.llm.execute_tool", return_value="Memory stored."),
        ):
            from radar.agent import run
            _, conv_id = run("Remember this fact")

        conv_file = isolated_data_dir / "conversations" / f"{conv_id}.jsonl"
        lines = [line.strip() for line in conv_file.read_text().splitlines() if line.strip()]
        # user + assistant(tool_calls) + tool(result) + assistant(final)
        assert len(lines) == 4

        roles = [json.loads(line)["role"] for line in lines]
        assert roles == ["user", "assistant", "tool", "assistant"]

        # Verify tool_calls field on assistant message
        assistant_tc = json.loads(lines[1])
        assert assistant_tc["tool_calls"] is not None
        assert assistant_tc["tool_calls"][0]["function"]["name"] == "remember"

        # Verify tool result message
        tool_msg = json.loads(lines[2])
        assert tool_msg["content"] == "Memory stored."

        # Verify final response
        final = json.loads(lines[3])
        assert final["content"] == "Noted!"
