# Changelog

## 0.1.1 (2026-03-22)

- Add badges to README
- Rename Install section to Installation in README
- Add Development section to README
- Add Changelog URL to project URLs
- Add `#readme` anchor to Homepage URL
- Add pytest and mypy configuration

## 0.1.0 (2026-03-21)

- Initial release
- Resilient HTTP requests with automatic retries and exponential backoff
- Convenience functions: `resilient_get`, `resilient_post`
- `Session` class for reusable defaults (base URL, headers, retry config)
- `RetryExhaustedError` with `.attempts` and `.last_error` attributes
- Zero dependencies (stdlib only)
