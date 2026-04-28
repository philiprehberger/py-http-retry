"""Tests for philiprehberger_http_retry."""

from __future__ import annotations

import time
import urllib.error
from unittest.mock import patch

import pytest

from philiprehberger_http_retry import (
    CircuitBreaker,
    CircuitBreakerOpen,
    RetryExhaustedError,
    Session,
    resilient_request,
)


class TestRetryExhaustedError:
    def test_stores_attempts(self) -> None:
        err = RetryExhaustedError(attempts=5, last_error=ValueError("boom"))
        assert err.attempts == 5

    def test_stores_last_error(self) -> None:
        cause = ConnectionError("refused")
        err = RetryExhaustedError(attempts=3, last_error=cause)
        assert err.last_error is cause

    def test_is_exception(self) -> None:
        err = RetryExhaustedError(attempts=1, last_error=RuntimeError("x"))
        assert isinstance(err, Exception)

    def test_message_contains_attempts(self) -> None:
        err = RetryExhaustedError(attempts=4, last_error=ValueError("fail"))
        assert "4" in str(err)


class TestSession:
    def test_stores_defaults(self) -> None:
        session = Session(
            base_url="https://api.example.com",
            default_headers={"Authorization": "Bearer tok"},
            retries=5,
            backoff="constant",
            timeout=10,
            retry_on=(500, 502),
        )
        assert session.base_url == "https://api.example.com"
        assert session.default_headers == {"Authorization": "Bearer tok"}
        assert session.retries == 5
        assert session.backoff == "constant"
        assert session.timeout == 10
        assert session.retry_on == (500, 502)

    def test_default_values(self) -> None:
        session = Session()
        assert session.base_url == ""
        assert session.default_headers == {}
        assert session.retries == 3
        assert session.backoff == "exponential"
        assert session.timeout == 30

    def test_strips_trailing_slash_from_base_url(self) -> None:
        session = Session(base_url="https://api.example.com/")
        assert session.base_url == "https://api.example.com"


class TestResilientRequest:
    @patch("philiprehberger_http_retry.urllib.request.urlopen")
    def test_raises_after_retries_exhausted(self, mock_urlopen: object) -> None:
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")  # type: ignore[attr-defined]

        with pytest.raises(RetryExhaustedError) as exc_info:
            resilient_request("GET", "http://example.com", retries=3, backoff=lambda _: 0)

        assert exc_info.value.attempts == 3
        assert isinstance(exc_info.value.last_error, urllib.error.URLError)

    @patch("philiprehberger_http_retry.urllib.request.urlopen")
    def test_returns_response_on_success(self, mock_urlopen: object) -> None:
        mock_urlopen.return_value = "fake_response"  # type: ignore[attr-defined]

        result = resilient_request("GET", "http://example.com", retries=3, backoff=lambda _: 0)
        assert result == "fake_response"

    @patch("philiprehberger_http_retry.urllib.request.urlopen")
    def test_retries_on_retryable_status(self, mock_urlopen: object) -> None:
        error_500 = urllib.error.HTTPError(
            "http://example.com", 500, "Server Error", {}, None  # type: ignore[arg-type]
        )
        mock_urlopen.side_effect = [error_500, error_500, "success"]  # type: ignore[attr-defined]

        result = resilient_request("GET", "http://example.com", retries=3, backoff=lambda _: 0)
        assert result == "success"
        assert mock_urlopen.call_count == 3  # type: ignore[attr-defined]

    @patch("philiprehberger_http_retry.urllib.request.urlopen")
    def test_raises_immediately_on_non_retryable_status(self, mock_urlopen: object) -> None:
        error_404 = urllib.error.HTTPError(
            "http://example.com", 404, "Not Found", {}, None  # type: ignore[arg-type]
        )
        mock_urlopen.side_effect = error_404  # type: ignore[attr-defined]

        with pytest.raises(urllib.error.HTTPError):
            resilient_request("GET", "http://example.com", retries=3, backoff=lambda _: 0)


class TestCircuitBreaker:
    def test_starts_closed(self) -> None:
        cb = CircuitBreaker()
        assert cb.state == "closed"
        assert cb.allow_request() is True

    def test_opens_after_failure_threshold(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=10.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"
        cb.record_failure()
        assert cb.state == "open"

    def test_rejects_requests_while_open(self) -> None:
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=10.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        assert cb.allow_request() is False

    def test_resilient_request_raises_circuit_breaker_open(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=10.0)
        cb.record_failure()
        assert cb.state == "open"
        with pytest.raises(CircuitBreakerOpen) as exc_info:
            resilient_request(
                "GET",
                "http://example.com",
                retries=3,
                backoff=lambda _: 0,
                circuit_breaker=cb,
            )
        assert exc_info.value.next_retry_at > time.time()

    def test_transitions_to_half_open_after_reset_timeout(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.05)
        cb.record_failure()
        assert cb.state == "open"
        time.sleep(0.06)
        assert cb.allow_request() is True
        assert cb.state == "half_open"

    def test_half_open_returns_to_closed_on_success(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.05)
        cb.record_failure()
        time.sleep(0.06)
        cb.allow_request()
        assert cb.state == "half_open"
        cb.record_success()
        assert cb.state == "closed"

    def test_half_open_returns_to_open_on_failure(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.05)
        cb.record_failure()
        time.sleep(0.06)
        cb.allow_request()
        assert cb.state == "half_open"
        cb.record_failure()
        assert cb.state == "open"

    def test_half_open_max_calls_limits_probes(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.05, half_open_max_calls=1)
        cb.record_failure()
        time.sleep(0.06)
        assert cb.allow_request() is True
        assert cb.allow_request() is False

    @patch("philiprehberger_http_retry.urllib.request.urlopen")
    def test_resilient_request_records_success(self, mock_urlopen: object) -> None:
        mock_urlopen.return_value = "ok"  # type: ignore[attr-defined]
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        result = resilient_request(
            "GET",
            "http://example.com",
            retries=3,
            backoff=lambda _: 0,
            circuit_breaker=cb,
        )
        assert result == "ok"
        # success in closed resets the failure counter
        cb.record_failure()
        assert cb.state == "closed"

    @patch("philiprehberger_http_retry.urllib.request.urlopen")
    def test_resilient_request_records_failure_only_after_retries_exhausted(
        self, mock_urlopen: object
    ) -> None:
        mock_urlopen.side_effect = urllib.error.URLError("boom")  # type: ignore[attr-defined]
        cb = CircuitBreaker(failure_threshold=2)
        # First call: 3 retries, then ONE failure recorded
        with pytest.raises(RetryExhaustedError):
            resilient_request(
                "GET",
                "http://example.com",
                retries=3,
                backoff=lambda _: 0,
                circuit_breaker=cb,
            )
        assert cb.state == "closed"
        # Second call: now breaker should trip after one more recorded failure
        with pytest.raises(RetryExhaustedError):
            resilient_request(
                "GET",
                "http://example.com",
                retries=3,
                backoff=lambda _: 0,
                circuit_breaker=cb,
            )
        assert cb.state == "open"

    @patch("philiprehberger_http_retry.urllib.request.urlopen")
    def test_session_integrates_circuit_breaker(self, mock_urlopen: object) -> None:
        mock_urlopen.return_value = "ok"  # type: ignore[attr-defined]
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=10.0)
        session = Session(base_url="http://example.com", circuit_breaker=cb)
        # Open the breaker manually
        cb.record_failure()
        assert cb.state == "open"
        with pytest.raises(CircuitBreakerOpen):
            session.get("/path", backoff=lambda _: 0)
