"""Tool 3 — get_engineering_standard (R503, FR-3 tool 3, FR-10) — read-only.

Looks up the applicable engineering standard's design limits for a bridge type (IRC / AASHTO /
Eurocode, per the `structural-research` skill) and returns them WITH the standard's code + version,
captured so an assessment that used them stays reproducible after the standard is later revised
(FR-10). Read-only; it consumes published limits verbatim and never derives or guesses one.

When no standard is available or the bridge type is ambiguous, it returns a structured "standard
unavailable" signal — NEVER a fabricated limit. That signal drives the FR-6 degraded path (the
comparison could not be made; the explanation says so).

[DB-DEP] / Open Item: whether the source is a curated local store or live retrieval is a plan.md
decision. The read is written against a source PROTOCOL and runs against an in-memory fake now.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StandardEntry:
    """One standard's published limits + its pinned identity (as the source stores it)."""

    standard_code: str
    standard_version: str
    limits: dict[str, float]


class StandardSource(Protocol):
    """The read port this tool needs — returns the entry for a bridge type, or None if absent."""

    def standard_for(self, bridge_type: str) -> StandardEntry | None:
        ...


@dataclass(frozen=True, slots=True)
class EngineeringStandard:
    """The tool's structured return.

    When `available`, `limits` + `standard_code` + `standard_version` are populated (the latter two
    pinned for provenance, FR-10). When not available, `limits` is empty, code/version are None,
    and `reason` names the gap — never a guessed limit.
    """

    available: bool
    limits: dict[str, float]
    standard_code: str | None
    standard_version: str | None
    reason: str | None = None


def get_engineering_standard(
    bridge_type: str,
    source: StandardSource,
) -> EngineeringStandard:
    """Look up the applicable standard for a bridge type (FR-3 tool 3, FR-10). Read-only; no guess."""
    entry = source.standard_for(bridge_type)
    if entry is None:
        return EngineeringStandard(
            available=False,
            limits={},
            standard_code=None,
            standard_version=None,
            reason=f"no applicable engineering standard for bridge type {bridge_type!r}",
        )
    return EngineeringStandard(
        available=True,
        limits=dict(entry.limits),
        standard_code=entry.standard_code,
        standard_version=entry.standard_version,
    )
