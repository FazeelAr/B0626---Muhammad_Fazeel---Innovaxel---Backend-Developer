"""
routers/events.py — Phase 6a
Endpoints:
  POST   /events                          → create event
  GET    /events                          → list events
  GET    /events/{event_id}               → get single event
  PATCH  /events/{event_id}               → update event
  DELETE /events/{event_id}               → delete event
  GET    /events/{event_id}/registrations → list active registrations
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    EventCreate, EventUpdate, EventResponse,
    RegistrationResponse, MessageResponse, ErrorResponse,
)
from app.services import event_service, registration_service

router = APIRouter()


@router.post(
    "/",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new event",
    responses={
        409: {"model": ErrorResponse, "description": "Event name already taken"},
        422: {"description": "Validation error (past date, zero seats, blank name)"},
    },
)
def create_event(data: EventCreate, db: Session = Depends(get_db)):
    """
    Create a new event.

    Rules enforced:
    - Name must be unique
    - total_seats must be > 0
    - event_date must be in the future
    """
    return event_service.create_event(db, data)


@router.get(
    "/",
    response_model=list[EventResponse],
    summary="List all events",
)
def list_events(
    sort_by: str = Query(
        default="date",
        pattern="^(date|name)$",
        description="Sort results by 'date' (default) or 'name'",
    ),
    upcoming_only: bool = Query(
        default=False,
        description="If true, only return events whose date has not passed",
    ),
    db: Session = Depends(get_db),
):
    """
    Retrieve all events.

    Supports:
    - **sort_by**: `date` (chronological, soonest first) or `name` (A→Z)
    - **upcoming_only**: exclude past events
    """
    return event_service.get_events(db, sort_by=sort_by, upcoming_only=upcoming_only)


@router.get(
    "/{event_id}",
    response_model=EventResponse,
    summary="Get a single event by ID",
    responses={
        404: {"model": ErrorResponse, "description": "Event not found"},
    },
)
def get_event(event_id: int, db: Session = Depends(get_db)):
    return event_service.get_event(db, event_id)


@router.patch(
    "/{event_id}",
    response_model=EventResponse,
    summary="Partially update an event",
    responses={
        400: {"model": ErrorResponse, "description": "Seat reduction below sold count"},
        404: {"model": ErrorResponse, "description": "Event not found"},
        409: {"model": ErrorResponse, "description": "New name already taken"},
    },
)
def update_event(event_id: int, data: EventUpdate, db: Session = Depends(get_db)):
    """
    Update one or more fields of an event.
    Only fields included in the request body are modified.
    """
    return event_service.update_event(db, event_id, data)


@router.delete(
    "/{event_id}",
    response_model=MessageResponse,
    summary="Delete an event",
    responses={
        404: {"model": ErrorResponse, "description": "Event not found"},
    },
)
def delete_event(event_id: int, db: Session = Depends(get_db)):
    """Delete an event and all its registrations (cascaded)."""
    return event_service.delete_event(db, event_id)


@router.get(
    "/{event_id}/registrations",
    response_model=list[RegistrationResponse],
    summary="List active registrations for an event",
    responses={
        404: {"model": ErrorResponse, "description": "Event not found"},
    },
)
def get_event_registrations(event_id: int, db: Session = Depends(get_db)):
    """
    Return all **active** registrations for the given event.
    Cancelled registrations are excluded.
    """
    return registration_service.get_event_registrations(db, event_id)