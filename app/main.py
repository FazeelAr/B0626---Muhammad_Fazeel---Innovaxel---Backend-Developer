"""
main.py — Phase 7
Responsibilities:
  1. Create the FastAPI application instance
  2. Register global exception handlers for consistent error responses
  3. Mount both routers with their URL prefixes
  4. Create all DB tables on startup via lifespan
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.database import engine, Base
from app.routers.events import router as events_router
from app.routers.registrations import router as registrations_router


# ─── Lifespan ─────────────────────────────────────────────────────────────────
# asynccontextmanager turns this into a startup/shutdown handler.
# Everything before `yield` runs on startup; after `yield` on shutdown.
# Base.metadata.create_all() issues CREATE TABLE IF NOT EXISTS for every
# model that inherits from Base — idempotent, safe to run on every startup.
@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


# ─── Application ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="Event Registration API",
    description=(
        "A simple event registration system with seat management, "
        "duplicate prevention, and race condition protection."
    ),
    version="1.0.0",
    lifespan=lifespan,
    # Swagger UI lives at /docs, ReDoc at /redoc
)


# ─── Global Exception Handlers ────────────────────────────────────────────────
# FastAPI raises RequestValidationError when a request body or query param
# fails Pydantic validation. The default error shape is verbose and nested.
# We reformat it into our standard {error, message} shape for consistency.
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Collect all validation errors into one readable message
    errors = exc.errors()
    messages = []
    for err in errors:
        field = " → ".join(str(loc) for loc in err["loc"] if loc != "body")
        messages.append(f"{field}: {err['msg']}" if field else err["msg"])

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "VALIDATION_ERROR",
            "message": "; ".join(messages),
        },
    )


# HTTPException raised in services carries detail as a dict {error, message}.
# FastAPI's default handler wraps it as {"detail": {...}} — we unwrap it so
# every error response has the same top-level {error, message} shape.
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        content = detail  # already {error, message}
    else:
        content = {"error": "HTTP_ERROR", "message": str(detail)}
    return JSONResponse(status_code=exc.status_code, content=content)


# Catch any unhandled IntegrityError that bubbles up from the DB layer
# (e.g. a unique constraint violation that slipped past service-level checks)
@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": "INTEGRITY_ERROR",
            "message": "A database constraint was violated. The resource may already exist.",
        },
    )


# ─── Routers ──────────────────────────────────────────────────────────────────
app.include_router(
    events_router,
    prefix="/events",
    tags=["Events"],
)

app.include_router(
    registrations_router,
    tags=["Registrations"],
)


# ─── Root health-check endpoint ───────────────────────────────────────────────
@app.get("/", tags=["Health"], summary="Health check")
def root():
    """Confirm the API is running."""
    return {"status": "ok", "message": "Event Registration API is running"}