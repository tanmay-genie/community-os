"""
aria/config.py — Central config loaded from .env
All modules import settings from here.

Fails hard in production if required secrets are missing or use placeholder values.
"""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_PLACEHOLDER_VALUES = {
    "",
    "your-admin-secret-here",
    "your-google-api-key",
    "your-openai-api-key",
    "your-sarvam-api-key",
    "your-livekit-api-key",
    "your-livekit-api-secret",
    "tanmay-key-001",
    "ops-key-001",
    "aria-key-001",
    "change-me",
}


class Settings:
    # CommunityOS DB
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # T2T backend
    T2T_BASE_URL: str = os.getenv("T2T_BASE_URL", "http://localhost:8000")
    T2T_ADMIN_SECRET: str = os.getenv("T2T_ADMIN_SECRET", "")

    # LLM
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # STT / TTS
    SARVAM_API_KEY: str = os.getenv("SARVAM_API_KEY", "")

    # LiveKit
    LIVEKIT_URL: str = os.getenv("LIVEKIT_URL", "")
    LIVEKIT_API_KEY: str = os.getenv("LIVEKIT_API_KEY", "")
    LIVEKIT_API_SECRET: str = os.getenv("LIVEKIT_API_SECRET", "")

    # MCP Server
    MCP_SERVER_PORT: int = int(os.getenv("MCP_SERVER_PORT", "9000"))
    ARIA_SERVER_NAME: str = os.getenv("ARIA_SERVER_NAME", "ARIA")
    APP_ENV: str = os.getenv("APP_ENV", "development")

    # CORS — production must set ALLOWED_ORIGINS explicitly
    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "")

    # Auth — HS256 shared secret for Bearer tokens
    JWT_SECRET: str = os.getenv("JWT_SECRET", "")
    JWT_ISSUER: str = os.getenv("JWT_ISSUER", "communityos-aria")
    JWT_EXPIRY_HOURS: int = int(os.getenv("JWT_EXPIRY_HOURS", "24"))

    def validate(self) -> None:
        is_prod = self.APP_ENV.lower() in ("production", "prod", "staging")
        missing: list[str] = []

        if is_prod:
            if self.T2T_ADMIN_SECRET in _PLACEHOLDER_VALUES:
                missing.append("T2T_ADMIN_SECRET")
            if self.GOOGLE_API_KEY in _PLACEHOLDER_VALUES:
                missing.append("GOOGLE_API_KEY")
            if self.JWT_SECRET in _PLACEHOLDER_VALUES:
                missing.append("JWT_SECRET")
            if not self.ALLOWED_ORIGINS:
                missing.append("ALLOWED_ORIGINS")
            if not self.DATABASE_URL:
                missing.append("DATABASE_URL")
            if missing:
                raise RuntimeError(
                    f"Production APP_ENV={self.APP_ENV} but required secrets missing/placeholder: "
                    f"{', '.join(missing)}"
                )
        else:
            if not self.JWT_SECRET:
                import secrets as _secrets
                self.JWT_SECRET = _secrets.token_urlsafe(32)
                logger.warning("JWT_SECRET not set — using random dev key (won't survive restart)")


settings = Settings()
settings.validate()
