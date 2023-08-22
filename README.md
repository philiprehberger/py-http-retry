# philiprehberger-http-retry

[![Tests](https://github.com/philiprehberger/py-http-retry/actions/workflows/publish.yml/badge.svg)](https://github.com/philiprehberger/py-http-retry/actions/workflows/publish.yml)
[![PyPI version](https://img.shields.io/pypi/v/philiprehberger-http-retry.svg)](https://pypi.org/project/philiprehberger-http-retry/)
[![Last updated](https://img.shields.io/github/last-commit/philiprehberger/py-http-retry)](https://github.com/philiprehberger/py-http-retry/commits/main)

Resilient HTTP client with automatic retries and configurable backoff.

## Installation

```bash
pip install philiprehberger-http-retry
```

## Usage

```python
from philiprehberger_http_retry import resilient_get, resilient_post, Session
```

### Simple Requests

```python
# GET request with default retries (3 attempts, exponential backoff)
response = resilient_get("https://api.example.com/data")
print(response.read().decode())

# POST with JSON body
response = resilient_post(
    "https://api.example.com/items",
    json_data={"name": "widget", "count": 5},
)
```

### Backoff Strategies

```python
from philiprehberger_http_retry import resilient_request

# Exponential backoff (default): 0.5s, 1s, 2s, ...
resilient_request("GET", url, backoff="exponential")

# Linear backoff: 0.5s, 1s, 1.5s, ...
resilient_request("GET", url, backoff="linear")

# Constant backoff: 0.5s, 0.5s, 0.5s, ...
resilient_request("GET", url, backoff="constant")

# Custom callable: receives attempt number, returns delay in seconds
resilient_request("GET", url, backoff=lambda attempt: 0.1 * (attempt + 1))
```

### Retry Hook

```python
import logging

def log_retry(attempt: int, error: Exception) -> None:
    logging.warning(f"Retry {attempt}: {error}")

response = resilient_get(
    "https://api.example.com/data",
    on_retry=log_retry,
)
```

### Session with Defaults

```python
session = Session(
    base_url="https://api.example.com",
    default_headers={"Authorization": "Bearer token123"},
    retries=5,
    backoff="linear",
    timeout=15,
    on_retry=log_retry,
)

response = session.get("/users")
response = session.post("/users", json_data={"name": "Alice"})
```

### Error Handling

```python
from philiprehberger_http_retry import resilient_get, RetryExhaustedError

try:
    response = resilient_get("https://unreliable-api.example.com/data")
except RetryExhaustedError as err:
    print(f"Failed after {err.attempts} attempts: {err.last_error}")
```

## API

| Function / Class | Description |
|---|---|
| `resilient_request(method, url, **kwargs)` | Core retry function. Supports `data`, `headers`, `retries`, `backoff`, `timeout`, `retry_on`, `on_retry`. |
| `resilient_get(url, **kwargs)` | GET convenience wrapper around `resilient_request`. |
| `resilient_post(url, data=None, json_data=None, **kwargs)` | POST wrapper. Auto-serializes `json_data` and sets Content-Type. |
| `Session(base_url, default_headers, retries, backoff, timeout, retry_on, on_retry)` | Stores defaults. Methods: `get(path)`, `post(path)`. |
| `RetryExhaustedError` | Raised after all retries fail. Attributes: `.attempts`, `.last_error`. |

## Development

```bash
pip install -e .
python -m pytest tests/ -v
```

## Support

If you find this project useful:

⭐ [Star the repo](https://github.com/philiprehberger/py-http-retry)

🐛 [Report issues](https://github.com/philiprehberger/py-http-retry/issues?q=is%3Aissue+is%3Aopen+label%3Abug)

💡 [Suggest features](https://github.com/philiprehberger/py-http-retry/issues?q=is%3Aissue+is%3Aopen+label%3Aenhancement)

❤️ [Sponsor development](https://github.com/sponsors/philiprehberger)

🌐 [All Open Source Projects](https://philiprehberger.com/open-source-packages)

💻 [GitHub Profile](https://github.com/philiprehberger)

🔗 [LinkedIn Profile](https://www.linkedin.com/in/philiprehberger)

## License

[MIT](LICENSE)
