"""Structured error envelope (AC-5 / INV-4).

Clients only ever see {error, code, detail, correlation_id} — never a stack trace.
Full exception detail is logged internally against the same correlation_id.

`detail` is the field most likely to leak, because it is where a handler is tempted
to be helpful and the nearest raw material is an exception string full of SQL and
file paths. It is therefore populated only from values that are safe *by
construction* — fixed strings and field NAMES — never from an exception's text and
never from request input.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    error: str = Field(..., description="Human-readable, client-safe message.")
    code: str = Field(..., description="Stable machine-readable error code.")
    detail: str = Field(
        ...,
        description=(
            "Safe-by-construction specifics: which field, which precondition. "
            "Never SQL, paths, library names, row contents, or request input."
        ),
    )
    correlation_id: str = Field(
        ..., description="Trace id; matches the internal log entry for this failure."
    )
