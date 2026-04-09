"""
policy/rbac_rules.py — Role-Based Access Control permission matrix.

Maps each role to the set of IntentTypes it is allowed to initiate.
Add new roles or permissions here without changing the policy engine.
"""
from schemas.intents import IntentType

# ── Permission Matrix ─────────────────────────────────────────────────────────
# Each role → set of allowed intent types
ROLE_PERMISSIONS: dict[str, set[IntentType]] = {

    # ── CommunityOS Roles ────────────────────────────────────────────────────

    # Resident / member — can chat with AI, voice navigate, request things
    "MEMBER": {
        IntentType.REQUEST,         # AI chat, voice commands, ask questions
        IntentType.CONFIRM,         # Confirm AI-suggested actions
        IntentType.DECLINE,         # Decline AI-suggested actions
        IntentType.CANCEL,          # Cancel own requests
        IntentType.UPDATE,          # Receive updates from AI
        IntentType.SURVEY_RESULTS,  # View poll/survey results
    },

    # Property admin — full AI access for property management
    "ADMIN": {
        IntentType.REQUEST,
        IntentType.PROPOSE,
        IntentType.NEGOTIATE,
        IntentType.CONFIRM,
        IntentType.DECLINE,
        IntentType.CANCEL,
        IntentType.EXECUTE,          # AI ops commands, content gen, triage
        IntentType.ESCALATE,
        IntentType.ATTEST,
        IntentType.POLICY_CHECK,     # AI moderation
        IntentType.SHARE_ARTIFACT,
        IntentType.REQUEST_REVIEW,
        IntentType.MEETING_JOIN,
        IntentType.MEETING_SUMMARIZE,
        IntentType.SURVEY_DEPLOY,    # Create polls/surveys
        IntentType.SURVEY_RESULTS,
        IntentType.UPDATE,
    },

    # Property manager — most AI features, no policy changes
    "MANAGER": {
        IntentType.REQUEST,
        IntentType.PROPOSE,
        IntentType.CONFIRM,
        IntentType.DECLINE,
        IntentType.CANCEL,
        IntentType.EXECUTE,          # AI ops commands (medium risk max)
        IntentType.ESCALATE,
        IntentType.SHARE_ARTIFACT,
        IntentType.REQUEST_REVIEW,
        IntentType.MEETING_JOIN,
        IntentType.MEETING_SUMMARIZE,
        IntentType.SURVEY_DEPLOY,
        IntentType.SURVEY_RESULTS,
        IntentType.UPDATE,
    },

    # AI Twin itself — can respond, suggest, update, summarize
    "AI": {
        IntentType.REQUEST,
        IntentType.PROPOSE,
        IntentType.CONFIRM,
        IntentType.DECLINE,
        IntentType.SHARE_ARTIFACT,
        IntentType.MEETING_SUMMARIZE,
        IntentType.SURVEY_RESULTS,
        IntentType.UPDATE,
    },

    # System/automation — triggered by pipelines (moderation, triage, etc.)
    "SYSTEM": {
        IntentType.REQUEST,
        IntentType.PROPOSE,
        IntentType.CONFIRM,
        IntentType.DECLINE,
        IntentType.CANCEL,
        IntentType.EXECUTE,
        IntentType.ESCALATE,
        IntentType.ATTEST,
        IntentType.POLICY_CHECK,
        IntentType.SHARE_ARTIFACT,
        IntentType.MEETING_SUMMARIZE,
        IntentType.SURVEY_DEPLOY,
        IntentType.SURVEY_RESULTS,
        IntentType.UPDATE,
    },

    # ── Genie AI Internal Roles ──────────────────────────────────────────────

    "Founder_CEO": {
        IntentType.REQUEST,
        IntentType.PROPOSE,
        IntentType.NEGOTIATE,
        IntentType.CONFIRM,
        IntentType.DECLINE,
        IntentType.CANCEL,
        IntentType.EXECUTE,
        IntentType.ESCALATE,
        IntentType.ATTEST,
        IntentType.POLICY_CHECK,
        IntentType.SHARE_ARTIFACT,
        IntentType.REQUEST_REVIEW,
        IntentType.MEETING_JOIN,
        IntentType.MEETING_SUMMARIZE,
        IntentType.SURVEY_DEPLOY,
        IntentType.SURVEY_RESULTS,
        IntentType.UPDATE,
    },

    "Product": {
        IntentType.REQUEST,
        IntentType.PROPOSE,
        IntentType.NEGOTIATE,
        IntentType.CONFIRM,
        IntentType.DECLINE,
        IntentType.CANCEL,
        IntentType.EXECUTE,
        IntentType.ESCALATE,
        IntentType.SHARE_ARTIFACT,
        IntentType.REQUEST_REVIEW,
        IntentType.MEETING_JOIN,
        IntentType.MEETING_SUMMARIZE,
        IntentType.SURVEY_DEPLOY,
        IntentType.UPDATE,
    },

    "Engineering": {
        IntentType.REQUEST,
        IntentType.PROPOSE,
        IntentType.NEGOTIATE,
        IntentType.CONFIRM,
        IntentType.DECLINE,
        IntentType.EXECUTE,
        IntentType.ESCALATE,
        IntentType.SHARE_ARTIFACT,
        IntentType.REQUEST_REVIEW,
        IntentType.MEETING_JOIN,
        IntentType.UPDATE,
    },

    "Security": {
        IntentType.REQUEST,
        IntentType.PROPOSE,
        IntentType.CONFIRM,
        IntentType.DECLINE,
        IntentType.ESCALATE,
        IntentType.ATTEST,
        IntentType.POLICY_CHECK,
        IntentType.SHARE_ARTIFACT,
        IntentType.REQUEST_REVIEW,
        IntentType.MEETING_JOIN,
        IntentType.UPDATE,
    },

    "Sales": {
        IntentType.REQUEST,
        IntentType.PROPOSE,
        IntentType.NEGOTIATE,
        IntentType.CONFIRM,
        IntentType.DECLINE,
        IntentType.SHARE_ARTIFACT,
        IntentType.MEETING_JOIN,
        IntentType.SURVEY_DEPLOY,
        IntentType.UPDATE,
    },

    "Procurement": {
        IntentType.REQUEST,
        IntentType.CONFIRM,
        IntentType.DECLINE,
        IntentType.ATTEST,
        IntentType.SHARE_ARTIFACT,
        IntentType.UPDATE,
    },

    # Default fallback for unknown roles — very restricted
    "__default__": {
        IntentType.REQUEST,
        IntentType.UPDATE,
    },
}


def get_allowed_intents(role: str) -> set[IntentType]:
    """Return the set of allowed IntentTypes for the given role."""
    return ROLE_PERMISSIONS.get(role, ROLE_PERMISSIONS["__default__"])


def role_can_send(role: str, intent_type: IntentType) -> bool:
    """Return True if the role is allowed to send the given intent type."""
    return intent_type in get_allowed_intents(role)
