"""
schemas/intents.py — All intent types, risk levels, clearance levels,
message states, and org-related enums used across the entire system.
"""
from enum import Enum


class IntentType(str, Enum):
    # Coordination
    REQUEST = "REQUEST"
    PROPOSE = "PROPOSE"
    NEGOTIATE = "NEGOTIATE"
    CONFIRM = "CONFIRM"
    DECLINE = "DECLINE"
    CANCEL = "CANCEL"
    # Execution
    EXECUTE = "EXECUTE"
    COMPLETE = "COMPLETE"
    FAIL = "FAIL"
    # Governance
    ESCALATE = "ESCALATE"
    ATTEST = "ATTEST"
    POLICY_CHECK = "POLICY_CHECK"
    # Collaboration
    SHARE_ARTIFACT = "SHARE_ARTIFACT"
    REQUEST_REVIEW = "REQUEST_REVIEW"
    MEETING_JOIN = "MEETING_JOIN"
    MEETING_SUMMARIZE = "MEETING_SUMMARIZE"
    SURVEY_DEPLOY = "SURVEY_DEPLOY"
    SURVEY_RESULTS = "SURVEY_RESULTS"
    # Internal reply types
    UPDATE = "UPDATE"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ClearanceLevel(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    SECRET = "SECRET"


class MessageState(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    SCOPED = "SCOPED"
    ROUTED = "ROUTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DECIDED = "DECIDED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"
    CANCELLED = "CANCELLED"


class PolicyDecision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


class TwinStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class AutonomyLevel(str, Enum):
    ADVISORY = "ADVISORY"
    ASSISTIVE = "ASSISTIVE"
    SEMI_AUTONOMOUS = "SEMI_AUTONOMOUS"
    AUTONOMOUS = "AUTONOMOUS"
