"""
audit/taxonomy.py — Standardised event type enum used across the entire system.
Every call to log_event() must use one of these types.
This enables structured querying: "show me all POLICY_DENIED events for org X".
"""
from enum import Enum


class EventType(str, Enum):
    # ── Identity & Access ──────────────────────────────
    SID_CREATED = "SID_CREATED"
    SID_REVOKED = "SID_REVOKED"
    SSO_BOUND = "SSO_BOUND"
    DEVICE_TRUSTED = "DEVICE_TRUSTED"

    # ── Twin Lifecycle ──────────────────────────────────
    TWIN_REGISTERED = "TWIN_REGISTERED"
    TWIN_SUSPENDED = "TWIN_SUSPENDED"
    TWIN_PERMISSION_CHANGED = "TWIN_PERMISSION_CHANGED"

    # ── Message Pipeline ────────────────────────────────
    MESSAGE_RECEIVED = "MESSAGE_RECEIVED"
    MESSAGE_VALIDATED = "MESSAGE_VALIDATED"
    MESSAGE_SCHEMA_ERROR = "MESSAGE_SCHEMA_ERROR"
    DUPLICATE_DETECTED = "DUPLICATE_DETECTED"

    # ── Policy ──────────────────────────────────────────
    POLICY_ALLOWED = "POLICY_ALLOWED"
    POLICY_DENIED = "POLICY_DENIED"
    POLICY_ESCALATED = "POLICY_ESCALATED"

    # ── Routing ─────────────────────────────────────────
    MESSAGE_ROUTED = "MESSAGE_ROUTED"
    MESSAGE_ACKNOWLEDGED = "MESSAGE_ACKNOWLEDGED"
    DELIVERY_FAILED = "DELIVERY_FAILED"

    # ── Cross-Org ────────────────────────────────────────
    CONTRACT_CREATED = "CONTRACT_CREATED"
    SCOPE_GRANTED = "SCOPE_GRANTED"
    SCOPE_REVOKED = "SCOPE_REVOKED"
    CROSS_ORG_MESSAGE_BLOCKED = "CROSS_ORG_MESSAGE_BLOCKED"

    # ── Orchestration / Execution ────────────────────────
    ORCHESTRATION_STARTED = "ORCHESTRATION_STARTED"
    STEP_STARTED = "STEP_STARTED"
    STEP_COMPLETED = "STEP_COMPLETED"
    STEP_FAILED = "STEP_FAILED"
    WORKFLOW_COMPLETED = "WORKFLOW_COMPLETED"
    WORKFLOW_FAILED = "WORKFLOW_FAILED"
    ROLLBACK_EXECUTED = "ROLLBACK_EXECUTED"
    ROLLBACK_COMPLETED = "ROLLBACK_COMPLETED"

    # ── Operations ───────────────────────────────────────
    TASK_ASSIGNED = "TASK_ASSIGNED"
    TASK_COMPLETED = "TASK_COMPLETED"
    SLA_BREACHED = "SLA_BREACHED"

    # ── Escalation ───────────────────────────────────────
    ESCALATION_CREATED = "ESCALATION_CREATED"
    ESCALATION_APPROVED = "ESCALATION_APPROVED"
    ESCALATION_DENIED = "ESCALATION_DENIED"
    ESCALATION_EXPIRED = "ESCALATION_EXPIRED"

    # ── Memory ───────────────────────────────────────────
    MEMORY_UPDATED = "MEMORY_UPDATED"

    # ── Notifications ────────────────────────────────────
    NOTIFICATION_SENT = "NOTIFICATION_SENT"

    # ── Compliance & Security ────────────────────────────
    CLEARANCE_DENIED = "CLEARANCE_DENIED"
    ANOMALY_DETECTED = "ANOMALY_DETECTED"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    LOOP_DETECTED = "LOOP_DETECTED"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
