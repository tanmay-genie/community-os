"""
aria.obs.correlation — Request-scoped correlation IDs.

Reads/generates `X-Request-ID` per request, stores in a ContextVar so every
log line in that request carries the same ID. Outbound HTTP calls (httpx)
can read `current_request_id()` and forward the header to t2t_backend so
a single user message produces one traceable chain across services.
"""
from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

HEADER_NAME = "X-Request-ID"

_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def current_request_id() -> str:
    return _request_id.get()


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get(HEADER_NAME) or uuid.uuid4().hex[:16]
        token = _request_id.set(rid)
        try:
            response = await call_next(request)
            response.headers[HEADER_NAME] = rid
            return response
        finally:
            _request_id.reset(token)


class CorrelationFilter(logging.Filter):
    """Injects request_id into every LogRecord."""
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


def install_logging() -> None:
    """Add correlation filter + formatter including request_id to root logger."""
    fmt = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"
    root = logging.getLogger()
    flt = CorrelationFilter()
    for h in root.handlers:
        h.addFilter(flt)
        h.setFormatter(logging.Formatter(fmt))
    if not root.handlers:
        h = logging.StreamHandler()
        h.addFilter(flt)
        h.setFormatter(logging.Formatter(fmt))
        root.addHandler(h)
    root.setLevel(logging.INFO)
