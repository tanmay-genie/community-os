"""
agent_aria.py — ARIA Voice Agent
Run: uv run aria-voice
LiveKit-based voice pipeline: STT → LLM → TTS
Connects to MCP server for tools.
Supports member and admin roles via separate entry points.
"""

import os
import logging

from dotenv import load_dotenv
from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.voice import Agent, AgentSession
from livekit.agents.llm import mcp
from livekit.plugins import google as lk_google, openai as lk_openai, sarvam, silero

from aria.prompts.templates import get_prompt
from aria.config import settings

# ── Provider config (swap here) ────────────────────────────────────────────

STT_PROVIDER = "sarvam"    # "sarvam" | "whisper"
LLM_PROVIDER = "gemini"    # "gemini" | "openai"
TTS_PROVIDER = "openai"    # "openai" | "sarvam"

GEMINI_MODEL  = "gemini-2.5-flash"
OPENAI_LLM    = "gpt-4o"
OPENAI_TTS    = "tts-1"
OPENAI_VOICE  = "nova"
TTS_SPEED     = 1.1

MCP_SERVER_URL = f"http://127.0.0.1:{settings.MCP_SERVER_PORT}/sse"

# ── Logging ────────────────────────────────────────────────────────────────

load_dotenv()
logger = logging.getLogger("aria-agent")
logger.setLevel(logging.INFO)

# ── Provider builders ──────────────────────────────────────────────────────

def _build_stt():
    if STT_PROVIDER == "sarvam":
        logger.info("STT → Sarvam Saaras v3 (Indian-English)")
        return sarvam.STT(
            language="unknown",
            model="saaras:v3",
            mode="transcribe",
            flush_signal=True,
            sample_rate=16000,
        )
    logger.info("STT → OpenAI Whisper")
    return lk_openai.STT(model="whisper-1")


def _build_llm():
    if LLM_PROVIDER == "gemini":
        logger.info("LLM → Gemini %s", GEMINI_MODEL)
        return lk_google.LLM(
            model=GEMINI_MODEL,
            api_key=settings.GOOGLE_API_KEY,
        )
    logger.info("LLM → OpenAI %s", OPENAI_LLM)
    return lk_openai.LLM(model=OPENAI_LLM)


def _build_tts():
    if TTS_PROVIDER == "sarvam":
        logger.info("TTS → Sarvam Bulbul v3")
        return sarvam.TTS(
            target_language_code="en-IN",
            model="bulbul:v3",
            speaker="rahul",
            pace=TTS_SPEED,
        )
    logger.info("TTS → OpenAI %s / %s", OPENAI_TTS, OPENAI_VOICE)
    return lk_openai.TTS(
        model=OPENAI_TTS,
        voice=OPENAI_VOICE,
        speed=TTS_SPEED,
    )


# ── ARIA Agent ─────────────────────────────────────────────────────────────

class ARIAAgent(Agent):
    """
    ARIA voice agent.
    Role is passed at construction time — determines system prompt and tools.
    """

    def __init__(self, stt, llm, tts, role: str = "member") -> None:
        super().__init__(
            instructions=get_prompt(role),
            stt=stt,
            llm=llm,
            tts=tts,
            vad=silero.VAD.load(),
            mcp_servers=[
                mcp.MCPServerHTTP(
                    url=MCP_SERVER_URL,
                    transport_type="sse",
                    client_session_timeout_seconds=30,
                ),
            ],
        )
        self.role = role

    async def on_enter(self) -> None:
        if self.role == "admin":
            await self.session.generate_reply(
                instructions=(
                    "Greet the admin: 'ARIA online. "
                    "Ready when you are. What would you like to review?'"
                )
            )
        else:
            await self.session.generate_reply(
                instructions=(
                    "Greet the resident warmly: "
                    "'Hi! I'm ARIA, your society assistant. How can I help you today?'"
                )
            )


# ── Entry points ───────────────────────────────────────────────────────────

def _turn_detection():
    return "stt" if STT_PROVIDER == "sarvam" else "vad"


def _endpointing_delay():
    return {"sarvam": 0.07, "whisper": 0.3}.get(STT_PROVIDER, 0.1)


async def _start_agent(ctx: JobContext, role: str) -> None:
    logger.info(
        "ARIA online — room: %s | role: %s | STT=%s | LLM=%s | TTS=%s",
        ctx.room.name, role, STT_PROVIDER, LLM_PROVIDER, TTS_PROVIDER,
    )
    stt = _build_stt()
    llm = _build_llm()
    tts = _build_tts()

    session = AgentSession(
        turn_detection=_turn_detection(),
        min_endpointing_delay=_endpointing_delay(),
    )
    await session.start(
        agent=ARIAAgent(stt=stt, llm=llm, tts=tts, role=role),
        room=ctx.room,
    )


# Member voice entry
async def entrypoint_member(ctx: JobContext) -> None:
    await _start_agent(ctx, role="member")


# Admin voice entry
async def entrypoint_admin(ctx: JobContext) -> None:
    await _start_agent(ctx, role="admin")


# ── Main ───────────────────────────────────────────────────────────────────

def main_member():
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint_member))


def main_admin():
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint_admin))


def dev():
    """Default dev entry — starts member agent."""
    import sys
    if len(sys.argv) == 1:
        sys.argv.append("dev")
    main_member()


if __name__ == "__main__":
    dev()
