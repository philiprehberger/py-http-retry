"""Resilient HTTP client with automatic retries and backoff."""

from __future__ import annotations

import json
import random
import threading
import time
import urllib.error
import urllib.request
from http.client import HTTPResponse
from typing import Any, Callable, Sequence, Union

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerOpen",
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


class CircuitBreakerOpen(Exception):
    """Raised when a request is rejected because the circuit breaker is open."""

    def __init__(self, next_retry_at: float) -> None:
        self.next_retry_at = next_retry_at
        super().__init__(
            f"Circuit breaker is open. Next retry allowed at unix time {next_retry_at:.3f}."
        )


class CircuitBreaker:
    """Circuit breaker for failing-fast on repeated request failures.

    A breaker tracks consecutive failures and trips to ``"open"`` once the
    ``failure_threshold`` is reached, rejecting subsequent requests until
    ``reset_timeout`` seconds have elapsed. After the timeout it enters
    ``"half_open"`` and allows up to ``half_open_max_calls`` probe requests.
    A successful probe returns the breaker to ``"closed"``; a failure
    returns it to ``"open"``.

    Args:
        failure_threshold: Failures in ``closed`` before tripping to ``open``.
        reset_timeout: Seconds to wait in ``open`` before allowing a probe.
        half_open_max_calls: Maximum concurrent probe requests in ``half_open``.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
        half_open_max_calls: int = 1,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.half_open_max_calls = half_open_max_calls
        self._state: str = "closed"
        self._failure_count: int = 0
        self._opened_at: float = 0.0
        self._half_open_inflight: int = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        """Current breaker state: ``"closed"``, ``"open"``, or ``"half_open"``."""
        with self._lock:
            return self._state

    def allow_request(self) -> bool:
        """Return whether a request should be permitted.

        Side effect: when in ``open`` and ``reset_timeout`` has elapsed,
        transitions to ``half_open`` and resets the in-flight probe counter.
        In ``half_open``, increments the in-flight probe counter when
        returning ``True``.
        """
        with self._lock:
            if self._state == "closed":
                return True
            if self._state == "open":
                if time.monotonic() - self._opened_at >= self.reset_timeout:
                    self._state = "half_open"
                    self._half_open_inflight = 0
                else:
                    return False
            # half_open
            if self._half_open_inflight < self.half_open_max_calls:
                self._half_open_inflight += 1
                return True
            return False

    def record_success(self) -> None:
        """Record a successful request.

        In ``closed``, resets the failure counter. In ``half_open``,
        returns the breaker to ``closed``.
        """
        with self._lock:
            if self._state == "closed":
                self._failure_count = 0
            elif self._state == "half_open":
                self._state = "closed"
                self._failure_count = 0
                self._half_open_inflight = 0

    def record_failure(self) -> None:
        """Record a failed request.

        In ``closed``, increments the failure counter and trips to ``open``
        once ``failure_threshold`` is reached. In ``half_open``, returns
        the breaker to ``open``.
        """
        with self._lock:
            if self._state == "closed":
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    self._state = "open"
                    self._opened_at = time.monotonic()
            elif self._state == "half_open":
                self._state = "open"
                self._opened_at = time.monotonic()
                self._half_open_inflight = 0


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
    circuit_breaker: CircuitBreaker | None = None,
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
        circuit_breaker: Optional :class:`CircuitBreaker`. When provided,
            requests are rejected with :class:`CircuitBreakerOpen` while
            the breaker is open. The breaker records a success on a
            non-retryable response and a failure once retries are
            exhausted (it counts request outcomes, not retry attempts).

    Returns:
        HTTPResponse on success.

    Raises:
        RetryExhaustedError: When all retry attempts fail.
        CircuitBreakerOpen: When the circuit breaker rejects the request.
    """
    headers = headers or {}
    last_error: Exception | None = None

    for attempt in range(retries):
        if circuit_breaker is not None and not circuit_breaker.allow_request():
            elapsed = time.monotonic() - circuit_breaker._opened_at
            remaining = max(0.0, circuit_breaker.reset_timeout - elapsed)
            raise CircuitBreakerOpen(next_retry_at=time.time() + remaining)

        try:
            req = urllib.request.Request(
                url, data=data, headers=headers, method=method.upper()
            )
            response = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in retry_on:
                if circuit_breaker is not None:
                    circuit_breaker.record_success()
                raise
        except (urllib.error.URLError, OSError) as exc:
            last_error = exc
        else:
            if circuit_breaker is not None:
                circuit_breaker.record_success()
            return response

        if attempt < retries - 1:
            if on_retry is not None:
                on_retry(attempt + 1, last_error)  # type: ignore[arg-type]
            delay = _resolve_backoff(backoff, attempt)
            time.sleep(delay)

    if circuit_breaker is not None:
        circuit_breaker.record_failure()
    raise RetryExhaustedError(attempts=retries, last_error=last_error)  # type: ignore[arg-type]


def resilient_get(url: str, **kwargs: Any) -> HTTPResponse:
    """Send a GET request with automatic retries.

    Args:
        url: The URL to request.
        **kwargs: Additional arguments passed to resilient_request,
            including the optional ``circuit_breaker``.

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
        **kwargs: Additional arguments passed to resilient_request,
            including the optional ``circuit_breaker``.

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
    status codes, a base URL, default headers, and an optional circuit
    breaker so that individual requests do not need to repeat them.
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
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_headers = default_headers or {}
        self.retries = retries
        self.backoff = backoff
        self.timeout = timeout
        self.retry_on = retry_on
        self.on_retry = on_retry
        self._circuit_breaker = circuit_breaker

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
        kwargs.setdefault("circuit_breaker", self._circuit_breaker)
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
        kwargs.setdefault("circuit_breaker", self._circuit_breaker)
        kwargs["headers"] = self._merge_headers(kwargs.get("headers"))
        return resilient_post(self._build_url(path), **kwargs)
