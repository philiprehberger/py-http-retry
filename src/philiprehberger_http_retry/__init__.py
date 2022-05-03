"""Resilient HTTP client with automatic retries and backoff."""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from http.client import HTTPResponse
from typing import Any, Callable, Sequence, Union

__all__ = [
    "RetryExhaustedError",
    "Session",
    "resilient_get",
    "resilient_post",
    "resilient_request",
]

BackoffStrategy = Union[str, Callable[[int], float]]


def _resolve_backoff(backoff: BackoffStrategy, attempt: int) -> float:
    """Compute delay for a given attempt using the backoff strategy.

    Args:
        backoff: ``"exponential"``, ``"linear"``, ``"constant"``, or a
            callable ``(attempt) -> seconds``.
        attempt: Zero-based attempt index.

    Returns:
        Delay in seconds (with jitter for built-in strategies).
    """
    if callable(backoff):
        return backoff(attempt)
    jitter = random.uniform(0, 0.1)
    if backoff == "exponential":
        return 0.5 * (2 ** attempt) + jitter
    if backoff == "linear":
        return 0.5 * (attempt + 1) + jitter
    if backoff == "constant":
        return 0.5 + jitter
    msg = f"Unknown backoff strategy: '{backoff}'. Use 'exponential', 'linear', 'constant', or a callable"
    raise ValueError(msg)


class RetryExhaustedError(Exception):
    """Raised when all retry attempts have been exhausted."""

    def __init__(self, attempts: int, last_error: Exception) -> None:
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"All {attempts} retry attempts exhausted. Last error: {last_error}"
        )


def resilient_request(
    method: str,
    url: str,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    retries: int = 3,
    backoff: BackoffStrategy = "exponential",
    timeout: int = 30,
    retry_on: Sequence[int] = (429, 500, 502, 503, 504),
    on_retry: Callable[[int, Exception], None] | None = None,
) -> HTTPResponse:
    """Send an HTTP request with automatic retries and configurable backoff.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE, etc.).
        url: The URL to request.
        data: Request body as bytes.
        headers: Optional HTTP headers.
        retries: Maximum number of retry attempts.
        backoff: Backoff strategy — ``"exponential"`` (default),
            ``"linear"``, ``"constant"``, or a callable
            ``(attempt_number) -> delay_seconds``.
        timeout: Request timeout in seconds.
        retry_on: HTTP status codes that trigger a retry.
        on_retry: Optional callback invoked before each retry with
            ``(attempt_number, exception)``. Useful for logging.

    Returns:
        HTTPResponse on success.

    Raises:
        RetryExhaustedError: When all retry attempts fail.
    """
    headers = headers or {}
    last_error: Exception | None = None

    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, data=data, headers=headers, method=method.upper()
            )
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in retry_on:
                raise
        except (urllib.error.URLError, OSError) as exc:
            last_error = exc

        if attempt < retries - 1:
            if on_retry is not None:
                on_retry(attempt + 1, last_error)  # type: ignore[arg-type]
            delay = _resolve_backoff(backoff, attempt)
            time.sleep(delay)

    raise RetryExhaustedError(attempts=retries, last_error=last_error)  # type: ignore[arg-type]


def resilient_get(url: str, **kwargs: Any) -> HTTPResponse:
    """Send a GET request with automatic retries.

    Args:
        url: The URL to request.
        **kwargs: Additional arguments passed to resilient_request.

    Returns:
        HTTPResponse on success.
    """
    return resilient_request("GET", url, **kwargs)


def resilient_post(
    url: str,
    data: bytes | None = None,
    json_data: Any = None,
    **kwargs: Any,
) -> HTTPResponse:
    """Send a POST request with automatic retries.

    If json_data is provided, it is serialized to JSON and the Content-Type
    header is set to application/json.

    Args:
        url: The URL to request.
        data: Raw request body as bytes.
        json_data: Data to serialize as JSON for the request body.
        **kwargs: Additional arguments passed to resilient_request.

    Returns:
        HTTPResponse on success.
    """
    if json_data is not None:
        data = json.dumps(json_data).encode("utf-8")
        headers = kwargs.pop("headers", None) or {}
        headers.setdefault("Content-Type", "application/json")
        kwargs["headers"] = headers
    return resilient_request("POST", url, data=data, **kwargs)


class Session:
    """HTTP session with reusable defaults.

    Stores default configuration for retries, backoff, timeout, retryable
    status codes, a base URL, and default headers so that individual
    requests do not need to repeat them.
    """

    def __init__(
        self,
        base_url: str = "",
        default_headers: dict[str, str] | None = None,
        retries: int = 3,
        backoff: BackoffStrategy = "exponential",
        timeout: int = 30,
        retry_on: Sequence[int] = (429, 500, 502, 503, 504),
        on_retry: Callable[[int, Exception], None] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_headers = default_headers or {}
        self.retries = retries
        self.backoff = backoff
        self.timeout = timeout
        self.retry_on = retry_on
        self.on_retry = on_retry

    def _build_url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return f"{self.base_url}/{path.lstrip('/')}" if self.base_url else path

    def _merge_headers(self, headers: dict[str, str] | None) -> dict[str, str]:
        merged = dict(self.default_headers)
        if headers:
            merged.update(headers)
        return merged

    def get(self, path: str, **kwargs: Any) -> HTTPResponse:
        """Send a GET request using session defaults.

        Args:
            path: URL path (appended to base_url) or full URL.
            **kwargs: Overrides for resilient_request parameters.

        Returns:
            HTTPResponse on success.
        """
        kwargs.setdefault("retries", self.retries)
        kwargs.setdefault("backoff", self.backoff)
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("retry_on", self.retry_on)
        kwargs.setdefault("on_retry", self.on_retry)
        kwargs["headers"] = self._merge_headers(kwargs.get("headers"))
        return resilient_get(self._build_url(path), **kwargs)

    def post(self, path: str, **kwargs: Any) -> HTTPResponse:
        """Send a POST request using session defaults.

        Args:
            path: URL path (appended to base_url) or full URL.
            **kwargs: Overrides for resilient_request parameters.

        Returns:
            HTTPResponse on success.
        """
        kwargs.setdefault("retries", self.retries)
        kwargs.setdefault("backoff", self.backoff)
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("retry_on", self.retry_on)
        kwargs.setdefault("on_retry", self.on_retry)
        kwargs["headers"] = self._merge_headers(kwargs.get("headers"))
        return resilient_post(self._build_url(path), **kwargs)
