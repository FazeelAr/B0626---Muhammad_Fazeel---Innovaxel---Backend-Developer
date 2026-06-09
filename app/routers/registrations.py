"""
routers/registrations.py — Phase 6b
Endpoints:
  POST   /events/{event_id}/register      → register a user
  DELETE /registrations/{registration_id} → cancel a registration
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    RegistrationCreate, RegistrationResponse,
    MessageResponse, ErrorResponse,
)
from app.services import registration_service

router = APIRouter()


@router.get(
    "/events/{event_id}/registrations",
    response_model=list[RegistrationResponse],
    summary="Get all registrations for an event",
)
def get_registrations(event_id: int, db: Session = Depends(get_db)):
    return registration_service.get_registrations(db, event_id)



@router.post(
    "/events/{event_id}/register",
    response_model=RegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a user for an event",
    responses={
        404: {"model": ErrorResponse, "description": "Event not found"},
        409: {"model": ErrorResponse, "description": "Event full or duplicate registration"},
    },
)
def register_user(
    event_id: int,
    data: RegistrationCreate,
    db: Session = Depends(get_db),
):
    """
    Register a user for an event.

    Rules enforced:
    - Event must exist
    - Event must have at least one available seat
    - Same user cannot register twice for the same event
    - Registration timestamp is recorded automatically
    """
    return registration_service.register_user(db, event_id, data)


@router.delete(
    "/registrations/{registration_id}",
    response_model=MessageResponse,
    summary="Cancel a registration",
    responses={
        400: {"model": ErrorResponse, "description": "Registration already cancelled"},
        404: {"model": ErrorResponse, "description": "Registration not found"},
    },
)
def cancel_registration(registration_id: int, db: Session = Depends(get_db)):
    """
    Cancel an active registration.

    - The freed seat is immediately returned to the event's available pool
    - Cancelled registrations are excluded from all active registration listings
    """
    return registration_service.cancel_registration(db, registration_id)