"""
config.py — Centralised settings loaded from environment variables.
"""
import logging
import secrets

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

_PLACEHOLDER_SECRETS = {"change-me", "admin-secret-change-in-prod", "change-this-to-a-strong-random-secret"}


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/t2t_db"
    DATABASE_URL_SYNC: str = "postgresql://postgres:postgres@localhost:5432/t2t_db"
    REDIS_URL: str = "redis://localhost:6379/0"
    APP_ENV: str = "development"
    APP_SECRET_KEY: str = ""
    LOG_LEVEL: str = "INFO"
    IDEMPOTENCY_TTL_SECONDS: int = 86400
    DEFAULT_ESCALATION_SLA_MINUTES: int = 60
    ADMIN_SECRET: str = ""
    WS_AUTH_TIMEOUT_SECONDS: int = 10
    LOOP_DETECTION_MAX_HOPS: int = 20

    # ── DB Pool ──────────────────────────────────────────────────────────────
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # ── LLM Configuration ────────────────────────────────────────────────────
    LLM_PROVIDER: str = "openai"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_MAX_TOKENS: int = 1024
    LLM_TEMPERATURE: float = 0.7
    LLM_TIMEOUT_SECONDS: int = 30

    class Config:
        env_file = ".env"
        extra = "ignore"

    def validate_secrets(self) -> None:
        if self.APP_ENV != "development":
            if not self.APP_SECRET_KEY or self.APP_SECRET_KEY in _PLACEHOLDER_SECRETS:
                raise ValueError("APP_SECRET_KEY must be set to a strong random value in production")
            if not self.ADMIN_SECRET or self.ADMIN_SECRET in _PLACEHOLDER_SECRETS:
                raise ValueError("ADMIN_SECRET must be set to a strong random value in production")
        else:
            if not self.APP_SECRET_KEY or self.APP_SECRET_KEY in _PLACEHOLDER_SECRETS:
                self.APP_SECRET_KEY = secrets.token_urlsafe(32)
                logger.warning("APP_SECRET_KEY not set — using random key (dev only)")
            if not self.ADMIN_SECRET or self.ADMIN_SECRET in _PLACEHOLDER_SECRETS:
                self.ADMIN_SECRET = "dev-admin-secret"
                logger.warning("ADMIN_SECRET not set — using dev default (dev only)")


settings = Settings()
settings.validate_secrets()
