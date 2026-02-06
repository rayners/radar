"""Tests for radar/llm.py — LLM client, format conversion, tool loops."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from radar.llm import (
    _chat_ollama,
    _chat_openai,
    _convert_messages_from_openai,
    _convert_messages_to_openai,
    _convert_openai_to_ollama_format,
    _convert_tools_to_openai,
    _is_rate_limit_error,
    _openai_message_to_dict,
    chat,
)


# ── Helpers ────────────────────────────────────────────────────────


def _make_config(provider="ollama", model="test-model", base_url="http://localhost:11434",
                 fallback_model="", max_tool_iterations=10):
    """Build a minimal config-like object for LLM tests."""
    llm = SimpleNamespace(
        provider=provider, model=model, base_url=base_url,
        api_key="", fallback_model=fallback_model,
    )
    return SimpleNamespace(llm=llm, max_tool_iterations=max_tool_iterations)


def _make_ollama_response(content, tool_calls=None, status_code=200):
    """Build a mock httpx.Response for Ollama chat."""
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = {"message": message}
    resp.raise_for_status = MagicMock()
    return resp


def _make_openai_message(content, tool_calls=None):
    """Build a mock OpenAI ChatCompletionMessage."""
    msg = SimpleNamespace(role="assistant", content=content, tool_calls=tool_calls)
    return msg


def _make_openai_tool_call(tc_id, name, arguments_json):
    """Build a mock OpenAI tool call object."""
    func = SimpleNamespace(name=name, arguments=arguments_json)
    return SimpleNamespace(id=tc_id, type="function", function=func)


# ── Rate limit detection ───────────────────────────────────────────


class TestIsRateLimitError:
    """_is_rate_limit_error checks status codes and error text."""

    def test_429_is_rate_limit(self):
        assert _is_rate_limit_error(429, "") is True

    def test_503_is_rate_limit(self):
        assert _is_rate_limit_error(503, "") is True

    def test_200_not_rate_limit(self):
        assert _is_rate_limit_error(200, "") is False

    def test_text_rate_limit(self):
        assert _is_rate_limit_error(None, "Rate limit exceeded") is True

    def test_text_temporarily_unavailable(self):
        assert _is_rate_limit_error(None, "Service temporarily unavailable") is True

    def test_unrelated_error(self):
        assert _is_rate_limit_error(500, "Internal server error") is False


# ── Tool format conversion ─────────────────────────────────────────


class TestConvertToolsToOpenai:
    """_convert_tools_to_openai wraps with type:function."""

    def test_wraps_tools(self):
        ollama_tools = [
            {"function": {"name": "weather", "description": "Get weather", "parameters": {"type": "object"}}}
        ]
        result = _convert_tools_to_openai(ollama_tools)
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "weather"

    def test_empty_list(self):
        assert _convert_tools_to_openai([]) == []


# ── Message conversion ─────────────────────────────────────────────


class TestConvertMessagesToOpenai:
    """_convert_messages_to_openai adds IDs and stringifies args."""

    def test_basic_messages(self):
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        result = _convert_messages_to_openai(msgs)
        assert result[0]["role"] == "system"
        assert result[1]["content"] == "Hi"

    def test_tool_calls_get_ids(self):
        msgs = [{"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "search", "arguments": {"q": "test"}}},
        ]}]
        result = _convert_messages_to_openai(msgs)
        tc = result[0]["tool_calls"][0]
        assert tc["id"] == "call_0"
        assert tc["type"] == "function"
        assert isinstance(tc["function"]["arguments"], str)
        assert json.loads(tc["function"]["arguments"]) == {"q": "test"}

    def test_string_arguments_preserved(self):
        msgs = [{"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "t", "arguments": '{"key": "val"}'}},
        ]}]
        result = _convert_messages_to_openai(msgs)
        assert result[0]["tool_calls"][0]["function"]["arguments"] == '{"key": "val"}'


class TestConvertMessagesFromOpenai:
    """_convert_messages_from_openai reverses the conversion."""

    def test_basic_roundtrip(self):
        msgs = [{"role": "user", "content": "hello"}]
        result = _convert_messages_from_openai(msgs)
        assert result[0]["content"] == "hello"

    def test_tool_calls_args_parsed(self):
        msgs = [{"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "t", "arguments": '{"k": "v"}'}},
        ]}]
        result = _convert_messages_from_openai(msgs)
        assert result[0]["tool_calls"][0]["function"]["arguments"] == {"k": "v"}

    def test_tool_call_id_dropped(self):
        msgs = [{"role": "tool", "tool_call_id": "call_0", "content": "result"}]
        result = _convert_messages_from_openai(msgs)
        assert "tool_call_id" not in result[0]


class TestOpenaiMessageToDict:
    """_openai_message_to_dict converts mock message objects."""

    def test_simple_message(self):
        msg = _make_openai_message("Hello!")
        result = _openai_message_to_dict(msg)
        assert result == {"role": "assistant", "content": "Hello!"}

    def test_with_tool_calls(self):
        tc = _make_openai_tool_call("call_1", "weather", '{"city": "NYC"}')
        msg = _make_openai_message("", tool_calls=[tc])
        result = _openai_message_to_dict(msg)
        assert result["tool_calls"][0]["id"] == "call_1"
        assert result["tool_calls"][0]["function"]["name"] == "weather"

    def test_none_content(self):
        msg = _make_openai_message(None)
        result = _openai_message_to_dict(msg)
        assert result["content"] == ""


class TestConvertOpenaiToOllamaFormat:
    """_convert_openai_to_ollama_format converts message objects."""

    def test_simple_message(self):
        msg = _make_openai_message("response text")
        result = _convert_openai_to_ollama_format(msg)
        assert result == {"role": "assistant", "content": "response text"}

    def test_with_tool_calls(self):
        tc = _make_openai_tool_call("id1", "search", '{"q": "test"}')
        msg = _make_openai_message("", tool_calls=[tc])
        result = _convert_openai_to_ollama_format(msg)
        assert result["tool_calls"][0]["function"]["name"] == "search"
        assert result["tool_calls"][0]["function"]["arguments"] == {"q": "test"}

    def test_none_content(self):
        msg = _make_openai_message(None)
        result = _convert_openai_to_ollama_format(msg)
        assert result["content"] == ""


# ── _chat_ollama ───────────────────────────────────────────────────


class TestChatOllama:
    """_chat_ollama tool loop with mocked httpx.post."""

    @patch("radar.llm._log_api_call")
    @patch("radar.llm.httpx.post")
    def test_simple_response(self, mock_post, mock_log):
        mock_post.return_value = _make_ollama_response("Hello!")
        config = _make_config()
        msg, history = _chat_ollama(
            [{"role": "user", "content": "hi"}],
            use_tools=False, config=config,
        )
        assert msg["content"] == "Hello!"
        assert len(history) == 2  # user + assistant

    @patch("radar.llm._log_api_call")
    @patch("radar.llm.execute_tool", return_value="tool result")
    @patch("radar.llm.get_tools_schema", return_value=[{"function": {"name": "t"}}])
    @patch("radar.llm.httpx.post")
    def test_tool_call_loop(self, mock_post, mock_schema, mock_exec, mock_log):
        # First call returns tool call, second returns final answer
        tool_call_resp = _make_ollama_response("", tool_calls=[
            {"function": {"name": "weather", "arguments": {"city": "NYC"}}},
        ])
        final_resp = _make_ollama_response("It's sunny!")
        mock_post.side_effect = [tool_call_resp, final_resp]

        config = _make_config()
        msg, history = _chat_ollama(
            [{"role": "user", "content": "weather?"}],
            use_tools=True, config=config,
        )
        assert msg["content"] == "It's sunny!"
        mock_exec.assert_called_once_with("weather", {"city": "NYC"})
        # user + assistant(tool_call) + tool(result) + assistant(final)
        assert len(history) == 4

    @patch("radar.llm._log_api_call")
    @patch("radar.llm.execute_tool", return_value="result")
    @patch("radar.llm.get_tools_schema", return_value=[{"function": {"name": "t"}}])
    @patch("radar.llm.httpx.post")
    def test_max_iterations_cap(self, mock_post, mock_schema, mock_exec, mock_log):
        # Always return tool calls — should stop at max_tool_iterations
        tool_resp = _make_ollama_response("", tool_calls=[
            {"function": {"name": "loop_tool", "arguments": {}}},
        ])
        mock_post.return_value = tool_resp

        config = _make_config(max_tool_iterations=3)
        msg, _ = _chat_ollama(
            [{"role": "user", "content": "loop"}],
            use_tools=True, config=config,
        )
        assert "maximum" in msg["content"].lower()
        assert mock_post.call_count == 3

    @patch("radar.llm._log_api_call")
    @patch("radar.llm.httpx.post", side_effect=httpx.TimeoutException("timeout"))
    def test_timeout_error(self, mock_post, mock_log):
        config = _make_config()
        with pytest.raises(RuntimeError, match="timed out"):
            _chat_ollama(
                [{"role": "user", "content": "hi"}],
                use_tools=False, config=config,
            )

    @patch("radar.llm._log_api_call")
    @patch("radar.llm.httpx.post", side_effect=httpx.ConnectError("refused"))
    def test_connect_error(self, mock_post, mock_log):
        config = _make_config()
        with pytest.raises(RuntimeError, match="Cannot connect"):
            _chat_ollama(
                [{"role": "user", "content": "hi"}],
                use_tools=False, config=config,
            )

    @patch("radar.llm._log_api_call")
    @patch("radar.llm._log_fallback")
    @patch("radar.llm.httpx.post")
    def test_rate_limit_fallback(self, mock_post, mock_fallback_log, mock_log):
        # First call raises 429, second succeeds with fallback model
        error_response = MagicMock(spec=httpx.Response)
        error_response.status_code = 429
        error_response.text = "Rate limit exceeded"
        rate_limit_exc = httpx.HTTPStatusError(
            "429", request=MagicMock(), response=error_response
        )

        success_resp = _make_ollama_response("Fallback answer!")
        mock_post.side_effect = [rate_limit_exc, success_resp]

        config = _make_config(fallback_model="fallback-model")
        msg, _ = _chat_ollama(
            [{"role": "user", "content": "hi"}],
            use_tools=False, config=config,
        )
        assert msg["content"] == "Fallback answer!"
        # Verify the second call used fallback model
        second_call_payload = mock_post.call_args_list[1][1]["json"]
        assert second_call_payload["model"] == "fallback-model"

    @patch("radar.llm._log_api_call")
    @patch("radar.llm.httpx.post")
    def test_no_fallback_without_config(self, mock_post, mock_log):
        error_response = MagicMock(spec=httpx.Response)
        error_response.status_code = 429
        error_response.text = "Rate limit"
        mock_post.side_effect = httpx.HTTPStatusError(
            "429", request=MagicMock(), response=error_response
        )
        config = _make_config(fallback_model="")
        with pytest.raises(RuntimeError, match="429"):
            _chat_ollama(
                [{"role": "user", "content": "hi"}],
                use_tools=False, config=config,
            )

    @patch("radar.llm._log_api_call")
    @patch("radar.llm.execute_tool", return_value="parsed ok")
    @patch("radar.llm.get_tools_schema", return_value=[{"function": {"name": "t"}}])
    @patch("radar.llm.httpx.post")
    def test_tool_args_string_parsed(self, mock_post, mock_schema, mock_exec, mock_log):
        """Tool arguments that arrive as a JSON string are parsed to dict."""
        tool_resp = _make_ollama_response("", tool_calls=[
            {"function": {"name": "search", "arguments": '{"q": "hello"}'}},
        ])
        final_resp = _make_ollama_response("Done")
        mock_post.side_effect = [tool_resp, final_resp]

        config = _make_config()
        _chat_ollama(
            [{"role": "user", "content": "search"}],
            use_tools=True, config=config,
        )
        mock_exec.assert_called_once_with("search", {"q": "hello"})

    @patch("radar.llm._log_api_call")
    @patch("radar.llm.httpx.post")
    def test_model_override(self, mock_post, mock_log):
        mock_post.return_value = _make_ollama_response("ok")
        config = _make_config(model="default-model")
        _chat_ollama(
            [{"role": "user", "content": "hi"}],
            use_tools=False, config=config,
            model_override="override-model",
        )
        payload = mock_post.call_args[1]["json"]
        assert payload["model"] == "override-model"


# ── _chat_openai ───────────────────────────────────────────────────


class TestChatOpenai:
    """_chat_openai tool loop with mocked OpenAI client."""

    @patch("radar.llm._log_api_call")
    def test_simple_response(self, mock_log):
        mock_client = MagicMock()
        msg_obj = _make_openai_message("Hello from OpenAI!")
        mock_client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=msg_obj)]
        )

        config = _make_config(provider="openai")
        with patch("openai.OpenAI", return_value=mock_client):
            msg, _ = _chat_openai(
                [{"role": "user", "content": "hi"}],
                use_tools=False, config=config,
            )
        assert msg["content"] == "Hello from OpenAI!"

    @patch("radar.llm._log_api_call")
    @patch("radar.llm.execute_tool", return_value="tool result")
    @patch("radar.llm.get_tools_schema", return_value=[
        {"function": {"name": "t", "description": "test", "parameters": {}}}
    ])
    def test_tool_call_loop(self, mock_schema, mock_exec, mock_log):
        mock_client = MagicMock()

        tc = _make_openai_tool_call("call_1", "weather", '{"city": "NYC"}')
        tool_msg = _make_openai_message("", tool_calls=[tc])
        final_msg = _make_openai_message("It's sunny!")

        mock_client.chat.completions.create.side_effect = [
            SimpleNamespace(choices=[SimpleNamespace(message=tool_msg)]),
            SimpleNamespace(choices=[SimpleNamespace(message=final_msg)]),
        ]

        config = _make_config(provider="openai")
        with patch("openai.OpenAI", return_value=mock_client):
            msg, _ = _chat_openai(
                [{"role": "user", "content": "weather"}],
                use_tools=True, config=config,
            )
        assert msg["content"] == "It's sunny!"
        mock_exec.assert_called_once_with("weather", {"city": "NYC"})

    @patch("radar.llm._log_api_call")
    @patch("radar.llm._log_fallback")
    def test_rate_limit_fallback(self, mock_fallback_log, mock_log):
        mock_client = MagicMock()

        # First call raises rate limit, second succeeds
        exc = Exception("Rate limit exceeded")
        exc.status_code = 429
        final_msg = _make_openai_message("Fallback!")

        mock_client.chat.completions.create.side_effect = [
            exc,
            SimpleNamespace(choices=[SimpleNamespace(message=final_msg)]),
        ]

        config = _make_config(provider="openai", fallback_model="fallback")
        with patch("openai.OpenAI", return_value=mock_client):
            msg, _ = _chat_openai(
                [{"role": "user", "content": "hi"}],
                use_tools=False, config=config,
            )
        assert msg["content"] == "Fallback!"


# ── chat() dispatch ────────────────────────────────────────────────


class TestChatDispatch:
    """chat() dispatches to the correct backend."""

    @patch("radar.llm.get_config")
    @patch("radar.llm._chat_ollama", return_value=({"content": "ok"}, []))
    def test_dispatches_to_ollama(self, mock_ollama, mock_config):
        mock_config.return_value = _make_config(provider="ollama")
        chat([{"role": "user", "content": "hi"}])
        mock_ollama.assert_called_once()

    @patch("radar.llm.get_config")
    @patch("radar.llm._chat_openai", return_value=({"content": "ok"}, []))
    def test_dispatches_to_openai(self, mock_openai, mock_config):
        mock_config.return_value = _make_config(provider="openai")
        chat([{"role": "user", "content": "hi"}])
        mock_openai.assert_called_once()
