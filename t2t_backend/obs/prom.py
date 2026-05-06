"""
t2t_backend.obs.prom — Prometheus metrics for the T2T backend.

Exports:
  t2t_http_requests_total{method, path, status}   - Counter
  t2t_http_request_latency_seconds{method, path}  - Histogram
"""
from __future__ import annotations

import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REGISTRY = CollectorRegistry()

http_requests_total = Counter(
    "t2t_http_requests_total", "HTTP requests total",
    ["method", "path", "status"], registry=REGISTRY,
)
http_request_latency = Histogram(
    "t2t_http_request_latency_seconds", "HTTP request latency",
    ["method", "path"], registry=REGISTRY,
)


class PromMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        latency = time.monotonic() - start
        path = request.url.path
        http_requests_total.labels(
            method=request.method, path=path, status=str(response.status_code),
        ).inc()
        http_request_latency.labels(method=request.method, path=path).observe(latency)
        return response


def render_metrics() -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
