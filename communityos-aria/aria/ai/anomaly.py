"""
aria.ai.anomaly — Admin-facing anomaly detection.

Detects unusual patterns:
  - Spike in tickets from a single unit
  - Unusual booking hours (late-night reservations)
  - Repeated identical messages (spam/bot)
  - High-frequency escalation triggers
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock

logger = logging.getLogger("aria.ai.anomaly")


@dataclass
class AnomalyAlert:
    kind: str
    severity: str
    subject: str
    details: dict


class AnomalyDetector:
    def __init__(self):
        self._tickets_by_unit: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self._bookings_by_twin: dict[str, deque] = defaultdict(lambda: deque(maxlen=50))
        self._messages_by_twin: dict[str, deque] = defaultdict(lambda: deque(maxlen=30))
        self._lock = Lock()

    def record_ticket(self, unit: str, priority: str, description: str) -> AnomalyAlert | None:
        now = time.time()
        with self._lock:
            bucket = self._tickets_by_unit[unit]
            bucket.append({"ts": now, "priority": priority, "desc": description[:80]})
            recent = [b for b in bucket if now - b["ts"] < 3600]
            if len(recent) >= 5:
                return AnomalyAlert(
                    kind="ticket_spike", severity="HIGH", subject=f"unit:{unit}",
                    details={"count_last_hour": len(recent),
                             "priorities": [b["priority"] for b in recent]},
                )
        return None

    def record_booking(self, twin_id: str, amenity: str, slot_start: str) -> AnomalyAlert | None:
        try:
            hour = int(slot_start.split(":")[0])
        except Exception:
            return None
        if hour >= 22 or hour < 6:
            return AnomalyAlert(
                kind="odd_hour_booking", severity="MEDIUM",
                subject=f"twin:{twin_id} amenity:{amenity}",
                details={"slot_start": slot_start, "hour": hour},
            )
        now = time.time()
        with self._lock:
            bucket = self._bookings_by_twin[twin_id]
            bucket.append({"ts": now, "amenity": amenity, "slot": slot_start})
            recent = [b for b in bucket if now - b["ts"] < 86400]
            if len(recent) > 8:
                return AnomalyAlert(
                    kind="booking_flood", severity="MEDIUM", subject=f"twin:{twin_id}",
                    details={"count_last_24h": len(recent)},
                )
        return None

    def record_message(self, twin_id: str, message: str) -> AnomalyAlert | None:
        now = time.time()
        norm = message.strip().lower()
        with self._lock:
            bucket = self._messages_by_twin[twin_id]
            bucket.append({"ts": now, "msg": norm})
            recent = [b for b in bucket if now - b["ts"] < 120]
            if len(recent) >= 6:
                return AnomalyAlert(
                    kind="rapid_messaging", severity="LOW", subject=f"twin:{twin_id}",
                    details={"count_last_2min": len(recent)},
                )
            dupes = sum(1 for b in recent if b["msg"] == norm)
            if dupes >= 4:
                return AnomalyAlert(
                    kind="repeated_message", severity="MEDIUM", subject=f"twin:{twin_id}",
                    details={"duplicate_count": dupes, "message": norm[:80]},
                )
        return None


detector = AnomalyDetector()
