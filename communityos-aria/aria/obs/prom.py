"""
aria.obs.prom — Prometheus metrics for ARIA.

Exports:
  http_requests_total{method, path, status}  - Counter
  http_request_latency_seconds{method, path} - Histogram
  llm_calls_total{model, cached, error}      - Counter
  llm_cost_usd_total{model}                   - Counter (monotonic spend)
  llm_latency_seconds{model}                  - Histogram
  rag_chunks_gauge                            - Gauge

Register middleware to automatically time every HTTP request. LLM counters
are bumped by aria.ai.metrics.record() via update_llm_metric().
"""
from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REGISTRY = CollectorRegistry()

http_requests_total = Counter(
    "aria_http_requests_total", "HTTP requests total",
    ["method", "path", "status"], registry=REGISTRY,
)
http_request_latency = Histogram(
    "aria_http_request_latency_seconds", "HTTP request latency",
    ["method", "path"], registry=REGISTRY,
)
llm_calls_total = Counter(
    "aria_llm_calls_total", "LLM calls total",
    ["model", "cached", "error"], registry=REGISTRY,
)
llm_cost_usd_total = Counter(
    "aria_llm_cost_usd_total", "Cumulative LLM cost USD", ["model"], registry=REGISTRY,
)
llm_latency_seconds = Histogram(
    "aria_llm_latency_seconds", "LLM call latency", ["model"], registry=REGISTRY,
)
rag_chunks_gauge = Gauge("aria_rag_chunks", "RAG chunks loaded", registry=REGISTRY)


def update_llm_metric(model: str, cached: bool, error: str | None,
                      latency_ms: float, cost_usd: float) -> None:
    """Called from aria.ai.metrics.record()."""
    llm_calls_total.labels(
        model=model,
        cached=str(bool(cached)).lower(),
        error="1" if error else "0",
    ).inc()
    llm_cost_usd_total.labels(model=model).inc(cost_usd)
    llm_latency_seconds.labels(model=model).observe(latency_ms / 1000.0)


class PromMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        import time
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
