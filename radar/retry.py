"""Retry utilities with exponential backoff and jitter."""

import random
import time

import httpx


def compute_delay(attempt: int, base_delay: float = 1.0, max_delay: float = 30.0) -> float:
    """Compute retry delay with exponential backoff and full jitter.

    Args:
        attempt: Zero-based attempt number (0 = first retry).
        base_delay: Base delay in seconds.
        max_delay: Maximum delay cap in seconds.

    Returns:
        Randomized delay in seconds.
    """
    ceiling = min(max_delay, base_delay * (2 ** attempt))
    return random.uniform(0, ceiling)


def is_retryable_httpx_error(exc: Exception) -> bool:
    """Check if an httpx exception is worth retrying.

    Retryable: TimeoutException, ConnectError, HTTP 429/500/502/503/504.
    Not retryable: 400/401/403/404 and other client errors.
    """
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return False


def is_retryable_openai_error(exc: Exception) -> bool:
    """Check if an OpenAI SDK exception is worth retrying.

    The OpenAI SDK raises exceptions with a ``status_code`` attribute
    for HTTP errors, or generic connection errors with descriptive text.
    """
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        return status_code in (429, 500, 502, 503, 504)
    error_text = str(exc).lower()
    return any(
        phrase in error_text
        for phrase in ("connection error", "timed out", "timeout", "connect")
    )


def retry_call(
    fn,
    *,
    max_retries: int,
    retry_cfg,
    is_retryable_fn,
    provider: str,
    label: str,
):
    """Call fn() with retry on transient errors.

    Args:
        fn: Callable to invoke (no arguments).
        max_retries: Maximum number of retries (0 = no retries).
        retry_cfg: RetryConfig with base_delay and max_delay.
        is_retryable_fn: Callable(Exception) -> bool.
        provider: Provider name for logging (e.g. "ollama-embedding").
        label: Model or URL label for logging.

    Returns:
        The return value of fn().

    Raises:
        The last exception if all retries are exhausted.
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            last_error = e
            if attempt < max_retries and is_retryable_fn(e):
                delay = compute_delay(
                    attempt,
                    retry_cfg.base_delay,
                    retry_cfg.max_delay,
                )
                log_retry(provider, label, attempt, max_retries, e, delay)
                time.sleep(delay)
                continue
            break
    raise last_error


def log_retry(
    provider: str,
    model: str,
    attempt: int,
    max_retries: int,
    error: Exception,
    delay: float,
) -> None:
    """Log a retry attempt with context."""
    try:
        from radar.logging import log

        log(
            "warn",
            f"Retry {attempt + 1}/{max_retries} for {provider}/{model}: {error}",
            provider=provider,
            model=model,
            attempt=attempt + 1,
            max_retries=max_retries,
            delay_seconds=round(delay, 2),
            error_type=type(error).__name__,
        )
    except Exception:
        pass  # Don't fail on logging errors
