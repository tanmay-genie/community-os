"""
notifications/notifications.py — Notification Service.

Sends structured notifications to twins after terminal pipeline states.
Types: INFORMATIONAL, ACTION_REQUIRED, ESCALATION_REQUIRED, SLA_BREACH.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, String, Text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from audit.audit import log_event
from audit.taxonomy import EventType
from auth.db import Base

logger = logging.getLogger(__name__)


class NotificationType(str, Enum):
    INFORMATIONAL = "INFORMATIONAL"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    ESCALATION_REQUIRED = "ESCALATION_REQUIRED"
    SLA_BREACH = "SLA_BREACH"


class NotificationModel(Base):
    __tablename__ = "notifications"

    notification_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    to_twin_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    from_system: Mapped[str] = mapped_column(String(100), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(36), index=True)
    thread_id: Mapped[str | None] = mapped_column(String(36))
    is_read: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


async def send_notification(
    db: AsyncSession,
    to_twin_id: str,
    from_system: str,
    notification_type: NotificationType,
    title: str,
    body: str,
    message_id: str | None = None,
    thread_id: str | None = None,
) -> NotificationModel:
    """Create and persist a notification for a twin."""
    notif = NotificationModel(
        notification_id=str(uuid.uuid4()),
        to_twin_id=to_twin_id,
        from_system=from_system,
        notification_type=notification_type.value,
        title=title,
        body=body,
        message_id=message_id,
        thread_id=thread_id,
    )
    db.add(notif)
    await db.flush()

    await log_event(
        db=db,
        event_type=EventType.NOTIFICATION_SENT,
        twin_id=to_twin_id,
        message_id=message_id,
        thread_id=thread_id,
        result=notification_type.value,
        reason=title,
    )

    logger.info(
        "Notification sent: to=%s type=%s title=%s",
        to_twin_id, notification_type.value, title,
    )
    return notif


# ── Notifications API ─────────────────────────────────────────────────────────

from fastapi import APIRouter, Depends
from sqlalchemy import select
from auth.auth import TwinContext, verify_twin
from auth.db import get_db

notif_router = APIRouter(prefix="/t2t/notifications", tags=["Notifications"])


@notif_router.get("/")
async def get_my_notifications(
    twin: TwinContext = Depends(verify_twin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await db.execute(
        select(NotificationModel)
        .where(NotificationModel.to_twin_id == twin.twin_id)
        .order_by(NotificationModel.created_at.desc())
        .limit(50)
    )
    notifs = result.scalars().all()
    return [
        {
            "notification_id": n.notification_id,
            "type": n.notification_type,
            "title": n.title,
            "body": n.body,
            "message_id": n.message_id,
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat(),
        }
        for n in notifs
    ]
