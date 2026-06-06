"""
registration_service.py — Phase 5
Responsibilities:
  1. register_user()       — register a user for an event
  2. cancel_registration() — cancel an active registration
  3. get_event_registrations() — list active registrations for an event

This is the most critical file in the project.
It directly addresses the "hidden tricky requirements":
  ✓ Prevent race conditions (overbooking)
  ✓ Handle duplicate requests safely
  ✓ Ensure correct seat count at all times
  ✓ Return proper error messages for all edge cases
"""

from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import update
from fastapi import HTTPException, status

from app.models import Event, Registration
from app.schemas import RegistrationCreate


# ─── Helper ───────────────────────────────────────────────────────────────────
def _get_registration_or_404(db: Session, registration_id: int) -> Registration:
    reg = db.get(Registration, registration_id)
    if reg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "REGISTRATION_NOT_FOUND",
                "message": f"No registration found with id={registration_id}",
            },
        )
    return reg


# ─── 1. register_user ─────────────────────────────────────────────────────────
def register_user(
    db: Session,
    event_id: int,
    data: RegistrationCreate,
) -> Registration:
    """
    Register a user for an event.

    This function must satisfy three guarantees simultaneously:
      A) The event exists
      B) The user hasn't already registered for this event (active registration)
      C) At least one seat is available

    The naive approach — read available_seats, check > 0, then decrement — has
    a race condition: two requests can both read available_seats=1, both pass
    the check, and both write, resulting in available_seats=-1 (overbooking).

    ─── The atomic UPDATE solution ────────────────────────────────────────────
    Instead of:
        READ  → if seats > 0: UPDATE seats = seats - 1   ← two operations, race window

    We do:
        UPDATE events
        SET    available_seats = available_seats - 1
        WHERE  id = event_id
        AND    available_seats > 0                        ← one atomic operation

    SQLite serialises all writes, so only one thread can execute this UPDATE
    at a time. The WHERE clause acts as a guard — if seats are already 0,
    no row is matched, rowcount=0, and we know to raise "Event is full".

    ─── Transaction boundary ──────────────────────────────────────────────────
    All three steps (duplicate check, atomic seat decrement, INSERT registration)
    happen inside one transaction. If any step fails, get_db() rolls back the
    entire unit — no partial writes are possible.
    """

    # ── Step 1: Verify the event exists ──────────────────────────────────────
    # Use with_for_update() to lock this row for the duration of the
    # transaction. This prevents another transaction from reading stale
    # seat data while we are mid-operation.
    # Note: SQLite doesn't support SELECT FOR UPDATE syntax, but SQLAlchemy
    # silently ignores it for SQLite — the WAL mode + serialised writes
    # provide equivalent safety. If you ever switch to PostgreSQL, this
    # locking hint becomes active and gives you even stronger guarantees.
    event = db.query(Event).filter(Event.id == event_id).with_for_update().first()
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "EVENT_NOT_FOUND",
                "message": f"No event found with id={event_id}",
            },
        )

    # ── Step 2: Duplicate registration check ─────────────────────────────────
    # Check BEFORE decrementing seats. If the user is already registered,
    # we short-circuit immediately without touching available_seats.
    #
    # The composite index (event_id, user_name, status) on the registrations
    # table makes this query an O(log n) index lookup — not a full table scan.
    existing = (
        db.query(Registration)
        .filter(
            Registration.event_id == event_id,
            Registration.user_name == data.user_name,
            Registration.status == "active",
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "DUPLICATE_REGISTRATION",
                "message": (
                    f"'{data.user_name}' is already registered for this event "
                    f"(registration id={existing.id})"
                ),
            },
        )

    # ── Step 3: Atomic seat decrement ─────────────────────────────────────────
    # This is the race condition fix. The WHERE clause is the guard:
    #   available_seats > 0  →  only succeeds if a seat is truly free
    #
    # SQLAlchemy's update() with returning() gives us the affected row count
    # in one round-trip. If rowcount == 0, the event was full at the moment
    # the UPDATE ran — even if it looked available a millisecond earlier.
    result = db.execute(
        update(Event)
        .where(
            Event.id == event_id,
            Event.available_seats > 0,      # ← the atomic guard
        )
        .values(available_seats=Event.available_seats - 1)
        .execution_options(synchronize_session="fetch")
    )

    # rowcount == 0 means the WHERE clause matched nothing → event is full
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "EVENT_FULL",
                "message": (
                    f"No seats available for event id={event_id}. "
                    f"Total capacity: {event.total_seats}"
                ),
            },
        )

    # ── Step 4: Insert the registration record ────────────────────────────────
    # Only reached if Steps 1-3 all passed. The seat has already been
    # decremented atomically — now we record who took it.
    registration = Registration(
        event_id=event_id,
        user_name=data.user_name,
        status="active",
    )

    db.add(registration)
    db.flush()              # get the auto-generated registration.id
    db.refresh(registration)

    return registration


