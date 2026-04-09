"""
aria/context/loader.py — User context loader.

Fetches unit, role, org, and Redis memory for the current user
before the LLM call so ARIA is always society-aware.
"""

import json
import redis.asyncio as aioredis
from aria.config import settings


redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)


async def load_user_context(twin_id: str) -> dict:
    """
    Returns a dict with everything ARIA needs to know about the user:
      - twin_id, org_id, unit, role
      - recent action history from Redis (t2t memory/user.py format)
      - pending dues flag
      - display name
    Falls back gracefully if Redis is unavailable.
    """
    context = {
        "twin_id": twin_id,
        "org_id": "UNKNOWN",
        "unit": "UNKNOWN",
        "role": "RESIDENT",
        "display_name": twin_id,
        "recent_actions": [],
        "pending_dues": False,
    }

    try:
        # T2T memory/user.py stores actions at key: user_memory:{twin_id}
        raw = await redis_client.get(f"user_memory:{twin_id}")
        if raw:
            memory = json.loads(raw)
            context["recent_actions"] = memory.get("actions", [])[-5:]  # last 5

        # CommunityOS stores user profile at: aria_user:{twin_id}
        profile_raw = await redis_client.get(f"aria_user:{twin_id}")
        if profile_raw:
            profile = json.loads(profile_raw)
            context.update({
                "org_id": profile.get("org_id", context["org_id"]),
                "unit": profile.get("unit", context["unit"]),
                "role": profile.get("role", context["role"]),
                "display_name": profile.get("display_name", twin_id),
                "pending_dues": profile.get("pending_dues", False),
            })

    except Exception:
        # Redis down — return defaults, ARIA still works
        pass

    return context


async def build_context_string(twin_id: str) -> str:
    """
    Returns a short context string injected into every ARIA LLM call.
    Example:
      User: Tanmay | Unit: A-404 | Role: RESIDENT | Org: SUNRISE_SOCIETY
      Recent actions: booked gym (yesterday), raised AC ticket (3 days ago)
      Pending dues: No
    """
    ctx = await load_user_context(twin_id)

    actions_str = (
        ", ".join(ctx["recent_actions"]) if ctx["recent_actions"] else "none"
    )
    dues_str = "YES — remind gently" if ctx["pending_dues"] else "No"

    return (
        f"User: {ctx['display_name']} | "
        f"Unit: {ctx['unit']} | "
        f"Role: {ctx['role']} | "
        f"Org: {ctx['org_id']}\n"
        f"Recent actions: {actions_str}\n"
        f"Pending dues: {dues_str}"
    )


async def save_user_action(twin_id: str, action: str) -> None:
    """
    Append a new action to the user's Redis memory after ARIA executes.
    Keeps last 20 actions only.
    """
    try:
        raw = await redis_client.get(f"user_memory:{twin_id}")
        memory = json.loads(raw) if raw else {"actions": []}
        memory["actions"].append(action)
        memory["actions"] = memory["actions"][-20:]
        await redis_client.set(
            f"user_memory:{twin_id}",
            json.dumps(memory),
            ex=60 * 60 * 24 * 30,  # 30 days TTL
        )
    except Exception:
        pass
