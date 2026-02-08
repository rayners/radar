"""Tests for web route modules.

Verifies that the routes.py → routes/ package split preserved all
endpoints with correct status codes and response content.
"""

from unittest.mock import patch, MagicMock, AsyncMock

import httpx
import pytest
from starlette.testclient import TestClient

from radar.web import app


@pytest.fixture
def client():
    """Create a test client with localhost config (no auth required)."""
    return TestClient(app, raise_server_exceptions=False)


# ---------- helpers for mocking heavy dependencies ----------

def _mock_scheduler_status():
    return {
        "running": False,
        "last_heartbeat": None,
        "next_heartbeat": None,
        "pending_events": 0,
        "quiet_hours": False,
        "interval_minutes": 15,
        "quiet_hours_start": "23:00",
        "quiet_hours_end": "07:00",
    }


def _mock_config():
    cfg = MagicMock()
    cfg.llm.provider = "ollama"
    cfg.llm.base_url = "http://localhost:11434"
    cfg.llm.model = "test-model"
    cfg.llm.fallback_model = None
    cfg.llm.api_key = None
    cfg.embedding.provider = "none"
    cfg.embedding.model = ""
    cfg.notifications.url = ""
    cfg.notifications.topic = ""
    cfg.tools.max_file_size = 100000
    cfg.tools.exec_timeout = 30
    cfg.max_tool_iterations = 10
    cfg.web.host = "127.0.0.1"
    cfg.web.port = 8420
    cfg.web.auth_token = ""
    cfg.personality = "default"
    cfg.plugins.allow_llm_generated = False
    cfg.plugins.auto_approve = False
    cfg.plugins.auto_approve_if_tests_pass = False
    cfg.heartbeat.interval_minutes = 15
    cfg.watch_paths = []
    return cfg


@pytest.fixture(autouse=True)
def mock_common_deps():
    """Mock common dependencies used across most routes."""
    cfg = _mock_config()
    with (
        patch("radar.web.get_common_context") as mock_ctx,
        patch("radar.config.load_config", return_value=cfg),
        patch("radar.config.get_config", return_value=cfg),
        patch("radar.scheduler.get_status", return_value=_mock_scheduler_status()),
    ):
        def _ctx(request, active_page):
            return {
                "request": request,
                "active_page": active_page,
                "model": "test-model",
                "llm_provider": "ollama",
                "llm_url": "localhost:11434",
                "ntfy_configured": False,
                "heartbeat_status": "stopped",
                "heartbeat_label": "Scheduler Stopped",
            }
        mock_ctx.side_effect = _ctx
        yield


# ===== Auth Routes =====


