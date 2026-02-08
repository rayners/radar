"""Tests for conversation export (JSON & Markdown)."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from radar.export import export_json, export_markdown


# ---- Fixtures ----


@pytest.fixture
def sample_conversation(conversations_dir):
    """Create a sample conversation JSONL file with various message types."""
    conv_id = "test-conv-1234-abcd"
    conv_file = conversations_dir / f"{conv_id}.jsonl"
    messages = [
        {
            "timestamp": "2025-06-15T10:00:00",
            "role": "user",
            "content": "What is the weather?",
            "tool_calls": None,
            "tool_call_id": None,
        },
        {
            "timestamp": "2025-06-15T10:00:01",
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "weather",
                        "arguments": {"location": "Seattle"},
                    },
                }
            ],
            "tool_call_id": None,
        },
        {
            "timestamp": "2025-06-15T10:00:02",
            "role": "tool",
            "content": "72F, sunny",
            "tool_calls": None,
            "tool_call_id": "call_1",
        },
        {
            "timestamp": "2025-06-15T10:00:03",
            "role": "assistant",
            "content": "The weather in Seattle is 72F and sunny.",
            "tool_calls": None,
            "tool_call_id": None,
        },
    ]
    with open(conv_file, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
    return conv_id


@pytest.fixture
def empty_conversation(conversations_dir):
    """Create an empty conversation file."""
    conv_id = "test-empty-5678-efgh"
    conv_file = conversations_dir / f"{conv_id}.jsonl"
    conv_file.touch()
    return conv_id


# ---- TestExportJson ----


class TestExportJson:
    def test_exports_valid_json_array(self, sample_conversation):
        result = export_json(sample_conversation)
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 4

    def test_strips_internal_id_field(self, sample_conversation):
        result = export_json(sample_conversation)
        parsed = json.loads(result)
        for msg in parsed:
            assert "id" not in msg

    def test_includes_timestamps(self, sample_conversation):
        result = export_json(sample_conversation)
        parsed = json.loads(result)
        assert parsed[0]["timestamp"] == "2025-06-15T10:00:00"
        assert parsed[1]["timestamp"] == "2025-06-15T10:00:01"

    def test_includes_tool_calls(self, sample_conversation):
        result = export_json(sample_conversation)
        parsed = json.loads(result)
        assistant_with_tools = parsed[1]
        assert assistant_with_tools["tool_calls"] is not None
        assert assistant_with_tools["tool_calls"][0]["function"]["name"] == "weather"

    def test_empty_conversation_returns_empty_array(self, empty_conversation):
        result = export_json(empty_conversation)
        parsed = json.loads(result)
        assert parsed == []

    def test_missing_conversation_raises_value_error(self, conversations_dir):
        with pytest.raises(ValueError, match="Conversation not found"):
            export_json("nonexistent-conv-id")


# ---- TestExportMarkdown ----


class TestExportMarkdown:
    def test_includes_header_with_id_prefix(self, sample_conversation):
        result = export_markdown(sample_conversation)
        assert "# Conversation test-con" in result

    def test_includes_user_messages(self, sample_conversation):
        result = export_markdown(sample_conversation)
        assert "## User" in result
        assert "What is the weather?" in result

    def test_includes_assistant_messages(self, sample_conversation):
        result = export_markdown(sample_conversation)
        assert "## Assistant" in result
        assert "The weather in Seattle is 72F and sunny." in result

    def test_formats_tool_calls(self, sample_conversation):
        result = export_markdown(sample_conversation)
        assert "**Tool call: weather**" in result
        assert '"location": "Seattle"' in result

    def test_includes_tool_results(self, sample_conversation):
        result = export_markdown(sample_conversation)
        assert "> 72F, sunny" in result

    def test_includes_timestamps(self, sample_conversation):
        result = export_markdown(sample_conversation)
        assert "_2025-06-15 10:00:00_" in result

    def test_empty_conversation_has_header(self, empty_conversation):
        result = export_markdown(empty_conversation)
        assert "# Conversation test-emp" in result

    def test_missing_conversation_raises_value_error(self, conversations_dir):
        with pytest.raises(ValueError, match="Conversation not found"):
            export_markdown("nonexistent-conv-id")


# ---- TestExportCli ----


class TestExportCli:
    def test_json_to_stdout(self, sample_conversation):
        from radar.cli import cli

        runner = CliRunner()
        with patch("radar.export.export_json", return_value='[{"role": "user"}]') as mock_export:
            result = runner.invoke(cli, ["export", sample_conversation, "-f", "json"])
        assert result.exit_code == 0
        assert '[{"role": "user"}]' in result.output
        mock_export.assert_called_once_with(sample_conversation)

    def test_markdown_to_stdout(self, sample_conversation):
        from radar.cli import cli

        runner = CliRunner()
        with patch("radar.export.export_markdown", return_value="# Conversation\n") as mock_export:
            result = runner.invoke(cli, ["export", sample_conversation, "-f", "markdown"])
        assert result.exit_code == 0
        assert "# Conversation" in result.output
        mock_export.assert_called_once_with(sample_conversation)

    def test_output_to_file(self, sample_conversation, tmp_path):
        from radar.cli import cli

        output_file = tmp_path / "export.json"
        runner = CliRunner()
        with patch("radar.export.export_json", return_value='[]'):
            result = runner.invoke(cli, ["export", sample_conversation, "-o", str(output_file)])
        assert result.exit_code == 0
        assert "Exported to" in result.output
        assert output_file.read_text() == "[]"

    def test_missing_conversation_exits_with_error(self, conversations_dir):
        from radar.cli import cli

        runner = CliRunner()
        with patch("radar.export.export_json", side_effect=ValueError("Conversation not found: bad-id")):
            result = runner.invoke(cli, ["export", "bad-id"])
        assert result.exit_code == 1
        assert "Error" in result.output


# ---- TestExportWebRoute ----


class TestExportWebRoute:
    @pytest.fixture
    def client(self):
        from starlette.testclient import TestClient
        from radar.web import app
        return TestClient(app, raise_server_exceptions=False)

    def _no_auth(self):
        return patch("radar.web._requires_auth", return_value=(False, ""))

    def test_json_export_returns_200(self, client, sample_conversation):
        with self._no_auth(), patch("radar.export.export_json", return_value='[]'):
            resp = client.get(f"/api/export/{sample_conversation}?format=json")
        assert resp.status_code == 200
        assert "content-disposition" in resp.headers
        assert "attachment" in resp.headers["content-disposition"]
        assert ".json" in resp.headers["content-disposition"]

    def test_markdown_export_returns_200(self, client, sample_conversation):
        with self._no_auth(), patch("radar.export.export_markdown", return_value="# Conv\n"):
            resp = client.get(f"/api/export/{sample_conversation}?format=markdown")
        assert resp.status_code == 200
        assert ".md" in resp.headers["content-disposition"]

    def test_invalid_format_returns_400(self, client):
        with self._no_auth():
            resp = client.get("/api/export/some-id?format=pdf")
        assert resp.status_code == 400

    def test_missing_conversation_returns_404(self, client):
        with self._no_auth(), patch("radar.export.export_json", side_effect=ValueError("not found")):
            resp = client.get("/api/export/missing-id?format=json")
        assert resp.status_code == 404

    def test_content_disposition_uses_id_prefix(self, client, sample_conversation):
        with self._no_auth(), patch("radar.export.export_json", return_value='[]'):
            resp = client.get(f"/api/export/{sample_conversation}?format=json")
        assert f"conversation-{sample_conversation[:8]}" in resp.headers["content-disposition"]
