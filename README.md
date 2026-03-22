# philiprehberger-http-retry

Resilient HTTP client with automatic retries and backoff.

## Install

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

### Session with Defaults

```python
session = Session(
    base_url="https://api.example.com",
    default_headers={"Authorization": "Bearer token123"},
    retries=5,
    timeout=15,
)

response = session.get("/users")
response = session.post("/users", json_data={"name": "Alice"})
```

### Custom Retry Configuration

```python
from philiprehberger_http_retry import resilient_request

response = resilient_request(
    "PUT",
    "https://api.example.com/resource/1",
    data=b'{"status": "active"}',
    headers={"Content-Type": "application/json"},
    retries=5,
    backoff=True,
    timeout=60,
    retry_on=(429, 500, 502, 503, 504),
)
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
| `resilient_request(method, url, **kwargs)` | Core retry function. Supports `data`, `headers`, `retries`, `backoff`, `timeout`, `retry_on`. |
| `resilient_get(url, **kwargs)` | GET convenience wrapper around `resilient_request`. |
| `resilient_post(url, data=None, json_data=None, **kwargs)` | POST wrapper. Auto-serializes `json_data` and sets Content-Type. |
| `Session(base_url, default_headers, retries, backoff, timeout, retry_on)` | Stores defaults. Methods: `get(path)`, `post(path)`. |
| `RetryExhaustedError` | Raised after all retries fail. Attributes: `.attempts`, `.last_error`. |

## License

MIT
