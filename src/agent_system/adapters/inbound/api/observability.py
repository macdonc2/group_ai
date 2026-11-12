"""Request correlation, structured logs and the access log.

Three pieces that only pay off together:

* every request gets an ID (taken from `X-Request-ID` when the caller sent a
  sane one, otherwise generated) which is returned in the response header;
* every log line written while that request is being handled carries the ID
  and, once known, the user's ID, without any call site passing them along;
* one access-log line per request records what happened: method, route,
  status, duration.

With JSON output, "show me everything that happened in request X" and "show
me every 401 in the last hour" become one-line queries instead of archaeology.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

REQUEST_ID_HEADER = "x-request-id"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

# One mutable dict per request. A dict (rather than one ContextVar per field)
# so that a value set deep inside the request, such as the user's ID once
# their token is checked, is visible to the middleware that logs at the end,
# even where the framework ran that code in a copied context.
_request: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("request_context", default=None)

access_logger = logging.getLogger("agent_system.access")
_QUIET_PATHS = ("/health",)  # probes hit these every few seconds


def current_request_id() -> str | None:
    ctx = _request.get()
    return ctx["request_id"] if ctx else None


def set_request_user(user_id: str) -> None:
    """Attach the authenticated user to the current request's log lines."""
    ctx = _request.get()
    if ctx is not None:
        ctx["user_id"] = user_id
    _annotate_span(**{"enduser.id": user_id})


def _annotate_span(**attributes: Any) -> None:
    from agent_system.adapters.outbound.telemetry.otel import annotate_current_span

    annotate_current_span(**attributes)


def _trace_ids() -> tuple[str, str] | None:
    from agent_system.adapters.outbound.telemetry.otel import current_trace_ids

    return current_trace_ids()


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName", "rid"}


class RequestContextFilter(logging.Filter):
    """Stamp each record with the request it was written under."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _request.get() or {}
        record.request_id = ctx.get("request_id")
        if not hasattr(record, "user_id"):
            record.user_id = ctx.get("user_id")
        ids = _trace_ids()  # None unless tracing is on and a span is active
        if ids:
            record.trace_id, record.span_id = ids
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Anything passed as `extra=` becomes a field."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and value is not None:
                entry[key] = value
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class TextFormatter(logging.Formatter):
    """Readable local output that still shows the request ID."""

    def format(self, record: logging.LogRecord) -> str:
        rid = getattr(record, "request_id", None)
        record.rid = f" [{rid[:8]}]" if rid else ""
        return super().format(record)


def configure_logging(as_json: bool) -> None:
    """Send all logs to stdout in one format. Safe to call more than once."""
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(
        JsonFormatter() if as_json
        else TextFormatter("%(asctime)s %(levelname)s %(name)s%(rid)s - %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    logging.getLogger("agent_system").setLevel(logging.INFO)
    # Our middleware writes the access log (with route, user and request ID),
    # so uvicorn's own would only duplicate it, query strings included.
    logging.getLogger("uvicorn.access").disabled = True
    # httpx logs every outbound URL at INFO, query string and all (search
    # terms, and for some APIs credentials). Failures still surface.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


def _header(scope: dict[str, Any], name: str) -> str | None:
    wanted = name.encode()
    for key, value in scope.get("headers") or ():
        if key == wanted:
            return value.decode("latin-1")
    return None


def _route_path(scope: dict[str, Any]) -> str:
    """The route template (`/conversations/{conversation_id}`), not the raw
    path: it groups requests by endpoint and keeps IDs out of the path field.
    The query string is never logged, since some endpoints carry a token there."""
    route = scope.get("route")
    return getattr(route, "path", None) or scope.get("path", "")


class RequestContextMiddleware:
    """Pure ASGI middleware, so streaming responses and WebSockets pass through untouched."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        offered = _header(scope, REQUEST_ID_HEADER)
        request_id = offered if offered and _SAFE_REQUEST_ID.match(offered) else uuid.uuid4().hex
        ctx: dict[str, Any] = {"request_id": request_id, "user_id": None}
        scope["request_id"] = request_id  # for the error handler, which runs outside this middleware
        _annotate_span(**{"app.request_id": request_id})
        token = _request.set(ctx)
        started = time.perf_counter()
        status_code = 500  # what the client gets if the app raises before responding

        async def send_with_id(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (REQUEST_ID_HEADER.encode(), request_id.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            # Logged here, while the request's context is still in place, so
            # the traceback carries the same ID the client is given.
            access_logger.exception(
                "Unhandled error in %s %s", scope.get("method"), _route_path(scope), extra={"event": "unhandled_error"},
            )
            raise
        finally:
            if scope["type"] == "http":
                self._log(scope, status_code, (time.perf_counter() - started) * 1000)
            _request.reset(token)

    @staticmethod
    def _log(scope: dict[str, Any], status_code: int, duration_ms: float) -> None:
        raw_path = scope.get("path", "")
        if status_code < 400 and raw_path.startswith(_QUIET_PATHS):
            return
        if status_code >= 500:
            level = logging.ERROR
        elif status_code in (401, 403, 429):
            level = logging.WARNING  # the security-relevant refusals
        else:
            level = logging.INFO
        path = _route_path(scope)
        access_logger.log(
            level, "%s %s -> %s", scope.get("method"), path, status_code,
            extra={
                "event": "http_request",
                "method": scope.get("method"),
                "path": path,
                "status": status_code,
                "duration_ms": round(duration_ms, 1),
                "client": _header(scope, "x-real-ip") or (scope.get("client") or ("unknown",))[0],
            },
        )
