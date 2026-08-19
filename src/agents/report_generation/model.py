"""The assembled report model (G401) — the pre-render document, provenance-carrying.

A ReportModel is what the assembler (G402) builds and the renderer (G603) draws. Its defining
property: every value the document will PRINT is held in a `Slot` that records BOTH the value AND
the `source_ref` it was copied from. This is what makes the report auditable:

  * the fidelity gate (G501) walks every slot and verifies its value traces to a finalized source
    row (FR-5) — a value with no matching source is never published;
  * because a slot holds a COPY plus its origin, nothing in the document is ever recomputed or
    reworded (FR-1) — the model only carries what upstream already finalized.

A `ReportSection` that has no upstream content is present-but-empty and marked `available=False`
(FR-6) — never silently omitted and never faked. The coherence rules (available⇔has-slots) are
enforced at construction so an incoherent model cannot exist as an object.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator


@dataclass(frozen=True, slots=True)
class Slot:
    """One printable value + the source reference it was copied from.

    `source_ref` is an opaque provenance key (e.g. "risk_assessments:1001:risk_score") tying the
    value back to the finalized row/field it came from. It is REQUIRED and non-empty: a printed
    value without provenance is exactly what FR-5 forbids.
    """

    value: Any
    source_ref: str

    def __post_init__(self) -> None:
        if not self.source_ref or not str(self.source_ref).strip():
            raise ValueError(
                "Slot.source_ref is required (FR-5: a printed value must trace to a source)"
            )


@dataclass(frozen=True, slots=True)
class ReportSection:
    """One section of the document: a name, an availability flag, and its printable slots.

    available=True is a claim the section HAS upstream content, so it must carry ≥1 slot.
    available=False means no upstream content (FR-6) — the section is rendered as a marked
    "data unavailable" block and must carry no slots.
    """

    name: str
    available: bool
    slots: tuple[Slot, ...]

    def __post_init__(self) -> None:
        if self.available and not self.slots:
            raise ValueError(
                f"section {self.name!r} is available=True but has no slots "
                "(an available section must carry content)"
            )
        if not self.available and self.slots:
            raise ValueError(
                f"section {self.name!r} is available=False but carries slots "
                "(an unavailable section must be empty)"
            )


@dataclass(frozen=True, slots=True)
class ReportModel:
    """The assembled, pre-render document model. Built by G402; drawn by G603; checked by G501."""

    bridge_id: str
    assessment_id: int
    assessment_version: int
    severity: str | None                # the band, or None when the assessment withheld its score
    rendered_at: str                    # timestamp seam (passed in; no clock in the assembler)
    sections: tuple[ReportSection, ...]

    def section(self, name: str) -> ReportSection:
        """Return the section by name, or raise KeyError if there is no such section."""
        for sec in self.sections:
            if sec.name == name:
                return sec
        raise KeyError(name)

    def all_slots(self) -> Iterator[Slot]:
        """Yield every printable slot across every AVAILABLE section (the fidelity-gate walk).

        Unavailable sections contribute nothing — they print a "data unavailable" block, not a
        value, so there is nothing to fidelity-check.
        """
        for sec in self.sections:
            if sec.available:
                yield from sec.slots
