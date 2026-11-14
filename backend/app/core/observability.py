from __future__ import annotations

import contextvars
import json
import logging
import re
import time
import uuid
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_VALID_ID = re.compile(r"^[A-Za-z0-9_.-]{8,64}$")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {"ts": self.formatTime(record), "level": record.levelname,
                "logger": record.name, "message": record.getMessage(),
                "request_id": getattr(record, "request_id", request_id_var.get())}
        for key in ("method", "path", "status", "duration_ms"):
            if hasattr(record, key):
                data[key] = getattr(record, key)
        return json.dumps(data, ensure_ascii=False)


def configure_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_cap1_json_logging", False):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    root._cap1_json_logging = True


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        identifier = incoming if _VALID_ID.fullmatch(incoming) else uuid.uuid4().hex
        token = request_id_var.set(identifier)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = identifier
            return response
        except Exception:
            # Keep unexpected exception details out of the response and preserve
            # operational headers even when the downstream stack raises.
            response = JSONResponse({"detail": "Internal Server Error"}, status_code=500)
            response.headers["X-Request-ID"] = identifier
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            import os
            if os.getenv("APP_HTTPS") == "1":
                response.headers["Strict-Transport-Security"] = "max-age=31536000"
            return response
        finally:
            logging.getLogger("cap1.access").info(
                "request completed", extra={"method": request.method,
                    "path": request.url.path, "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "request_id": identifier})
            request_id_var.reset(token)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        import os
        if os.getenv("APP_HTTPS") == "1":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response


class TTLCache:
    def __init__(self, ttl: float, clock: Callable[[], float] = time.monotonic):
        self.ttl, self.clock = ttl, clock
        self._value = None
        self._expires = 0.0

    def get(self):
        if self._value is not None and self.clock() < self._expires:
            return self._value
        return None

    def set(self, value):
        self._value, self._expires = value, self.clock() + self.ttl
        return value
