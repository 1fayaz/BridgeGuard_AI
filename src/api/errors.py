"""Global exception handling (AC-5, INV-4 — no silent/leaky failures).

Every error leaving the API is the structured ErrorResponse envelope. Unhandled
exceptions are logged in full internally with a correlation_id and returned to the
client as a generic 500 carrying only that id — never a stack trace.

**Field semantics (P101 Finding 2, resolved):** `error` is the client-safe message,
`code` is the stable machine-readable code. The spec text was corrected to match this
built shape — an HTTP status is already present in the status line, so `code` is
better spent on a code a client can branch on.

**`detail` is safe by construction.** It is built from fixed strings and, for
validation failures, from *field names only* — never from an exception's text, never
from submitted values. Echoing input back is how an injected payload reaches a log
viewer or a browser, so 422 reports which field failed and what kind of failure it
was, not what was sent.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .schemas.errors import ErrorResponse
from .status_policy import ApiError, Failure

logger = logging.getLogger("bridgeguard.api")

# Shown to the client when something unexpected breaks. Deliberately says nothing.
_OPAQUE_INTERNAL_DETAIL = (
    "The request could not be completed. Quote the correlation_id when reporting this."
)


def _new_correlation_id() -> str:
    return uuid.uuid4().hex


def _envelope(
    status_code: int,
    error: str,
    code: str,
    detail: str,
    correlation_id: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=error, code=code, detail=detail, correlation_id=correlation_id
    )
    return JSONResponse(
        status_code=status_code, content=body.model_dump(), headers=headers
    )


def _safe_field_path(loc: tuple[object, ...]) -> str:
    """Render a pydantic error location as a dotted field path.

    Only structural parts are kept: names and indices. The `body`/`query` prefixes are
    dropped as noise, and nothing from the submitted value is included.
    """
    parts = [str(p) for p in loc if str(p) not in ("body", "query", "path", "header")]
    return ".".join(parts) or "request"


def _validation_detail(exc: RequestValidationError) -> str:
    """Name the offending fields and the failure kind — never the sent values.

    pydantic's own messages are usually safe but can embed input, so we use only
    `loc` (field path) and `type` (a stable machine token like `float_parsing`).
    """
    seen: list[str] = []
    for err in exc.errors():
        field = _safe_field_path(tuple(err.get("loc", ())))
        kind = str(err.get("type", "invalid"))
        entry = f"{field} ({kind})"
        if entry not in seen:
            seen.append(entry)
    if not seen:
        return "One or more fields are missing or malformed."
    # Bounded: a huge payload must not produce a huge error body.
    shown = seen[:10]
    suffix = f" and {len(seen) - len(shown)} more" if len(seen) > len(shown) else ""
    return "Invalid or missing fields: " + ", ".join(shown) + suffix + "."


async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
    """The declared-failure path: status comes from the policy table, never the handler."""
    correlation_id = _new_correlation_id()
    # Log the failure class and the real path. For a cross-tenant refusal this is the
    # ONLY place the distinction from a genuine miss survives — the client cannot see it.
    logger.info(
        "api_error failure=%s status=%s path=%s correlation_id=%s",
        exc.failure.value, exc.status_code, request.url.path, correlation_id,
    )
    headers = None
    if exc.failure is Failure.RATE_LIMITED:
        # Spec §Rate limiting: 429 always tells the caller when to come back, so a
        # backing-off Pi does not have to guess and hammer.
        headers = {"Retry-After": str(exc.retry_after or 60)}
    return _envelope(
        status_code=exc.status_code,
        error=exc.error,
        code=exc.code,
        detail=exc.detail,
        correlation_id=correlation_id,
        headers=headers,
    )


async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    correlation_id = _new_correlation_id()
    logger.info(
        "http_exception status=%s path=%s correlation_id=%s detail=%s",
        exc.status_code, request.url.path, correlation_id, exc.detail,
    )
    # A raised HTTPException's detail is author-written (not exception text), so it
    # doubles as both the message and the specific reason for this status.
    message = str(exc.detail)
    return _envelope(
        status_code=exc.status_code,
        error=message,
        code=f"http_{exc.status_code}",
        detail=message,
        correlation_id=correlation_id,
    )


async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    correlation_id = _new_correlation_id()
    logger.info(
        "validation_error path=%s correlation_id=%s errors=%s",
        request.url.path, correlation_id, exc.errors(),
    )
    return _envelope(
        status_code=422,
        error="Request validation failed.",
        code="validation_error",
        detail=_validation_detail(exc),
        correlation_id=correlation_id,
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    correlation_id = _new_correlation_id()
    # Full detail (incl. traceback) goes to logs ONLY, never to the client.
    logger.exception(
        "unhandled_exception path=%s correlation_id=%s", request.url.path, correlation_id
    )
    return _envelope(
        status_code=500,
        error="An internal error occurred.",
        code="internal_error",
        detail=_OPAQUE_INTERNAL_DETAIL,
        correlation_id=correlation_id,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, handle_api_error)
    app.add_exception_handler(HTTPException, handle_http_exception)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
