import asyncio
import functools
import inspect
import json
import logging
import os
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from starlette.responses import Response


LOGGER_NAME = "price_chatbot"
LOG_LEVEL_ENV = "JSON_LOG_LEVEL"


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return str(value)


def to_jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=_json_default, ensure_ascii=False))


def parse_body(body: bytes) -> Any:
    if not body:
        return None

    text = body.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def get_json_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.propagate = False

    level_name = os.getenv(LOG_LEVEL_ENV, "INFO").upper()
    logger.setLevel(getattr(logging, level_name, logging.INFO))
    return logger


def log_json(event: str, **fields: Any) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "event": event,
        **fields,
    }
    get_json_logger().info(json.dumps(to_jsonable(payload), ensure_ascii=False))


def _error_payload(error: Exception) -> dict[str, Any]:
    return {
        "type": error.__class__.__name__,
        "message": str(error),
        "traceback": traceback.format_exc(),
    }


def log_mcp_tool(tool_name: str) -> Callable:
    def decorator(func: Callable) -> Callable:
        signature = inspect.signature(func)

        def bound_arguments(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            return dict(bound.arguments)

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                call_id = str(uuid.uuid4())
                started_at = time.perf_counter()
                body = bound_arguments(args, kwargs)

                try:
                    result = await func(*args, **kwargs)
                except Exception as error:
                    log_json(
                        "mcp.tool.failed",
                        call_id=call_id,
                        source="mcp",
                        tool=tool_name,
                        body=body,
                        success=False,
                        duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                        error=_error_payload(error),
                    )
                    raise

                log_json(
                    "mcp.tool.completed",
                    call_id=call_id,
                    source="mcp",
                    tool=tool_name,
                    body=body,
                    success=True,
                    duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                    result=result,
                )
                return result

            async_wrapper.__signature__ = signature
            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            call_id = str(uuid.uuid4())
            started_at = time.perf_counter()
            body = bound_arguments(args, kwargs)

            try:
                result = func(*args, **kwargs)
            except Exception as error:
                log_json(
                    "mcp.tool.failed",
                    call_id=call_id,
                    source="mcp",
                    tool=tool_name,
                    body=body,
                    success=False,
                    duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                    error=_error_payload(error),
                )
                raise

            log_json(
                "mcp.tool.completed",
                call_id=call_id,
                source="mcp",
                tool=tool_name,
                body=body,
                success=True,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                result=result,
            )
            return result

        wrapper.__signature__ = signature
        return wrapper

    return decorator


async def log_api_request(request: Any, call_next: Callable) -> Response:
    call_id = str(uuid.uuid4())
    started_at = time.perf_counter()
    request_body = await request.body()

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": request_body, "more_body": False}

    request._receive = receive

    request_payload = {
        "method": request.method,
        "endpoint": request.url.path,
        "query": dict(request.query_params),
        "body": parse_body(request_body),
        "client": request.client.host if request.client else None,
    }

    try:
        response = await call_next(request)
        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk

        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        log_json(
            "api.request.completed",
            call_id=call_id,
            source="api",
            **request_payload,
            status_code=response.status_code,
            success=response.status_code < 400,
            duration_ms=duration_ms,
            result=parse_body(response_body),
        )

        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
            background=response.background,
        )
    except Exception as error:
        log_json(
            "api.request.failed",
            call_id=call_id,
            source="api",
            **request_payload,
            success=False,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
            error=_error_payload(error),
        )
        raise
