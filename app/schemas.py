"""
schemas.py — Phase 3
Responsibilities:
  1. EventCreate     — validate incoming data when creating an event
  2. EventResponse   — shape of data returned for any event query
  3. RegistrationCreate  — validate incoming data when registering a user
  4. RegistrationResponse — shape of data returned for any registration query

Pydantic v2 is used throughout. Key behaviours:
  - Field validators run BEFORE the object is constructed
  - model_config = ConfigDict(from_attributes=True) lets us pass SQLAlchemy
    ORM objects directly to the schema (no manual dict conversion needed)
  - All validation errors are automatically returned as structured JSON by
    FastAPI — no extra error handling needed in the routes for input errors
"""

from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _strip_tz(dt: datetime) -> datetime:
    """
    SQLite stores datetimes without timezone info. When comparing dates that
    came from the DB (naive) with user-supplied dates (aware), we normalise
    both to naive UTC to avoid TypeError on comparison.
    """
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


# ══════════════════════════════════════════════════════════════════════════════
# EVENT SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class EventCreate(BaseModel):
    """
    Validated input for POST /events.
    All three fields are required — no defaults.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Unique name for the event",
        examples=["Tech Summit 2026"],
    )

    total_seats: int = Field(
        ...,
        gt=0,
        description="Total capacity — must be greater than 0",
        examples=[100],
    )

    event_date: datetime = Field(
        ...,
        description="Event date and time in ISO 8601 format — must be in the future",
        examples=["2026-12-01T18:00:00Z"],
    )

    # ── Field validators ──────────────────────────────────────────────────────

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Event name cannot be blank or whitespace only")
        return stripped  # return the cleaned version

    @field_validator("event_date")
    @classmethod
    def event_date_must_be_future(cls, v: datetime) -> datetime:
        now_naive = _utcnow().replace(tzinfo=None)
        v_naive   = _strip_tz(v)
        if v_naive <= now_naive:
            raise ValueError(
                "event_date must be in the future. "
                f"Received: {v.isoformat()}, "
                f"Current UTC: {_utcnow().isoformat()}"
            )
        return v


class EventUpdate(BaseModel):
    """
    Optional-field input for PATCH /events/{id} (bonus endpoint).
    Only fields explicitly provided are updated — others remain unchanged.
    Uses None as the sentinel for "not provided".
    """

    name: str | None = Field(None, min_length=1, max_length=255)
    total_seats: int | None = Field(None, gt=0)
    event_date: datetime | None = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip()
            if not stripped:
                raise ValueError("Event name cannot be blank")
            return stripped
        return v

    @field_validator("event_date")
    @classmethod
    def date_must_be_future(cls, v: datetime | None) -> datetime | None:
        if v is not None:
            now_naive = _utcnow().replace(tzinfo=None)
            if _strip_tz(v) <= now_naive:
                raise ValueError("event_date must be in the future")
        return v


class EventResponse(BaseModel):
    """
    Shape of every event object returned by the API.
    'total_registrations' is a computed property on the ORM model —
    Pydantic reads it transparently because from_attributes=True.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    total_seats: int
    available_seats: int
    total_registrations: int   # ORM @property: total_seats - available_seats
    event_date: datetime
    created_at: datetime


# ══════════════════════════════════════════════════════════════════════════════
# REGISTRATION SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class RegistrationCreate(BaseModel):
    """
    Validated input for POST /events/{event_id}/register.
    Only the user's name is needed — event_id comes from the URL path.
    """

    user_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Name of the user registering for the event",
        examples=["Ali Hassan"],
    )

    @field_validator("user_name")
    @classmethod
    def user_name_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("user_name cannot be blank or whitespace only")
        return stripped


class RegistrationResponse(BaseModel):
    """
    Shape of every registration object returned by the API.
    'status' is typed as a Literal so OpenAPI docs show the exact valid values.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: int
    user_name: str
    status: Literal["active", "cancelled"]
    registered_at: datetime
    cancelled_at: datetime | None = None


# ══════════════════════════════════════════════════════════════════════════════
# GENERIC RESPONSE SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class MessageResponse(BaseModel):
    """
    Simple success response for operations that don't return an object.
    Used by the cancel registration endpoint.
    Example: {"message": "Registration cancelled successfully"}
    """
    message: str


class ErrorResponse(BaseModel):
    """
    Consistent error shape for all 4xx/5xx responses.
    'error'   — machine-readable error code (e.g. "EVENT_FULL")
    'message' — human-readable explanation
    FastAPI uses this as the response_model for error documentation in Swagger.
    """
    error: str
    message: str