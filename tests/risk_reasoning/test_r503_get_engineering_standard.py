"""R503 — get_engineering_standard(bridge_type, source) read-only tool (FR-3 tool 3, FR-10).

[DB-DEP] The live standards source (curated store vs. live retrieval — an Open Item) does not
exist yet, so the read runs against an in-memory fake. The tool's contract IS verifiable now:
known type -> limits + standard_code + standard_version (pinned for provenance); unknown/ambiguous
type -> structured "standard unavailable" signal (drives the FR-6 degraded path), NEVER a guessed
limit; performs NO mutation.

FR-10: the standard's value + version must be captured at decision time so an assessment stays
reproducible after the standard is later revised.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agents.risk_reasoning.tools.engineering_standard import (
    get_engineering_standard,
    StandardEntry,
)


@dataclass
class FakeStandardSource:
    entries: dict[str, StandardEntry] = field(default_factory=dict)
    read_calls: int = 0
    mutated: bool = False

    def standard_for(self, bridge_type: str) -> StandardEntry | None:
        self.read_calls += 1
        return self.entries.get(bridge_type)


def _entry() -> StandardEntry:
    return StandardEntry(
        standard_code="IRC:6",
        standard_version="2017",
        limits={"deflection_ratio": 1.0 / 800.0, "max_strain": 500.0},
    )


def test_known_type_returns_limits_with_pinned_code_and_version():
    src = FakeStandardSource(entries={"girder": _entry()})
    out = get_engineering_standard("girder", src)
    assert out.available is True
    assert out.standard_code == "IRC:6"
    assert out.standard_version == "2017"        # pinned for provenance (FR-10)
    assert out.limits["max_strain"] == 500.0


def test_unknown_type_is_unavailable_signal_never_a_guess():
    src = FakeStandardSource(entries={"girder": _entry()})
    out = get_engineering_standard("cable_stayed", src)
    assert out.available is False
    assert out.limits == {}                      # no fabricated limit
    assert out.standard_code is None
    assert out.reason                            # names the gap (drives FR-6 degraded path)


def test_unavailable_carries_no_version_to_pin():
    src = FakeStandardSource(entries={})
    out = get_engineering_standard("girder", src)
    assert out.available is False
    assert out.standard_version is None


def test_read_only_does_not_mutate_source():
    src = FakeStandardSource(entries={"girder": _entry()})
    get_engineering_standard("girder", src)
    assert src.mutated is False
    assert set(src.entries) == {"girder"}


def test_limits_are_returned_as_read_no_recompute():
    # The agent consumes the standard's published limits verbatim; it does not derive them.
    src = FakeStandardSource(entries={"girder": _entry()})
    out = get_engineering_standard("girder", src)
    assert out.limits["deflection_ratio"] == 1.0 / 800.0
