import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PRICE_API_BASE_URL_ENV = "PRICE_API_BASE_URL"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _env_paths():
    paths = [PROJECT_ROOT / ".env", Path.cwd() / ".env"]
    paths.extend(parent / ".env" for parent in Path.cwd().parents)

    seen = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        yield resolved


def _load_env_file():
    for env_path in _env_paths():
        if not env_path.exists():
            continue

        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value


def _price_api_base_url():
    _load_env_file()
    base_url = os.getenv(PRICE_API_BASE_URL_ENV)
    if not base_url:
        checked_paths = ", ".join(str(path) for path in _env_paths())
        raise ValueError(
            f"{PRICE_API_BASE_URL_ENV} is not set. Checked .env paths: {checked_paths}"
        )
    return base_url.rstrip("/")


def _error_result(message, *, status_code=None, response_body=None):
    result = {
        "success": False,
        "error": message,
    }
    if status_code is not None:
        result["status_code"] = status_code
    if response_body:
        try:
            parsed_body = json.loads(response_body)
        except json.JSONDecodeError:
            result["response_body"] = response_body
        else:
            result["response_body"] = parsed_body
            if isinstance(parsed_body, dict) and parsed_body.get("error"):
                result["error"] = str(parsed_body["error"])
    return result


def check_price_now(url):
    """Fetch the current product price from the configured price API."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")

    request = Request(
        f"{_price_api_base_url()}/price",
        data=json.dumps({"Url": url.strip()}).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")
    except HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        return _error_result(
            "Price API request failed",
            status_code=error.code,
            response_body=error_body,
        )
    except URLError as error:
        return _error_result(f"Could not reach price API: {error.reason}")

    try:
        return json.loads(response_body)
    except json.JSONDecodeError as error:
        return _error_result(
            f"Price API returned invalid JSON: {error.msg}",
            response_body=response_body,
        )
