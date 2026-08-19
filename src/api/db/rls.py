"""P204 — the RLS predicate, in Python, so it can be tested without Neon.

[DB-DEP] Migration 0016 puts this on every tenant-scoped table:

    USING (municipality_id = current_setting('app.current_municipality_id', true))

There is no Neon instance locally, so that predicate cannot be executed. This module is
it, transcribed — one function, deliberately tiny, so the transcription is obviously
faithful. It is a *model* of the engine's behaviour, not a second enforcement layer:
nothing in the request path calls it. Its whole job is to make the fail-closed argument
testable now and to fail if someone later changes the migration's predicate without
noticing what it implied.

The argument it encodes, in full:

`missing_ok = true` means an unset GUC yields **NULL** rather than raising. In SQL,
`municipality_id = NULL` is not false — it is NULL, which is not true, so the row is not
returned. Therefore a session that forgot to set its scope reads **zero rows**. The
alternative design (`missing_ok = false`, raising on an unset GUC) would be louder, but
it fails *open* in one specific and catastrophic way: any code path that catches the
error and continues gets an unfiltered read. Zero rows cannot be caught into a leak.

Why keep the quiet layer when P203 already raises loudly? They cover different failures.
P203's exception catches our own bug — a repository that skipped the seam. This catches
everything the seam does not mediate: a psql session, a future service, a migration
script, an ORM someone adds in a year. It is the last thing standing if the loud layer
is bypassed.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

# The column every tenant-scoped table carries, denormalized by 0015 so the predicate
# stays a single indexed equality rather than a join up the ownership chain.
TENANT_COLUMN = "municipality_id"


def visible_rows(
    rows: Sequence[Mapping[str, Any]], scope: str | None
) -> list[Mapping[str, Any]]:
    """Rows visible under 0016's SELECT policy for the given scope.

    `scope` is what `current_setting('app.current_municipality_id', true)` returned:
    None models the GUC being unset. Matching is exact equality — never a prefix or
    pattern match, which would let `MUNI_A` read `MUNI_A2`.
    """
    if not scope:
        # NULL (unset) and '' both match nothing. An empty GUC is not a wildcard.
        return []
    return [r for r in rows if r.get(TENANT_COLUMN) == scope]
