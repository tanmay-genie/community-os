"""
app.py — GENIE AI · T2T Backend · FastAPI Application Entry Point

Registers all routers and handles startup/shutdown lifecycle.
Run with: uvicorn app:app --reload
"""
from __future__ import annotations

import logging
import sys

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from auth.db import create_all_tables
from config import settings
from redis_client import close_redis, get_redis

# ── Structured Logging ────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("t2t")

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="GENIE AI — T2T Backend",
    description=(
        "Twin-to-Twin Communication Protocol Backend. "
        "Policy-gated, auditable, event-driven workflow coordination."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS (adjust origins for production) ─────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.APP_ENV == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global exception handler ──────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception at %s: %s", request.url, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )

# ── Lifecycle events ──────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup() -> None:
    logger.info("T2T Backend starting up (env=%s)", settings.APP_ENV)

    # Import adapters to trigger auto-registration
    import orchestrator.adapters.dummy  # noqa: F401
    import orchestrator.adapters.jira   # noqa: F401
    import orchestrator.adapters.llm_adapter  # noqa: F401

    # Create DB tables (dev only — use Alembic migrations in prod)
    if settings.APP_ENV == "development":
        await create_all_tables()
        logger.info("Database tables created/verified")

    # Verify Redis connection
    try:
        redis = await get_redis()
        await redis.ping()
        logger.info("Redis connection verified")
    except Exception as e:
        logger.warning("Redis connection failed: %s (some features may be degraded)", e)

    logger.info("T2T Backend ready ✓")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await close_redis()
    logger.info("T2T Backend shut down cleanly")

# ── Register routers ──────────────────────────────────────────────────────────

from router.router import router as t2t_router
from router.websocket import ws_router
from notifications.notifications import notif_router
from notifications.escalation import esc_router
from admin.admin_router import admin_router

app.include_router(t2t_router)
app.include_router(ws_router)
app.include_router(notif_router)
app.include_router(esc_router)
app.include_router(admin_router)

# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health() -> dict:
    return {
        "status": "ok",
        "service": "t2t-backend",
        "version": "1.0.0",
        "env": settings.APP_ENV,
    }


@app.get("/", tags=["System"])
async def root() -> dict:
    return {
        "service": "GENIE AI — T2T Backend",
        "docs": "/docs",
        "health": "/health",
        "pipeline": "Human → Twin → SID → Policy → Router → Target Twin → Policy → Orchestrator → Audit → Notify",
    }
