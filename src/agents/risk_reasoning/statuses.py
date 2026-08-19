"""Closed status vocabulary for the Risk Reasoning Agent (R103/R201).

Mirrors the DCA/SA `statuses.py` style: small closed enums that the output contract, the schema
(R203), and the persistence layer all rely on. `str, Enum` so values round-trip cleanly to/from
the DB enums and JSON.

R103 introduces `Severity` (the FR-4 band); R201 adds `ReviewStatus` (FR-11). Both are closed
sets the output contract, schema (R203), and persistence (R901/R902) rely on.
"""
from __future__ import annotations

from enum import Enum


class Severity(str, Enum):
    """The fixed FR-4 severity band a 0-100 risk score maps to. Closed set, ordered SAFE->CRITICAL."""

    SAFE = "SAFE"
    WATCH = "WATCH"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class ReviewStatus(str, Enum):
    """Whether an assessment is final or held for a human (FR-11).

    `CRITICAL`-band assessments and score-withheld assessments are always PENDING_HUMAN_REVIEW;
    no downstream agent may treat a PENDING_HUMAN_REVIEW verdict as final (mandate #3). The
    clearing of the flag (PENDING_HUMAN_REVIEW -> FINAL) is a separate downstream workflow,
    out of scope for this agent.
    """

    FINAL = "FINAL"
    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"
