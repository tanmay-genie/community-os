"""
config.py — Centralised settings loaded from environment variables.
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/t2t_db"
    DATABASE_URL_SYNC: str = "postgresql://postgres:password@localhost:5432/t2t_db"
    REDIS_URL: str = "redis://localhost:6379/0"
    APP_ENV: str = "development"
    APP_SECRET_KEY: str = "change-me"
    LOG_LEVEL: str = "INFO"
    IDEMPOTENCY_TTL_SECONDS: int = 86400
    DEFAULT_ESCALATION_SLA_MINUTES: int = 60
    ADMIN_SECRET: str = "admin-secret-change-in-prod"
    WS_AUTH_TIMEOUT_SECONDS: int = 10
    LOOP_DETECTION_MAX_HOPS: int = 20

    # ── LLM Configuration ────────────────────────────────────────────────────
    LLM_PROVIDER: str = "openai"                    # "openai" or "anthropic"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o-mini"                  # or "claude-sonnet-4-20250514"
    LLM_MAX_TOKENS: int = 1024
    LLM_TEMPERATURE: float = 0.7
    LLM_TIMEOUT_SECONDS: int = 30

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
