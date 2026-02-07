"""Mock LLM responder for integration tests.

Replaces httpx.post at the HTTP layer so the real chat() tool loop
in radar/llm.py still executes, but responses are scripted.
"""

import copy

import httpx


class MockLLMResponder:
    """Scriptable mock for httpx.post that mimics Ollama API responses."""

    def __init__(self):
        self._responses = []  # Queue of responses
        self._call_count = 0
        self._calls = []  # Recorded calls for assertions

    def add_response(self, content="", tool_calls=None):
        """Queue a response. Consumed in order when mock_post is called.

        Args:
            content: The assistant message text.
            tool_calls: Optional list of tool call dicts in Ollama format:
                [{"function": {"name": "tool_name", "arguments": {"arg": "val"}}}]
        """
        self._responses.append({
            "message": {
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls or [],
            },
            "done": True,
        })

    def mock_post(self, url, **kwargs):
        """Drop-in replacement for httpx.post.

        Records the call and returns the next queued response.
        """
        self._calls.append({"url": url, "kwargs": copy.deepcopy(kwargs)})
        self._call_count += 1

        if not self._responses:
            raise RuntimeError("MockLLMResponder: no more responses queued")

        response_data = self._responses.pop(0)

        mock_response = httpx.Response(
            status_code=200,
            json=response_data,
            request=httpx.Request("POST", url),
        )
        return mock_response

    @property
    def last_call(self):
        """Return the most recent call kwargs, or None."""
        return self._calls[-1] if self._calls else None

    def get_sent_messages(self, call_index=-1):
        """Extract the messages list from a recorded call's JSON payload.

        Args:
            call_index: Which call to inspect (default: last call).

        Returns:
            The messages list from the request payload.
        """
        call = self._calls[call_index]
        payload = call["kwargs"].get("json", {})
        return payload.get("messages", [])
