"""
aria/config.py — Central config loaded from .env
All modules import settings from here.
"""

import os
from dotenv import load_dotenv

load_dotenv()


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


settings = Settings()
