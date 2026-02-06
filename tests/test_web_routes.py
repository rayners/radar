"""Tests for web route modules.

Verifies that the routes.py → routes/ package split preserved all
endpoints with correct status codes and response content.
"""

from unittest.mock import patch, MagicMock

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

    @patch("radar.memory.get_recent_conversations", return_value=[])
    def test_dashboard_page(self, mock_convs, client):
        resp = client.get("/")
        assert resp.status_code == 200

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