class TestAuthRoutes:
    """Tests for auth.py routes."""

    def test_login_page_redirects_on_localhost(self, client):
        """GET /login redirects to / when no auth required."""
        resp = client.get("/login", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"

    def test_logout_clears_cookie(self, client):
        """GET /logout redirects to /login and clears cookie."""
        resp = client.get("/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login"

    def test_login_post_redirects_on_localhost(self, client):
        """POST /login redirects to / when no auth required."""
        resp = client.post("/login", data={"token": "whatever"}, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"


# ===== Dashboard Routes =====


class TestDashboardRoutes:
    """Tests for dashboard.py routes."""

    @patch("radar.memory.get_recent_activity", return_value=[])
    @patch("radar.memory.count_tool_calls_today", return_value=0)
    @patch("radar.memory.get_recent_conversations", return_value=[])
    def test_dashboard_page(self, mock_convs, mock_tc, mock_activity, client):
        resp = client.get("/")
        assert resp.status_code == 200

    @patch("radar.memory.get_recent_activity", return_value=[
        {"time": "2025-01-01T12:00", "message": "hello", "type": "chat"},
        {"time": "2025-01-01T12:01", "message": "Called weather", "type": "tool"},
    ])
    def test_api_activity_returns_html(self, mock_activity, client):
        resp = client.get("/api/activity")
        assert resp.status_code == 200
        assert "hello" in resp.text
        assert "Called weather" in resp.text
        assert "activity-log__item" in resp.text

    @patch("radar.memory.get_recent_activity", return_value=[])
    def test_api_activity_empty(self, mock_activity, client):
        resp = client.get("/api/activity")
        assert resp.status_code == 200
        assert "No recent activity" in resp.text

    def test_chat_page(self, client):
        resp = client.get("/chat")
        assert resp.status_code == 200

    @patch("radar.memory.get_recent_conversations", return_value=[])
    def test_history_page(self, mock_convs, client):
        resp = client.get("/history")
        assert resp.status_code == 200

    @patch("radar.semantic._get_connection")
    def test_memory_page(self, mock_conn, client):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.return_value.execute.return_value = mock_cursor
        resp = client.get("/memory")
        assert resp.status_code == 200


class TestApiHistory:
    """Tests for /api/history endpoint."""

    @patch("radar.memory.get_recent_conversations", return_value=[
        {"id": "abc-123", "created_at": "2025-01-15T10:30:00", "timestamp": "2025-01-15 10:30",
         "type": "chat", "summary": "Hello world", "tool_count": 2, "preview": "Hello world"},
    ])
    def test_returns_html_tr_elements(self, mock_convs, client):
        resp = client.get("/api/history")
        assert resp.status_code == 200
        assert "<tr>" in resp.text
        assert "Hello world" in resp.text
        assert "abc-123" in resp.text

    @patch("radar.memory.get_recent_conversations")
    def test_filter_param_passed_through(self, mock_convs, client):
        mock_convs.return_value = []
        client.get("/api/history?filter=heartbeat")
        mock_convs.assert_called_once_with(
            limit=20, offset=0, type_filter="heartbeat", search=None,
        )

    @patch("radar.memory.get_recent_conversations")
    def test_offset_param_passed_through(self, mock_convs, client):
        mock_convs.return_value = []
        client.get("/api/history?offset=40")
        mock_convs.assert_called_once_with(
            limit=20, offset=40, type_filter=None, search=None,
        )

    @patch("radar.memory.get_recent_conversations")
    def test_search_param_passed_through(self, mock_convs, client):
        mock_convs.return_value = []
        client.get("/api/history?search=weather")
        mock_convs.assert_called_once_with(
            limit=20, offset=0, type_filter=None, search="weather",
        )

    @patch("radar.memory.get_recent_conversations", return_value=[])
    def test_empty_state_message(self, mock_convs, client):
        resp = client.get("/api/history")
        assert resp.status_code == 200
        assert "No conversations found" in resp.text

    @patch("radar.memory.get_recent_conversations")
    def test_load_more_present_when_results_equal_limit(self, mock_convs, client):
        # Return exactly 20 results (== limit) to trigger Load More
        mock_convs.return_value = [
            {"id": f"id-{i}", "created_at": "", "timestamp": "", "type": "chat",
             "summary": f"msg {i}", "tool_count": 0, "preview": f"msg {i}"}
            for i in range(20)
        ]
        resp = client.get("/api/history")
        assert "Load More" in resp.text
        assert "offset=20" in resp.text

    @patch("radar.memory.get_recent_conversations")
    def test_no_load_more_when_results_less_than_limit(self, mock_convs, client):
        mock_convs.return_value = [
            {"id": "id-1", "created_at": "", "timestamp": "", "type": "chat",
             "summary": "msg", "tool_count": 0, "preview": "msg"},
        ]
        resp = client.get("/api/history")
        assert "Load More" not in resp.text

    @patch("radar.memory.get_recent_conversations", return_value=[
        {"id": "c1", "created_at": "2025-01-15T10:30:00", "timestamp": "2025-01-15 10:30",
         "type": "chat", "summary": "Test", "tool_count": 0, "preview": "Test"},
    ])
    def test_history_page_uses_enriched_data(self, mock_convs, client):
        resp = client.get("/history")
        assert resp.status_code == 200
        assert "2025-01-15 10:30" in resp.text

    @patch("radar.memory.get_recent_conversations")
    @patch("radar.conversation_search.search_conversations")
    def test_semantic_search_merges_results(self, mock_sem, mock_convs, client):
        """Semantic results are ordered first, then substring matches."""
        mock_sem.return_value = [
            {"conversation_id": "sem-1", "content": "semantic match", "score": 0.9},
        ]
        mock_convs.return_value = [
            {"id": "sub-1", "created_at": "", "timestamp": "", "type": "chat",
             "summary": "substring match", "tool_count": 0, "preview": "substring match"},
            {"id": "sem-1", "created_at": "", "timestamp": "", "type": "chat",
             "summary": "semantic match", "tool_count": 0, "preview": "semantic match"},
        ]
        resp = client.get("/api/history?search=test+query")
        assert resp.status_code == 200
        # Semantic result (sem-1) should appear before substring-only (sub-1)
        text = resp.text
        sem_pos = text.index("sem-1")
        sub_pos = text.index("sub-1")
        assert sem_pos < sub_pos


# ===== Conversation Delete Routes =====


class TestConversationDeleteRoutes:
    """Tests for DELETE /api/conversations/{id}."""

    @patch("radar.memory.delete_conversation", return_value=(True, "Deleted"))
    def test_successful_delete(self, mock_del, client):
        resp = client.delete("/api/conversations/abc-123")
        assert resp.status_code == 200
        assert resp.text == ""
        mock_del.assert_called_once_with("abc-123")

    @patch("radar.memory.delete_conversation", return_value=(False, "Conversation xyz not found"))
    def test_not_found(self, mock_del, client):
        resp = client.delete("/api/conversations/xyz")
        assert resp.status_code == 404

    @patch("radar.memory.delete_conversation", return_value=(False, "Cannot delete the heartbeat conversation"))
    def test_heartbeat_rejection(self, mock_del, client):
        resp = client.delete("/api/conversations/hb-id")
        assert resp.status_code == 400
        assert "heartbeat" in resp.text


# ===== Chat API Routes =====


class TestChatRoutes:
    """Tests for chat.py routes."""

    @patch("radar.agent.ask", return_value="test response")
    def test_api_ask(self, mock_ask, client):
        resp = client.post("/api/ask", data={"message": "hello"})
        assert resp.status_code == 200
        assert "test response" in resp.text
        assert "hello" in resp.text

    def test_api_ask_empty(self, client):
        resp = client.post("/api/ask", data={"message": ""})
        assert resp.status_code == 200
        assert "No message" in resp.text

    @patch("radar.memory.get_messages", return_value=[{}, {}, {}])
    @patch("radar.agent.run", return_value=("response text", "conv-123"))
    def test_api_chat(self, mock_run, mock_msgs, client):
        resp = client.post("/api/chat", data={"message": "hi"})
        assert resp.status_code == 200
        assert "conv-123" in resp.text
        assert "response text" in resp.text

    def test_api_chat_empty(self, client):
        resp = client.post("/api/chat", data={"message": ""})
        assert resp.status_code == 200
        assert resp.text == ""

    @patch("radar.feedback.store_feedback")
    def test_api_feedback_positive(self, mock_store, client):
        resp = client.post("/api/feedback", data={
            "conversation_id": "conv-1",
            "message_index": "0",
            "sentiment": "positive",
        })
        assert resp.status_code == 200
        assert "Recorded" in resp.text
        mock_store.assert_called_once()

    def test_api_feedback_invalid(self, client):
        resp = client.post("/api/feedback", data={
            "conversation_id": "",
            "message_index": "0",
            "sentiment": "positive",
        })
        assert resp.status_code == 400

    @patch("radar.agent.ask", return_value="personality response")
    def test_api_ask_passes_personality(self, mock_ask, client):
        resp = client.post("/api/ask", data={"message": "hello", "personality": "creative"})
        assert resp.status_code == 200
        mock_ask.assert_called_once_with("hello", personality="creative")

    @patch("radar.agent.ask", return_value="default response")
    def test_api_ask_no_personality_uses_default(self, mock_ask, client):
        resp = client.post("/api/ask", data={"message": "hello"})
        assert resp.status_code == 200
        mock_ask.assert_called_once_with("hello", personality=None)

    @patch("radar.memory.get_messages", return_value=[{}, {}, {}])
    @patch("radar.agent.run", return_value=("personality response", "conv-456"))
    def test_api_chat_passes_personality(self, mock_run, mock_msgs, client):
        resp = client.post("/api/chat", data={
            "message": "hi",
            "personality": "creative",
        })
        assert resp.status_code == 200
        mock_run.assert_called_once_with("hi", None, personality="creative")

    @patch("radar.memory.get_messages", return_value=[{}, {}, {}])
    @patch("radar.agent.run", return_value=("default response", "conv-789"))
    def test_api_chat_no_personality_uses_default(self, mock_run, mock_msgs, client):
        resp = client.post("/api/chat", data={"message": "hi"})
        assert resp.status_code == 200
        mock_run.assert_called_once_with("hi", None, personality=None)


class TestChatPersonalitySelector:
    """Tests for personality selector on the chat page."""

    @patch("radar.agent.get_personalities_dir")
    def test_chat_page_includes_personality_selector(self, mock_dir, tmp_path, client):
        pdir = tmp_path / "personalities"
        pdir.mkdir()
        (pdir / "default.md").write_text("# Default\nA test personality.")
        (pdir / "creative.md").write_text("# Creative\nA creative personality.")
        mock_dir.return_value = pdir
        resp = client.get("/chat")
        assert resp.status_code == 200
        assert '<select' in resp.text
        assert 'personality-select' in resp.text
        assert 'default' in resp.text
        assert 'creative' in resp.text


# ===== Tasks Routes =====


class TestTasksRoutes:
    """Tests for tasks.py routes."""

    @patch("radar.scheduled_tasks.list_tasks", return_value=[])
    def test_tasks_page(self, mock_list, client):
        resp = client.get("/tasks")
        assert resp.status_code == 200

    def test_tasks_add_form(self, client):
        resp = client.get("/tasks/add")
        assert resp.status_code == 200
        assert "Add Scheduled Task" in resp.text

    @patch("radar.scheduled_tasks.list_tasks", return_value=[])
    @patch("radar.scheduled_tasks.create_task")
    def test_api_tasks_create(self, mock_create, mock_list, client):
        resp = client.post("/api/tasks", data={
            "name": "test task",
            "message": "do something",
            "schedule_type": "daily",
            "time_of_day": "07:00",
        })
        assert resp.status_code == 200
        mock_create.assert_called_once()

    def test_api_tasks_create_missing_fields(self, client):
        resp = client.post("/api/tasks", data={"name": "", "message": ""})
        assert resp.status_code == 400

    @patch("radar.scheduled_tasks.delete_task", return_value=True)
    def test_api_tasks_delete(self, mock_del, client):
        resp = client.delete("/api/tasks/1")
        assert resp.status_code == 200

    @patch("radar.scheduled_tasks.delete_task", return_value=False)
    def test_api_tasks_delete_not_found(self, mock_del, client):
        resp = client.delete("/api/tasks/999")
        assert resp.status_code == 404

    @patch("radar.scheduler.add_event")
    @patch("radar.scheduled_tasks.get_task", return_value={"name": "t", "message": "m"})
    def test_api_tasks_run(self, mock_get, mock_event, client):
        resp = client.post("/api/tasks/1/run")
        assert resp.status_code == 200
        assert "Queued" in resp.text

    @patch("radar.scheduled_tasks.get_task", return_value=None)
    def test_api_tasks_run_not_found(self, mock_get, client):
        resp = client.post("/api/tasks/999/run")
        assert resp.status_code == 404

    @patch("radar.scheduled_tasks.list_tasks", return_value=[])
    @patch("radar.scheduled_tasks.disable_task")
    @patch("radar.scheduled_tasks.get_task", return_value={"enabled": True})
    def test_api_tasks_toggle_disable(self, mock_get, mock_disable, mock_list, client):
        resp = client.post("/api/tasks/1/toggle")
        assert resp.status_code == 200
        mock_disable.assert_called_once_with(1)

    @patch("radar.scheduled_tasks.list_tasks", return_value=[])
    @patch("radar.scheduled_tasks.enable_task")
    @patch("radar.scheduled_tasks.get_task", return_value={"enabled": False})
    def test_api_tasks_toggle_enable(self, mock_get, mock_enable, mock_list, client):
        resp = client.post("/api/tasks/1/toggle")
        assert resp.status_code == 200
        mock_enable.assert_called_once_with(1)

    @patch("radar.scheduler.trigger_heartbeat", return_value="Heartbeat triggered")
    def test_api_heartbeat_trigger(self, mock_hb, client):
        resp = client.post("/api/heartbeat/trigger")
        assert resp.status_code == 200
        assert "Heartbeat triggered" in resp.text


# ===== Memory Routes =====


class TestMemoryRoutes:
    """Tests for memory.py routes."""

    @patch("radar.semantic._get_connection")
    def test_api_memory_search_empty_query(self, mock_conn, client):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.return_value.execute.return_value = mock_cursor
        resp = client.get("/api/memory/search?q=")
        assert resp.status_code == 200
        assert "No memories found" in resp.text

    @patch("radar.semantic._get_connection")
    def test_api_memory_search_with_results(self, mock_conn, client):
        mock_row = {"id": 1, "content": "test fact", "created_at": "2025-01-01", "source": "manual"}
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [mock_row]
        mock_conn.return_value.execute.return_value = mock_cursor
        resp = client.get("/api/memory/search?q=")
        assert resp.status_code == 200
        assert "test fact" in resp.text

    @patch("radar.semantic.delete_memory", return_value=True)
    def test_api_memory_delete(self, mock_del, client):
        resp = client.delete("/api/memory/1")
        assert resp.status_code == 200

    @patch("radar.semantic.delete_memory", return_value=False)
    def test_api_memory_delete_not_found(self, mock_del, client):
        resp = client.delete("/api/memory/999")
        assert resp.status_code == 404

    def test_memory_add_form(self, client):
        resp = client.get("/memory/add")
        assert resp.status_code == 200
        assert "Add Memory" in resp.text

    def test_api_memory_create_empty(self, client):
        resp = client.post("/api/memory", data={"content": ""})
        assert resp.status_code == 400

    @patch("radar.semantic.store_memory", return_value=42)
    @patch("radar.semantic.is_embedding_available", return_value=True)
    def test_api_memory_create(self, mock_avail, mock_store, client):
        resp = client.post("/api/memory", data={"content": "remember this", "source": "test"})
        assert resp.status_code == 200
        assert "remember this" in resp.text

    @patch("radar.semantic.is_embedding_available", return_value=False)
    def test_api_memory_create_no_embeddings(self, mock_avail, client):
        resp = client.post("/api/memory", data={"content": "something"})
        assert resp.status_code == 400
        assert "Embedding provider" in resp.text


# ===== Config Routes =====


class TestConfigRoutes:
    """Tests for config.py routes."""

    @patch("radar.config.get_config_path", return_value=None)
    def test_config_page(self, mock_path, client):
        resp = client.get("/config")
        assert resp.status_code == 200

    def test_api_config_test_connection_error(self, client):
        resp = client.get("/api/config/test")
        assert resp.status_code == 200
        assert "Connection failed" in resp.text

    @patch("radar.config.reload_config")
    @patch("radar.config.get_config_path")
    def test_config_save_basic(self, mock_path, mock_reload, tmp_path, client):
        config_file = tmp_path / "radar.yaml"
        config_file.write_text("llm:\n  provider: ollama\n")
        mock_path.return_value = config_file
        resp = client.post("/api/config", data={
            "llm.provider": "ollama",
            "llm.model": "qwen3:latest",
        })
        assert resp.status_code == 200
        assert "saved" in resp.text.lower()
        mock_reload.assert_called_once()

    @patch("radar.config.reload_config")
    @patch("radar.config.get_config_path", return_value=None)
    def test_config_save_creates_file_if_missing(self, mock_path, mock_reload, tmp_path, client, monkeypatch):
        # Point home to tmp_path so it creates config there
        monkeypatch.setenv("HOME", str(tmp_path))
        resp = client.post("/api/config", data={
            "llm.provider": "ollama",
            "llm.model": "test-model",
        })
        assert resp.status_code == 200
        config_file = tmp_path / ".config" / "radar" / "radar.yaml"
        assert config_file.exists()

    @patch("radar.config.reload_config")
    @patch("radar.config.get_config_path")
    def test_config_save_preserves_existing_fields(self, mock_path, mock_reload, tmp_path, client):
        import yaml
        config_file = tmp_path / "radar.yaml"
        config_file.write_text("llm:\n  provider: ollama\n  base_url: http://localhost:11434\nembedding:\n  provider: none\n")
        mock_path.return_value = config_file
        # Only update the model, should preserve base_url and embedding
        resp = client.post("/api/config", data={"llm.model": "new-model"})
        assert resp.status_code == 200
        saved = yaml.safe_load(config_file.read_text())
        assert saved["llm"]["base_url"] == "http://localhost:11434"
        assert saved["llm"]["model"] == "new-model"
        assert saved["embedding"]["provider"] == "none"

    def test_config_save_invalid_provider(self, client):
        with patch("radar.config.get_config_path", return_value=None):
            resp = client.post("/api/config", data={"llm.provider": "invalid"})
            assert resp.status_code == 400
            assert "Invalid LLM provider" in resp.text

    def test_config_save_invalid_numeric(self, client):
        with patch("radar.config.get_config_path", return_value=None):
            resp = client.post("/api/config", data={"tools.max_file_size": "not-a-number"})
            assert resp.status_code == 400
            assert "Invalid value" in resp.text

    @patch("radar.config.reload_config")
    @patch("radar.config.get_config_path")
    def test_config_save_coerces_numeric_types(self, mock_path, mock_reload, tmp_path, client):
        import yaml
        config_file = tmp_path / "radar.yaml"
        config_file.write_text("")
        mock_path.return_value = config_file
        resp = client.post("/api/config", data={
            "tools.max_file_size": "200000",
            "tools.exec_timeout": "60",
            "max_tool_iterations": "20",
        })
        assert resp.status_code == 200
        saved = yaml.safe_load(config_file.read_text())
        assert saved["tools"]["max_file_size"] == 200000
        assert saved["tools"]["exec_timeout"] == 60
        assert saved["max_tool_iterations"] == 20


# ===== Logs Routes =====


class TestLogsRoutes:
    """Tests for logs.py routes."""

    @patch("radar.logging.get_uptime", return_value="1h 2m")
    @patch("radar.logging.get_log_stats", return_value={"error_count": 0, "warn_count": 0, "api_calls": 0})
    @patch("radar.logging.get_logs", return_value=[])
    def test_logs_page(self, mock_logs, mock_stats, mock_uptime, client):
        resp = client.get("/logs")
        assert resp.status_code == 200

    @patch("radar.logging.get_logs", return_value=[])
    def test_api_logs_empty(self, mock_logs, client):
        resp = client.get("/api/logs")
        assert resp.status_code == 200
        assert "No log entries" in resp.text

    @patch("radar.logging.get_logs", return_value=[
        {"timestamp": "2025-01-01T12:00:00", "level": "info", "message": "test log"}
    ])
    def test_api_logs_with_entries(self, mock_logs, client):
        resp = client.get("/api/logs")
        assert resp.status_code == 200
        assert "test log" in resp.text
        assert "12:00:00" in resp.text

    @patch("radar.logging.get_recent_entries", return_value=[])
    def test_api_logs_stream_empty(self, mock_entries, client):
        resp = client.get("/api/logs/stream")
        assert resp.status_code == 200
        assert resp.text == ""

    @patch("radar.logging.get_recent_entries", return_value=[
        {"timestamp": "2025-01-01T13:00:00", "level": "warn", "message": "warning msg"}
    ])
    def test_api_logs_stream_with_entries(self, mock_entries, client):
        resp = client.get("/api/logs/stream?since=2025-01-01T12:00:00")
        assert resp.status_code == 200
        assert "warning msg" in resp.text


# ===== Personalities Routes =====


class TestPersonalitiesRoutes:
    """Tests for personalities.py routes."""

    @patch("radar.agent.get_personalities_dir")
    def test_personalities_page(self, mock_dir, tmp_path, client):
        pdir = tmp_path / "personalities"
        pdir.mkdir()
        (pdir / "default.md").write_text("# Default\nA test personality.")
        mock_dir.return_value = pdir
        resp = client.get("/personalities")
        assert resp.status_code == 200

    @patch("radar.agent.get_personalities_dir")
    def test_api_personalities_list(self, mock_dir, tmp_path, client):
        pdir = tmp_path / "personalities"
        pdir.mkdir()
        (pdir / "default.md").write_text("# Default\nA test.")
        mock_dir.return_value = pdir
        resp = client.get("/api/personalities")
        assert resp.status_code == 200
        data = resp.json()
        assert "personalities" in data
        assert len(data["personalities"]) == 1

    @patch("radar.agent.load_personality", return_value="# Test content")
    def test_api_personality_get(self, mock_load, client):
        resp = client.get("/api/personalities/default")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "default"
        assert "Test content" in data["content"]

    @patch("radar.agent.get_personalities_dir")
    def test_api_personality_update(self, mock_dir, tmp_path, client):
        pdir = tmp_path / "personalities"
        pdir.mkdir()
        (pdir / "test.md").write_text("old")
        mock_dir.return_value = pdir
        resp = client.put("/api/personalities/test", data={"content": "new content"})
        assert resp.status_code == 200
        assert "saved" in resp.text
        assert (pdir / "test.md").read_text() == "new content"

    def test_api_personality_create_empty_name(self, client):
        resp = client.post("/api/personalities", data={"name": ""})
        assert resp.status_code == 400

    def test_api_personality_create_invalid_name(self, client):
        resp = client.post("/api/personalities", data={"name": "bad name!"})
        assert resp.status_code == 400

    def test_api_personality_delete_default(self, client):
        resp = client.delete("/api/personalities/default")
        assert resp.status_code == 400
        assert "Cannot delete default" in resp.text

    def test_api_personality_delete_active(self, client):
        resp = client.delete("/api/personalities/default")
        assert resp.status_code == 400
        # "default" is the active personality in mock config

    @patch("radar.feedback.get_feedback_summary", return_value={"total": 0, "positive": 0, "negative": 0})
    @patch("radar.feedback.get_pending_suggestions", return_value=[])
    def test_personality_suggestions_page(self, mock_sug, mock_summary, client):
        resp = client.get("/personalities/suggestions")
        assert resp.status_code == 200

    @patch("radar.feedback.get_feedback_summary", return_value={"total": 5, "positive": 3, "negative": 2})
    def test_api_feedback_summary(self, mock_summary, client):
        resp = client.get("/api/feedback/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5


# ===== Plugin Routes =====


class TestPluginRoutes:
    """Tests for plugins.py routes."""

    @patch("radar.plugins.get_plugin_loader")
    def test_plugins_page(self, mock_loader, client):
        loader = MagicMock()
        loader.list_plugins.return_value = []
        loader.list_pending.return_value = []
        mock_loader.return_value = loader
        resp = client.get("/plugins")
        assert resp.status_code == 200

    @patch("radar.plugins.get_plugin_loader")
    def test_plugins_review_page(self, mock_loader, client):
        loader = MagicMock()
        loader.list_pending.return_value = []
        mock_loader.return_value = loader
        resp = client.get("/plugins/review")
        assert resp.status_code == 200

    @patch("radar.plugins.get_plugin_loader")
    def test_api_plugin_enable(self, mock_loader, client):
        loader = MagicMock()
        loader.enable_plugin.return_value = (True, "enabled")
        loader.list_plugins.return_value = [
            {"name": "test_plugin", "version": "1.0", "description": "A test", "enabled": True}
        ]
        mock_loader.return_value = loader
        resp = client.post("/api/plugins/test_plugin/enable")
        assert resp.status_code == 200
        assert "test_plugin" in resp.text

    @patch("radar.plugins.get_plugin_loader")
    def test_api_plugin_enable_fail(self, mock_loader, client):
        loader = MagicMock()
        loader.enable_plugin.return_value = (False, "not found")
        mock_loader.return_value = loader
        resp = client.post("/api/plugins/bad/enable")
        assert resp.status_code == 400

    @patch("radar.plugins.get_plugin_loader")
    def test_api_plugin_disable(self, mock_loader, client):
        loader = MagicMock()
        loader.disable_plugin.return_value = (True, "disabled")
        loader.list_plugins.return_value = [
            {"name": "test_plugin", "version": "1.0", "description": "A test", "enabled": False}
        ]
        mock_loader.return_value = loader
        resp = client.post("/api/plugins/test_plugin/disable")
        assert resp.status_code == 200

    @patch("radar.plugins.get_plugin_loader")
    def test_api_plugin_approve(self, mock_loader, client):
        loader = MagicMock()
        loader.approve_plugin.return_value = (True, "approved")
        mock_loader.return_value = loader
        resp = client.post("/api/plugins/test_plugin/approve")
        assert resp.status_code == 200
        assert "Approved" in resp.text

    @patch("radar.plugins.get_plugin_loader")
    def test_api_plugin_reject(self, mock_loader, client):
        loader = MagicMock()
        loader.reject_plugin.return_value = (True, "rejected")
        mock_loader.return_value = loader
        resp = client.post("/api/plugins/test_plugin/reject", data={"reason": "bad"})
        assert resp.status_code == 200

    @patch("radar.plugins.get_plugin_loader")
    def test_api_plugin_update_code_success(self, mock_loader, client):
        loader = MagicMock()
        loader.update_plugin_code.return_value = (True, "Code updated", None)
        mock_loader.return_value = loader
        resp = client.put("/api/plugins/test_plugin/code", data={"code": "print('hi')"})
        assert resp.status_code == 200

    @patch("radar.plugins.get_plugin_loader")
    def test_api_plugin_update_code_fail(self, mock_loader, client):
        loader = MagicMock()
        loader.update_plugin_code.return_value = (False, "Validation failed", {
            "test_results": [{"passed": False, "name": "test1", "error": "syntax error"}]
        })
        mock_loader.return_value = loader
        resp = client.put("/api/plugins/test_plugin/code", data={"code": "bad"})
        assert resp.status_code == 400

    @patch("radar.plugins.get_plugin_loader")
    def test_api_plugin_rollback(self, mock_loader, client):
        loader = MagicMock()
        loader.rollback_plugin.return_value = (True, "Rolled back to v1")
        mock_loader.return_value = loader
        resp = client.post("/api/plugins/test_plugin/rollback/v1")
        assert resp.status_code == 200
        assert "Rolled back" in resp.text

    @patch("radar.plugins.get_plugin_loader")
    def test_api_plugin_rollback_fail(self, mock_loader, client):
        loader = MagicMock()
        loader.rollback_plugin.return_value = (False, "Version not found")
        mock_loader.return_value = loader
        resp = client.post("/api/plugins/test_plugin/rollback/v99")
        assert resp.status_code == 400


# ===== Health Routes =====


class TestHealthRoutes:
    """Tests for health.py routes."""

    @patch("radar.logging.get_log_stats", return_value={"error_count": 0, "warn_count": 2, "api_calls": 42})
    @patch("radar.logging.get_uptime", return_value="3d 14h")
    def test_health_basic(self, mock_uptime, mock_stats, client):
        """GET /health returns 200 with basic health info."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("healthy", "degraded")
        assert data["uptime"] == "3d 14h"
        assert "scheduler" in data
        assert "stats" in data
        assert data["stats"]["warnings_24h"] == 2
        assert data["stats"]["api_calls"] == 42
        # Service sections should NOT appear without check_services
        assert "llm" not in data
        assert "embeddings" not in data
        assert "database" not in data

    @patch("radar.semantic._get_connection")
    @patch("radar.web.routes.health.httpx.AsyncClient")
    @patch("radar.logging.get_log_stats", return_value={"error_count": 0, "warn_count": 0, "api_calls": 0})
    @patch("radar.logging.get_uptime", return_value="1h")
    @patch("radar.scheduler.get_status", return_value={
        "running": True, "last_heartbeat": None, "next_heartbeat": None,
        "pending_events": 0, "quiet_hours": False,
        "interval_minutes": 15, "quiet_hours_start": "23:00", "quiet_hours_end": "07:00",
    })
    def test_health_with_services(self, mock_sched, mock_uptime, mock_stats,
                                  mock_httpx, mock_db_conn, client):
        """GET /health?check_services=true includes llm, embeddings, database."""
        # Mock httpx responses
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.return_value = mock_client_instance

        # Mock DB
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = [128]
        mock_conn = MagicMock()
        mock_conn.execute.return_value = mock_cursor
        mock_db_conn.return_value = mock_conn

        resp = client.get("/health?check_services=true")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "llm" in data
        assert data["llm"]["status"] == "ok"
        assert data["llm"]["provider"] == "ollama"
        assert "embeddings" in data
        assert "database" in data
        assert data["database"]["status"] == "ok"
        assert data["database"]["memory_count"] == 128

    @patch("radar.web.routes.health.httpx.AsyncClient")
    @patch("radar.logging.get_log_stats", return_value={"error_count": 0, "warn_count": 0, "api_calls": 0})
    @patch("radar.logging.get_uptime", return_value="1h")
    @patch("radar.scheduler.get_status", return_value={
        "running": True, "last_heartbeat": None, "next_heartbeat": None,
        "pending_events": 0, "quiet_hours": False,
        "interval_minutes": 15, "quiet_hours_start": "23:00", "quiet_hours_end": "07:00",
    })
    def test_health_llm_unreachable(self, mock_sched, mock_uptime, mock_stats,
                                    mock_httpx, client):
        """LLM unreachable sets overall status to unhealthy."""
        # Mock httpx to raise ConnectError
        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.return_value = mock_client_instance

        resp = client.get("/health?check_services=true")
        assert resp.status_code == 200
        data = resp.json()
        assert data["llm"]["status"] == "unreachable"
        assert data["status"] == "unhealthy"

    @patch("radar.logging.get_log_stats", return_value={"error_count": 3, "warn_count": 1, "api_calls": 10})
    @patch("radar.logging.get_uptime", return_value="5h")
    @patch("radar.scheduler.get_status", return_value={
        "running": False, "last_heartbeat": None, "next_heartbeat": None,
        "pending_events": 0, "quiet_hours": False,
        "interval_minutes": 15, "quiet_hours_start": "23:00", "quiet_hours_end": "07:00",
    })
    def test_health_degraded(self, mock_sched, mock_uptime, mock_stats, client):
        """Scheduler stopped + errors > 0 sets status to degraded."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"

    @patch("radar.logging.get_log_stats", return_value={"error_count": 0, "warn_count": 0, "api_calls": 0})
    @patch("radar.logging.get_uptime", return_value="1h")
    def test_health_no_auth_required(self, mock_uptime, mock_stats, client):
        """Health endpoint works even when auth is configured."""
        cfg = _mock_config()
        cfg.web.host = "0.0.0.0"
        cfg.web.auth_token = "secret-token"
        with (
            patch("radar.config.get_config", return_value=cfg),
            patch("radar.web._requires_auth", return_value=(True, "secret-token")),
        ):
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert "status" in data
