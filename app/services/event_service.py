"""
event_service.py — Phase 4
Responsibilities:
  1. create_event()  — insert a new event, enforce unique name
  2. get_events()    — list all events with sorting and upcoming filter
  3. get_event()     — fetch a single event by ID
  4. update_event()  — partial update (PATCH) on name / seats / date
  5. delete_event()  — remove an event and cascade its registrations

All DB interaction lives here. Routes call these functions and do nothing else.
All errors are raised as HTTPException so FastAPI catches and serialises them.
"""

from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from app.models import Event
from app.schemas import EventCreate, EventUpdate


# ─── Helper ───────────────────────────────────────────────────────────────────
def _get_event_or_404(db: Session, event_id: int) -> Event:
    """
    Fetch event by primary key. Raise 404 if not found.
    Extracted into a helper so every service function that needs an event
    doesn't repeat the same fetch-and-check pattern.
    """
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "EVENT_NOT_FOUND",
                "message": f"No event found with id={event_id}",
            },
        )
    return event


# ─── 1. create_event ──────────────────────────────────────────────────────────
def create_event(db: Session, data: EventCreate) -> Event:
    """
    Insert a new event row.

    Steps:
      1. Check for duplicate name   → 409 CONFLICT
      2. Build the ORM object
      3. Add, flush (get the DB-assigned id), refresh, return

    Why flush instead of commit here?
    ─────────────────────────────────
    get_db() in database.py commits automatically when the route returns
    successfully. We only flush() inside service functions to:
      a) obtain the auto-generated id without a full commit
      b) trigger any DB-level constraint violations early (e.g. unique name)
    If something raises after flush(), get_db() rolls back everything.
    """
    # ── Duplicate name check ──────────────────────────────────────────────────
    # Use scalar() instead of .first() so we get the value directly.
    # filter() is case-sensitive in SQLite by default — intentional,
    # "Tech Summit" and "tech summit" are treated as different events.
    existing = db.query(Event).filter(Event.name == data.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "NAME_TAKEN",
                "message": f"An event named '{data.name}' already exists (id={existing.id})",
            },
        )

    # ── Build and persist ─────────────────────────────────────────────────────
    event = Event(
        name=data.name,
        total_seats=data.total_seats,
        available_seats=data.total_seats,   # starts full, decrements on registration
        event_date=data.event_date,
    )

    try:
        db.add(event)
        db.flush()          # sends INSERT, gets id, stays in transaction
        db.refresh(event)   # loads any DB-generated values (created_at, etc.)
    except IntegrityError:
        # Race condition guard: two simultaneous POSTs with the same name.
        # The first passes the Python check above, both hit the DB — the
        # unique index on events.name rejects the second one here.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "NAME_TAKEN",
                "message": f"An event named '{data.name}' already exists",
            },
        )

    return event


# ─── 2. get_events ────────────────────────────────────────────────────────────
def get_events(
    db: Session,
    sort_by: str = "date",
    upcoming_only: bool = False,
) -> list[Event]:
    """
    Return all events with optional filtering and sorting.

    Parameters:
      sort_by       — "date" (default) | "name"
      upcoming_only — if True, exclude events whose date has already passed
    """
    query = db.query(Event)

    # ── Filter ────────────────────────────────────────────────────────────────
    if upcoming_only:
        # SQLite stores datetimes as naive UTC strings.
        # datetime.utcnow() gives a naive datetime — the right type to compare.
        # Using timezone.utc here would produce an aware datetime that
        # SQLite's comparator would reject.
        now = datetime.utcnow()
        query = query.filter(Event.event_date > now)

    # ── Sort ──────────────────────────────────────────────────────────────────
    if sort_by == "name":
        query = query.order_by(Event.name.asc())
    else:
        # Default: chronological order, soonest first
        query = query.order_by(Event.event_date.asc())

    return query.all()


# ─── 3. get_event ─────────────────────────────────────────────────────────────
def get_event(db: Session, event_id: int) -> Event:
    """Fetch a single event by ID. Raises 404 if not found."""
    return _get_event_or_404(db, event_id)


# ─── 4. update_event ──────────────────────────────────────────────────────────
def update_event(db: Session, event_id: int, data: EventUpdate) -> Event:
    """
    Partial update (PATCH semantics) — only update fields that were provided.
    Fields not included in the request body are left unchanged.

    Special case for total_seats:
      If total_seats is being reduced, we must ensure the new value is not
      less than the number of seats already sold. Otherwise available_seats
      would go negative, breaking the invariant.
    """
    event = _get_event_or_404(db, event_id)

    # ── Name change ───────────────────────────────────────────────────────────
    if data.name is not None and data.name != event.name:
        conflict = db.query(Event).filter(Event.name == data.name).first()
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "NAME_TAKEN",
                    "message": f"An event named '{data.name}' already exists",
                },
            )
        event.name = data.name

    # ── Seat count change ─────────────────────────────────────────────────────
    if data.total_seats is not None:
        seats_sold = event.total_seats - event.available_seats
        if data.total_seats < seats_sold:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "INVALID_SEATS",
                    "message": (
                        f"Cannot reduce total_seats to {data.total_seats}. "
                        f"{seats_sold} seat(s) are already sold."
                    ),
                },
            )
        # Adjust available_seats proportionally
        seat_diff = data.total_seats - event.total_seats
        event.total_seats = data.total_seats
        event.available_seats += seat_diff

    # ── Date change ───────────────────────────────────────────────────────────
    if data.event_date is not None:
        event.event_date = data.event_date

    try:
        db.flush()
        db.refresh(event)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "NAME_TAKEN", "message": "Event name already exists"},
        )

    return event


# ─── 5. delete_event ──────────────────────────────────────────────────────────
def delete_event(db: Session, event_id: int) -> dict:
    """
    Delete an event and all its registrations (via cascade).
    Returns a confirmation message dict.
    """
    event = _get_event_or_404(db, event_id)
    event_name = event.name

    db.delete(event)
    db.flush()

    return {
        "message": f"Event '{event_name}' and all its registrations have been deleted"
    }