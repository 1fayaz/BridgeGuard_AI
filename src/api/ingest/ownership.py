"""P404 — is this sensor on the bridge the credential opened?

The question this module is allowed to ask is narrow on purpose: *is this sensor on my bridge?*
It is specifically **not** allowed to ask *whose sensor is this?* — because the moment the
ingest path can resolve a sensor to its own tenant, re-attributing a stray reading to that
tenant is one obliging-looking line away.

Which would be the worst outcome available. The credential is the only statement of tenancy we
have (INV-3: a supplied id is never a grant), so a gateway that can name a sensor id would
become a write path into whatever tenant owns it. Worse, the resulting row would be
indistinguishable from a real reading — correctly attributed, internally consistent, with no
alarm and no way back. A refused reading is a support ticket; a re-attributed one is corrupted
evidence in another municipality's record.

The three reasons are distinct because they require three different human actions, and the
order between them matters. Existence is checked first, then bridge, then unit — each answer
is only meaningful once the previous one holds. Telling a gateway "unit mismatch" for a sensor
nobody has provisioned would send an operator to edit a config file for equipment that does
not exist.

Reporting stops at the first objection for a second reason too: a rejection must not become a
tenancy oracle. Confirming the registered unit of a sensor on someone else's bridge answers a
question the caller has no standing to ask, so a foreign sensor gets exactly one answer —
"not on this bridge" — whoever owns it and whatever unit it uses.

Unit is per-sensor config (0014 `config` JSONB) and is compared case-insensitively after
stripping, because `"MicroStrain\\n"` from a gateway's string formatting is a formatting
difference, not a wrong unit. An unset registered unit accepts anything: sensors onboarded
before the field was populated must not have their readings refused.

[DB-DEP] The roster is the in-memory FakeTenantStore here. Live, the same guarantees come from
the 0014/0015 hard FKs plus the 0016 RLS policies — this check is the boundary's early, explicit
refusal, not the only line of defence.

Ties to tasks.md P404, spec AC-1 + AC-2 + §1, plan §4.
"""
from __future__ import annotations

from typing import Any, Final

from api.ingest.reasons import RejectionReason

_UNIT_KEY: Final = "unit"


class SensorRegistry:
    """Read-only view of the sensor roster: existence, bridge, registered unit.

    Deliberately narrow. There is no provisioning method — onboarding a sensor is an operator
    action elsewhere, and a write path here would let a gateway create the sensor whose absence
    it was just told about.
    """

    __slots__ = ("_store",)

    def __init__(self, store: Any) -> None:
        self._store = store

    def exists(self, sensor_id: str) -> bool:
        try:
            return bool(self._store.has_sensor(sensor_id))
        except Exception:
            return False

    def is_on_bridge(self, sensor_id: str, bridge_id: str) -> bool:
        """True only if the sensor's bridge is exactly the one the credential opened.

        Any failure to establish that answers False. Fail closed: an unresolvable roster must
        not admit a reading, and it must not raise either (that would cost the batch, P403).
        """
        if not bridge_id or not bridge_id.strip():
            return False
        try:
            return self._store.bridge_of_sensor(sensor_id) == bridge_id
        except Exception:
            return False

    def registered_unit(self, sensor_id: str) -> str | None:
        """The unit this sensor is configured to report in, or None if unset."""
        try:
            config = self._store.get_sensor(sensor_id).config or {}
            unit = config.get(_UNIT_KEY)
        except Exception:
            return None
        if not isinstance(unit, str) or not unit.strip():
            return None
        return unit


def check_ownership(
    sensor_id: Any,
    unit: Any,
    registry: SensorRegistry,
    *,
    bridge_id: str,
) -> RejectionReason | None:
    """The ownership objection to one reading, or None. Never raises.

    Stops at the first objection — see the module docstring on why that is a disclosure rule,
    not just brevity.
    """
    if not isinstance(sensor_id, str) or not sensor_id.strip():
        return RejectionReason.UNKNOWN_SENSOR
    resolved = sensor_id.strip()

    if not registry.exists(resolved):
        return RejectionReason.UNKNOWN_SENSOR
    if not registry.is_on_bridge(resolved, bridge_id):
        return RejectionReason.SENSOR_NOT_ON_THIS_BRIDGE

    expected = registry.registered_unit(resolved)
    if expected is None:
        return None
    if not _units_agree(unit, expected):
        return RejectionReason.UNIT_MISMATCH
    return None


def _units_agree(presented: Any, expected: str) -> bool:
    if not isinstance(presented, str):
        return False
    return presented.strip().casefold() == expected.strip().casefold()