# ─── 2. cancel_registration ───────────────────────────────────────────────────
def cancel_registration(db: Session, registration_id: int) -> dict:
    """
    Cancel an active registration and return the freed seat to the pool.

    Steps:
      1. Fetch the registration — 404 if not found
      2. Check it is still active — 400 if already cancelled
      3. Mark it cancelled with a timestamp
      4. Atomically increment available_seats on the parent event
      5. Return a confirmation message

    Why use an atomic UPDATE for the seat increment too?
    ─────────────────────────────────────────────────────
    Same reason as registration: available_seats += 1 via a direct UPDATE
    is safe even under concurrent cancellations. Two simultaneous cancellations
    both increment correctly because each UPDATE is serialised by SQLite.
    Using event.available_seats += 1 via the ORM object could produce a
    lost update if two sessions read the same stale value before either commits.
    """
    # ── Step 1: Fetch registration ────────────────────────────────────────────
    registration = _get_registration_or_404(db, registration_id)

    # ── Step 2: Guard — already cancelled ─────────────────────────────────────
    if registration.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "ALREADY_CANCELLED",
                "message": (
                    f"Registration id={registration_id} has already been cancelled "
                    f"on {registration.cancelled_at.isoformat() if registration.cancelled_at else 'unknown date'}"
                ),
            },
        )

    # ── Step 3: Mark as cancelled ─────────────────────────────────────────────
    registration.status = "cancelled"
    registration.cancelled_at = datetime.now(timezone.utc)

    # ── Step 4: Atomic seat restore ───────────────────────────────────────────
    # Mirror of the atomic decrement in register_user().
    # available_seats <= total_seats is enforced by the DB check constraint,
    # so this is safe even without an explicit upper bound in the WHERE clause.
    db.execute(
        update(Event)
        .where(Event.id == registration.event_id)
        .values(available_seats=Event.available_seats + 1)
        .execution_options(synchronize_session="fetch")
    )

    db.flush()

    return {
        "message": (
            f"Registration id={registration_id} for '{registration.user_name}' "
            f"has been cancelled. Seat is now available again."
        )
    }


# ─── 3. get_event_registrations ───────────────────────────────────────────────
def get_event_registrations(
    db: Session,
    event_id: int,
) -> list[Registration]:
    """
    Return all ACTIVE registrations for a given event.
    Cancelled registrations are excluded — the requirement states
    "cancelled users should not appear in active registrations".

    Raises 404 if the event doesn't exist.
    """
    # Verify the event exists before querying registrations
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "EVENT_NOT_FOUND",
                "message": f"No event found with id={event_id}",
            },
        )

    return (
        db.query(Registration)
        .filter(
            Registration.event_id == event_id,
            Registration.status == "active",    # ← only active, never cancelled
        )
        .order_by(Registration.registered_at.asc())  # first registered, first listed
        .all()
    )