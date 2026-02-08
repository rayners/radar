"""Tests for radar/retry.py — exponential backoff, retryable error detection."""

from unittest.mock import MagicMock

import httpx
import pytest

from radar.retry import compute_delay, is_retryable_httpx_error, is_retryable_openai_error


# ── compute_delay ─────────────────────────────────────────────────


class TestComputeDelay:
    """compute_delay returns bounded randomized delays."""

    def test_delay_is_non_negative(self):
        for attempt in range(10):
            assert compute_delay(attempt) >= 0

    def test_delay_bounded_by_max(self):
        for attempt in range(10):
            delay = compute_delay(attempt, base_delay=1.0, max_delay=5.0)
            assert delay <= 5.0

    def test_exponential_growth_ceiling(self):
        # At attempt 0, ceiling = min(30, 1*2^0) = 1.0
        # At attempt 3, ceiling = min(30, 1*2^3) = 8.0
        # At attempt 10, ceiling = min(30, 1*2^10) = 30.0 (capped)
        for _ in range(50):
            d0 = compute_delay(0, base_delay=1.0, max_delay=30.0)
            assert d0 <= 1.0
        for _ in range(50):
            d3 = compute_delay(3, base_delay=1.0, max_delay=30.0)
            assert d3 <= 8.0
        for _ in range(50):
            d10 = compute_delay(10, base_delay=1.0, max_delay=30.0)
            assert d10 <= 30.0

    def test_zero_base_delay(self):
        delay = compute_delay(5, base_delay=0.0, max_delay=10.0)
        assert delay == 0.0

    def test_max_delay_zero(self):
        delay = compute_delay(5, base_delay=1.0, max_delay=0.0)
        assert delay == 0.0


# ── is_retryable_httpx_error ──────────────────────────────────────


class TestIsRetryableHttpxError:
    """is_retryable_httpx_error classifies httpx exceptions."""

    def test_timeout_is_retryable(self):
        assert is_retryable_httpx_error(httpx.TimeoutException("timeout")) is True

    def test_connect_error_is_retryable(self):
        assert is_retryable_httpx_error(httpx.ConnectError("refused")) is True

    def test_429_is_retryable(self):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 429
        exc = httpx.HTTPStatusError("429", request=MagicMock(), response=resp)
        assert is_retryable_httpx_error(exc) is True

    def test_502_is_retryable(self):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 502
        exc = httpx.HTTPStatusError("502", request=MagicMock(), response=resp)
        assert is_retryable_httpx_error(exc) is True

    def test_503_is_retryable(self):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 503
        exc = httpx.HTTPStatusError("503", request=MagicMock(), response=resp)
        assert is_retryable_httpx_error(exc) is True

    def test_504_is_retryable(self):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 504
        exc = httpx.HTTPStatusError("504", request=MagicMock(), response=resp)
        assert is_retryable_httpx_error(exc) is True

    def test_400_not_retryable(self):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 400
        exc = httpx.HTTPStatusError("400", request=MagicMock(), response=resp)
        assert is_retryable_httpx_error(exc) is False

    def test_401_not_retryable(self):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 401
        exc = httpx.HTTPStatusError("401", request=MagicMock(), response=resp)
        assert is_retryable_httpx_error(exc) is False

    def test_404_not_retryable(self):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 404
        exc = httpx.HTTPStatusError("404", request=MagicMock(), response=resp)
        assert is_retryable_httpx_error(exc) is False

    def test_value_error_not_retryable(self):
        assert is_retryable_httpx_error(ValueError("bad")) is False


# ── is_retryable_openai_error ─────────────────────────────────────


class TestIsRetryableOpenaiError:
    """is_retryable_openai_error classifies OpenAI SDK exceptions."""

    def test_status_code_429(self):
        exc = Exception("rate limit")
        exc.status_code = 429
        assert is_retryable_openai_error(exc) is True

    def test_status_code_503(self):
        exc = Exception("unavailable")
        exc.status_code = 503
        assert is_retryable_openai_error(exc) is True

    def test_status_code_400(self):
        exc = Exception("bad request")
        exc.status_code = 400
        assert is_retryable_openai_error(exc) is False

    def test_connection_error_text(self):
        exc = Exception("Connection error: refused")
        assert is_retryable_openai_error(exc) is True

    def test_timeout_text(self):
        exc = Exception("Request timed out")
        assert is_retryable_openai_error(exc) is True

    def test_generic_error_not_retryable(self):
        exc = Exception("Invalid API key")
        assert is_retryable_openai_error(exc) is False
