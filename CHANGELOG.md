# Changelog

## 0.2.1 (2026-03-31)

- Standardize README to 3-badge format with emoji Support section
- Update CI checkout action to v5 for Node.js 24 compatibility

## 0.2.0 (2026-03-27)

- Add configurable backoff strategies: `"exponential"`, `"linear"`, `"constant"`, or custom callable
- Add `on_retry` callback parameter for logging and observability
- Session class now accepts `backoff` strategy and `on_retry` hook
- Add issue templates, PR template, and Dependabot config
- Update README with full badge set and Support section

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
