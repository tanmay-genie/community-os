"""society baseline

Creates ARIA's society tables: amenities, bookings, community_events,
dues, community_notices, rsvps. Idempotent (CREATE TABLE IF NOT EXISTS) so
this can be re-run on partially seeded environments without harm.

These tables used to live in T2T's database; they are now owned by ARIA.

Revision ID: 0001_society_baseline
Revises:
Create Date: 2026-05-02 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0001_society_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS amenities (
            amenity_id          VARCHAR(36) PRIMARY KEY,
            org_id              VARCHAR(100) NOT NULL,
            name                VARCHAR(100) NOT NULL,
            display_name        VARCHAR(200) NOT NULL,
            location            VARCHAR(300) DEFAULT '',
            capacity_per_slot   INTEGER DEFAULT 10,
            slot_duration_mins  INTEGER DEFAULT 60,
            open_time           TIME DEFAULT '06:00:00',
            close_time          TIME DEFAULT '22:00:00',
            active              BOOLEAN DEFAULT TRUE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_amenities_org_id ON amenities(org_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            booking_id     VARCHAR(36) PRIMARY KEY,
            amenity_id     VARCHAR(36) NOT NULL,
            org_id         VARCHAR(100) NOT NULL,
            twin_id        VARCHAR(100) NOT NULL,
            slot_date      DATE NOT NULL,
            slot_start     TIME NOT NULL,
            slot_end       TIME NOT NULL,
            status         VARCHAR(20) DEFAULT 'CONFIRMED',
            booked_at      TIMESTAMPTZ DEFAULT NOW(),
            cancelled_at   TIMESTAMPTZ,
            CONSTRAINT uq_booking_per_slot_per_twin
                UNIQUE (amenity_id, slot_date, slot_start, twin_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_bookings_amenity_id ON bookings(amenity_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_bookings_twin_id    ON bookings(twin_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_bookings_slot_date  ON bookings(slot_date)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS community_events (
            event_id      VARCHAR(36) PRIMARY KEY,
            org_id        VARCHAR(100) NOT NULL,
            title         VARCHAR(200) NOT NULL,
            description   VARCHAR(1000) DEFAULT '',
            event_date    DATE NOT NULL,
            event_time    TIME NOT NULL,
            location      VARCHAR(300) DEFAULT '',
            capacity      INTEGER DEFAULT 50,
            rsvp_count    INTEGER DEFAULT 0,
            created_at    TIMESTAMPTZ DEFAULT NOW(),
            active        BOOLEAN DEFAULT TRUE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_community_events_org_id     ON community_events(org_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_community_events_event_date ON community_events(event_date)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS dues (
            due_id      VARCHAR(36) PRIMARY KEY,
            org_id      VARCHAR(100) NOT NULL,
            twin_id     VARCHAR(100) NOT NULL,
            type        VARCHAR(50)  NOT NULL,
            amount      DOUBLE PRECISION NOT NULL,
            due_date    DATE NOT NULL,
            status      VARCHAR(20) DEFAULT 'PENDING',
            paid_at     TIMESTAMPTZ,
            created_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_dues_org_id  ON dues(org_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_dues_twin_id ON dues(twin_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS community_notices (
            notice_id   VARCHAR(36) PRIMARY KEY,
            org_id      VARCHAR(100) NOT NULL,
            title       VARCHAR(200) NOT NULL,
            body        VARCHAR(2000) DEFAULT '',
            priority    VARCHAR(20) DEFAULT 'normal',
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            active      BOOLEAN DEFAULT TRUE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_community_notices_org_id ON community_notices(org_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS rsvps (
            rsvp_id     VARCHAR(36) PRIMARY KEY,
            event_id    VARCHAR(36) NOT NULL,
            twin_id     VARCHAR(100) NOT NULL,
            org_id      VARCHAR(100) NOT NULL,
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT uq_rsvp_per_event_per_twin UNIQUE (event_id, twin_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_rsvps_event_id ON rsvps(event_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_rsvps_twin_id  ON rsvps(twin_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rsvps")
    op.execute("DROP TABLE IF EXISTS community_notices")
    op.execute("DROP TABLE IF EXISTS dues")
    op.execute("DROP TABLE IF EXISTS community_events")
    op.execute("DROP TABLE IF EXISTS bookings")
    op.execute("DROP TABLE IF EXISTS amenities")
