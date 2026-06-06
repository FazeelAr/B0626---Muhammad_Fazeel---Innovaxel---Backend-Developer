"""
models.py — Phase 2
Responsibilities:
  1. Define the Event ORM model   → maps to the "events" table
  2. Define the Registration ORM model → maps to the "registrations" table
  3. Set up relationships, indexes, and constraints between them

These classes are what SQLAlchemy uses to:
  - Generate the CREATE TABLE SQL on startup
  - Map Python objects ↔ database rows throughout the app
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    Index,
    CheckConstraint,
)
from sqlalchemy.orm import relationship, validates
from app.database import Base


# ─── Helper ───────────────────────────────────────────────────────────────────
def utcnow() -> datetime:
    """Return current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


# ─── 1. Event Model ───────────────────────────────────────────────────────────
class Event(Base):
    __tablename__ = "events"

    # Primary key — auto-incremented by SQLite
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Event name must be unique across all rows.
    # index=True creates a B-tree index for fast lookups by name.
    name = Column(String(255), nullable=False, unique=True, index=True)

    # Total capacity — set at creation time, never changes after that.
    total_seats = Column(Integer, nullable=False)

    # Available seats — starts equal to total_seats, decremented on each
    # registration, incremented on each cancellation.
    # Stored explicitly (not derived) so we can use an atomic UPDATE on it,
    # which is the core of our race condition prevention strategy.
    available_seats = Column(Integer, nullable=False)

    # Must be a future date — enforced in Pydantic schema (Phase 3) AND
    # as a DB-level check constraint here for double safety.
    event_date = Column(DateTime(timezone=True), nullable=False)

    # Audit timestamp — set automatically, never updated.
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )

    # ── Relationship ──────────────────────────────────────────────────────────
    # "registrations" gives us event.registrations to access related rows.
    # back_populates="event" creates the reverse: registration.event
    # cascade="all, delete-orphan" means if an Event is deleted, all its
    # Registration rows are automatically deleted too.
    registrations = relationship(
        "Registration",
        back_populates="event",
        cascade="all, delete-orphan",
    )

    # ── DB-level constraints ──────────────────────────────────────────────────
    # These run inside the database engine as a last line of defence,
    # even if application-level validation somehow fails.
    __table_args__ = (
        CheckConstraint("total_seats > 0", name="ck_events_total_seats_positive"),
        CheckConstraint("available_seats >= 0", name="ck_events_available_seats_non_negative"),
        CheckConstraint("available_seats <= total_seats", name="ck_events_seats_not_exceed_total"),
    )

    # ── ORM-level validator ───────────────────────────────────────────────────
    # Runs before any INSERT or UPDATE on these columns.
    @validates("total_seats")
    def validate_total_seats(self, key, value):
        if value <= 0:
            raise ValueError("total_seats must be greater than 0")
        return value

    @validates("available_seats")
    def validate_available_seats(self, key, value):
        if value < 0:
            raise ValueError("available_seats cannot be negative")
        return value

    # ── Convenience properties ────────────────────────────────────────────────
    @property
    def total_registrations(self) -> int:
        """Active registrations = seats sold = total - available."""
        return self.total_seats - self.available_seats

    @property
    def is_full(self) -> bool:
        return self.available_seats == 0

    @property
    def is_upcoming(self) -> bool:
        # SQLite stores datetimes without timezone info, so we compare
        # against a naive UTC datetime to avoid offset-aware vs offset-naive
        # comparison errors. The DB always stores UTC, so this is safe.
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        event_dt = self.event_date.replace(tzinfo=None) if self.event_date.tzinfo else self.event_date
        return event_dt > now

    def __repr__(self) -> str:
        return (
            f"<Event id={self.id} name='{self.name}' "
            f"seats={self.available_seats}/{self.total_seats} "
            f"date={self.event_date.date()}>"
        )


# ─── 2. Registration Model ────────────────────────────────────────────────────
class Registration(Base):
    __tablename__ = "registrations"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Foreign key — references events.id.
    # ondelete="CASCADE" mirrors the ORM cascade above at the SQL level.
    event_id = Column(
        Integer,
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )

    user_name = Column(String(255), nullable=False)

    # Status tracks whether this registration is still active.
    # Two valid values: "active" | "cancelled"
    status = Column(String(20), nullable=False, default="active")

    registered_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )

    # Set only when the user cancels — NULL means still active.
    cancelled_at = Column(DateTime(timezone=True), nullable=True)

    # ── Relationship ──────────────────────────────────────────────────────────
    event = relationship("Event", back_populates="registrations")

    # ── Indexes and constraints ───────────────────────────────────────────────
    # Composite index on the three columns used by the duplicate-check query.
    # Without this, that query scans every row in the table.
    # With it, the lookup is O(log n) regardless of table size.
    __table_args__ = (
        Index(
            "ix_registrations_event_user_status",
            "event_id",
            "user_name",
            "status",
        ),
        CheckConstraint(
            "status IN ('active', 'cancelled')",
            name="ck_registrations_status_valid",
        ),
    )

    # ── ORM-level validator ───────────────────────────────────────────────────
    @validates("status")
    def validate_status(self, key, value):
        allowed = {"active", "cancelled"}
        if value not in allowed:
            raise ValueError(f"status must be one of {allowed}, got '{value}'")
        return value

    # ── Convenience properties ────────────────────────────────────────────────
    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def __repr__(self) -> str:
        return (
            f"<Registration id={self.id} event_id={self.event_id} "
            f"user='{self.user_name}' status={self.status}>"
        )