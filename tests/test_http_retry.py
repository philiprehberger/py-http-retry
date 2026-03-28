"""Tests for philiprehberger_http_retry."""

from __future__ import annotations

import urllib.error
from unittest.mock import patch

import pytest

from philiprehberger_http_retry import (
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
