"""P502 — the response base that will not let an absence become a missing key.

A `None` that is correct in the model and gone from the body is not a smaller bug than a
fabricated zero; it is the same bug, reached later. A dashboard that receives no `risk_score` key
reads `undefined` and renders its fallback — a dash, a zero, a green tile — and the value that
reaches a human's eye was decided by frontend defaulting rather than by anything that was assessed.

pydantic offers exactly one switch that does this (`exclude_none=True`), and it is attractive for
ordinary reasons: smaller payloads, tidier bodies. Everywhere else in an API it is a fine idea.
Here it silently deletes the distinction between "no score" and "score not mentioned", so the
models that carry a verdict opt out of it permanently.

**The override is deliberately quiet rather than loud.** Raising on `exclude_none=True` would turn
a tidy-payload change into a 500 at request time, in production, on the safety-critical path. Being
honest instead — serving the nulls regardless of what was asked — fails towards the response that
is true. The pressure to notice therefore lives in review, not at runtime: nothing under `src/api/`
sets the flag, and a test enforces that.

This also covers FastAPI's `response_model_exclude_none=True`, which routes through `model_dump`
on the outermost model. pydantic serializes a whole tree in one pass from that outer call, so
forcing the flag there settles it for every nested verdict too.

Ties to tasks.md P502, spec AC-8, INV-6.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class NullHonestModel(BaseModel):
    """A response model whose nulls are part of the answer.

    Frozen and `extra="forbid"` by inheritance: a projection a caller can edit after the fact is
    not a projection of anything, and a field nobody declared is a field nobody audited.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        return super().model_dump(**{**kwargs, "exclude_none": False})

    def model_dump_json(self, **kwargs: Any) -> str:
        return super().model_dump_json(**{**kwargs, "exclude_none": False})
