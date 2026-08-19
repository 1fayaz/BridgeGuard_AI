"""In-memory tenant store (D101+) — mirrors the tenancy-chain schema guarantees for tests.

FakeTenantStore stands in for the Neon-backed tenancy tables (`municipalities` 0012, and later
`bridges` 0013 / `sensors` 0014) until a live instance exists ([DB-DEP]), the same way the DCA/SA/
Risk/Report/Alert fakes mirror their tables. It enforces, in Python, exactly the guarantees the SQL
enforces in the database:

  * a TEXT natural key per municipality; a duplicate id is rejected (the 0012 PRIMARY KEY);
  * a name must be non-blank (the 0012 municipality_name_not_blank CHECK).

Later tasks (D102/D103) extend this fake with bridges + sensors and the hard-FK ownership chain, so
D101 establishes only the municipalities root. Keeping these invariants in the fake means the logic
tests exercise the same rules the live DB will enforce, so nothing is faked away.
"""
from __future__ import annotations

from dataclasses import dataclass


class DuplicateMunicipalityError(Exception):
    """Raised on a second municipality with an existing id — the 0012 TEXT PRIMARY KEY uniqueness."""


class DuplicateBridgeError(Exception):
    """Raised on a second bridge with an existing id — the 0013 TEXT PRIMARY KEY uniqueness."""


class UnknownMunicipalityError(Exception):
    """Raised on a bridge whose municipality does not exist — the 0013 hard FK to municipalities."""


class DuplicateSensorError(Exception):
    """Raised on a second sensor with an existing id — the 0014 TEXT PRIMARY KEY uniqueness."""


class UnknownBridgeError(Exception):
    """Raised on a sensor whose bridge does not exist — the 0014 hard FK to bridges."""


class UnknownSensorError(Exception):
    """Raised when attributing a reading to a sensor that isn't onboarded — the 0015 sensor_id ->
    sensors hard FK (part B). An orphan reading is rejected by the store."""


class ScopeNotSetError(Exception):
    """Raised when a scoped read is attempted with no current municipality set — the in-memory
    analogue of the 0016 RLS fail-closed behaviour (an unset app.current_municipality_id GUC yields
    NULL, so the policy predicate matches nothing). A forgotten scope reads ZERO rows, never all —
    here surfaced as an explicit error so a test can assert the fail-closed contract."""


class CrossTenantWriteError(Exception):
    """Raised when a scoped write tries to stamp a municipality_id other than the current scope — the
    in-memory analogue of the 0016 INSERT policy WITH CHECK. Read scoping stops a tenant SEEING
    another's rows; this stops it CREATING a row attributed to another tenant."""


class TenantConsistencyError(Exception):
    """Raised when a row's denormalized tenant copy disagrees with the ownership chain — mirrors the
    0015 part-B tenant_consistency BEFORE INSERT OR UPDATE trigger. The hard FKs prove each id points
    at a real parent; this proves the copies agree with each other, so a mis-attributed row (correct
    FKs, wrong denormalized municipality/bridge) cannot slip past RLS."""


@dataclass(frozen=True, slots=True)
class Municipality:
    """A persisted municipality: the tenant root row (mirrors the 0012 table)."""

    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Bridge:
    """A persisted bridge: the second ownership-chain link (mirrors the 0013 table)."""

    id: str
    municipality_id: str
    name: str
    location: str | None = None


@dataclass(frozen=True, slots=True)
class Sensor:
    """A persisted sensor: the third ownership-chain link (mirrors the 0014 table)."""

    id: str
    bridge_id: str
    sensor_type: str
    config: dict | None = None


@dataclass(frozen=True, slots=True)
class OwnershipChain:
    """A fully-resolved ownership chain sensor -> bridge -> municipality (spec FR-1/FR-2).

    All three ids are present and non-null; the resolver that builds this raises rather than return
    a partial, so a missing hop can never masquerade as a resolved chain.
    """

    sensor_id: str
    bridge_id: str
    municipality_id: str


class FakeTenantStore:
    """In-memory tenancy store. Not thread-safe; tests are serial."""

    def __init__(self) -> None:
        self._municipalities: dict[str, Municipality] = {}
        self._bridges: dict[str, Bridge] = {}
        self._sensors: dict[str, Sensor] = {}
        self._current_municipality: str | None = None

    # --- RLS scope (0016 SELECT policies, in-memory) ----------------------------
    def set_current_municipality(self, municipality_id: str) -> None:
        """Set the current tenant for scoped reads — the analogue of `SET app.current_municipality_id`
        (plan §2). Rejects an unknown municipality (a caller error, not a silent empty read)."""
        if municipality_id not in self._municipalities:
            raise UnknownMunicipalityError(
                f"cannot scope to unknown municipality {municipality_id!r}"
            )
        self._current_municipality = municipality_id

    def clear_scope(self) -> None:
        """Unset the current tenant — subsequent scoped reads fail closed (RESET of the GUC)."""
        self._current_municipality = None

    @property
    def current_municipality(self) -> str | None:
        """The municipality scoped reads are filtered to, or None when unset."""
        return self._current_municipality

    def _require_scope(self) -> str:
        if self._current_municipality is None:
            raise ScopeNotSetError(
                "no current municipality set: a scoped read is fail-closed (0016 RLS) — "
                "call set_current_municipality(...) first"
            )
        return self._current_municipality

    def scoped_bridges(self) -> tuple[Bridge, ...]:
        """Bridges visible under the current scope — only the current tenant's, mirroring the 0016
        bridges SELECT policy. Fail-closed: ScopeNotSetError when no scope is set."""
        muni = self._require_scope()
        return tuple(b for b in self._bridges.values() if b.municipality_id == muni)

    def scoped_sensors(self) -> tuple[Sensor, ...]:
        """Sensors visible under the current scope — only those whose bridge belongs to the current
        tenant, mirroring the 0016 sensors SELECT policy (keyed on the denormalized municipality_id).
        Fail-closed: ScopeNotSetError when no scope is set."""
        muni = self._require_scope()
        return tuple(
            s for s in self._sensors.values()
            if self._bridges[s.bridge_id].municipality_id == muni
        )

    def check_insert_scope(self, *, municipality_id: str) -> None:
        """Enforce the 0016 INSERT-policy WITH CHECK: a scoped write may only stamp the CURRENT
        tenant's municipality_id. Raises CrossTenantWriteError on a foreign tenant, and (fail-closed)
        ScopeNotSetError when no scope is set — you cannot write unscoped."""
        muni = self._require_scope()
        if municipality_id != muni:
            raise CrossTenantWriteError(
                f"scoped to {muni!r} but the row is attributed to {municipality_id!r} "
                "(0016 INSERT WITH CHECK: a writer may only create rows for its own tenant)"
            )

    # --- municipalities (0012) --------------------------------------------------
    def add_municipality(self, municipality_id: str, *, name: str) -> Municipality:
        """Add a municipality; returns it. Rejects a duplicate id or a blank name."""
        if not municipality_id or not municipality_id.strip():
            raise ValueError("municipality id must be non-blank")
        if not name or not name.strip():
            raise ValueError("municipality name must be non-blank (0012 CHECK)")
        if municipality_id in self._municipalities:
            raise DuplicateMunicipalityError(
                f"municipality already exists: {municipality_id!r}"
            )
        row = Municipality(id=municipality_id, name=name)
        self._municipalities[municipality_id] = row
        return row

    def get_municipality(self, municipality_id: str) -> Municipality:
        """Fetch a municipality by id; raises KeyError if absent."""
        return self._municipalities[municipality_id]

    def has_municipality(self, municipality_id: str) -> bool:
        return municipality_id in self._municipalities

    # --- bridges (0013) ---------------------------------------------------------
    def add_bridge(
        self,
        bridge_id: str,
        *,
        municipality_id: str,
        name: str,
        location: str | None = None,
    ) -> Bridge:
        """Add a bridge under a municipality; returns it.

        Mirrors the 0013 hard FK: a bridge under an unknown municipality is rejected. Also rejects a
        duplicate id (PK) and a blank name (CHECK).
        """
        if not bridge_id or not bridge_id.strip():
            raise ValueError("bridge id must be non-blank")
        if not name or not name.strip():
            raise ValueError("bridge name must be non-blank (0013 CHECK)")
        if municipality_id not in self._municipalities:
            raise UnknownMunicipalityError(
                f"bridge {bridge_id!r} references unknown municipality {municipality_id!r} "
                "(0013 hard FK)"
            )
        if bridge_id in self._bridges:
            raise DuplicateBridgeError(f"bridge already exists: {bridge_id!r}")
        row = Bridge(id=bridge_id, municipality_id=municipality_id, name=name, location=location)
        self._bridges[bridge_id] = row
        return row

    def get_bridge(self, bridge_id: str) -> Bridge:
        """Fetch a bridge by id; raises KeyError if absent."""
        return self._bridges[bridge_id]

    def has_bridge(self, bridge_id: str) -> bool:
        return bridge_id in self._bridges

    def municipality_of_bridge(self, bridge_id: str) -> str:
        """Resolve a bridge to its owning municipality (the bridge -> municipality chain hop)."""
        return self._bridges[bridge_id].municipality_id

    # --- sensors (0014) ---------------------------------------------------------
    def add_sensor(
        self,
        sensor_id: str,
        *,
        bridge_id: str,
        sensor_type: str,
        config: dict | None = None,
    ) -> Sensor:
        """Add a sensor under a bridge; returns it.

        Mirrors the 0014 hard FK: a sensor under an unknown bridge is rejected. Also rejects a
        duplicate id (PK) and a blank sensor_type (CHECK).
        """
        if not sensor_id or not sensor_id.strip():
            raise ValueError("sensor id must be non-blank")
        if not sensor_type or not sensor_type.strip():
            raise ValueError("sensor_type must be non-blank (0014 CHECK)")
        if bridge_id not in self._bridges:
            raise UnknownBridgeError(
                f"sensor {sensor_id!r} references unknown bridge {bridge_id!r} (0014 hard FK)"
            )
        if sensor_id in self._sensors:
            raise DuplicateSensorError(f"sensor already exists: {sensor_id!r}")
        row = Sensor(id=sensor_id, bridge_id=bridge_id, sensor_type=sensor_type, config=config)
        self._sensors[sensor_id] = row
        return row

    def get_sensor(self, sensor_id: str) -> Sensor:
        """Fetch a sensor by id; raises KeyError if absent."""
        return self._sensors[sensor_id]

    def has_sensor(self, sensor_id: str) -> bool:
        return sensor_id in self._sensors

    def bridge_of_sensor(self, sensor_id: str) -> str:
        """Resolve a sensor to its owning bridge (the sensor -> bridge chain hop)."""
        return self._sensors[sensor_id].bridge_id

    def municipality_of_sensor(self, sensor_id: str) -> str:
        """Resolve a sensor to its owning municipality via the full sensor -> bridge -> municipality
        chain (spec FR-2: sensor-keyed data is tenant-attributable)."""
        return self.ownership_chain(sensor_id).municipality_id

    # --- tenant attribution of a sensor-keyed row (0015 part B hard FK) ---------
    def attribute_reading(self, *, sensor_id: str) -> tuple[str, str]:
        """Resolve the (bridge_id, municipality_id) a sensor-keyed row belongs to.

        Mirrors the 0015 sensor_id -> sensors hard FK: a reading whose sensor is not onboarded is
        rejected (UnknownSensorError), so an orphan sensor-keyed row cannot exist. This is the
        attribution a writer performs to populate the denormalized bridge_id / municipality_id.
        """
        if sensor_id not in self._sensors:
            raise UnknownSensorError(
                f"reading references unknown sensor {sensor_id!r} (0015 sensor_id -> sensors FK)"
            )
        chain = self.ownership_chain(sensor_id)
        return chain.bridge_id, chain.municipality_id

    # --- tenant consistency guard (D303, 0015 part B trigger) -------------------
    def check_tenant_consistency(
        self, *, sensor_id: str, bridge_id: str, municipality_id: str
    ) -> None:
        """Verify a sensor-keyed row's denormalized (bridge_id, municipality_id) equal what the
        sensor -> bridge -> municipality chain yields. Raises TenantConsistencyError on drift.

        Mirrors tenant_consistency_sensor_keyed(): both hops must agree — bridge_id equals the
        sensor's bridge, and municipality_id equals that bridge's municipality.
        """
        chain_bridge_id = self._sensors[sensor_id].bridge_id
        if bridge_id != chain_bridge_id:
            raise TenantConsistencyError(
                f"tenant drift: bridge_id {bridge_id!r} does not match sensor {sensor_id!r}'s "
                f"bridge {chain_bridge_id!r}"
            )
        self.check_bridge_tenant_consistency(
            bridge_id=bridge_id, municipality_id=municipality_id
        )

    def check_bridge_tenant_consistency(
        self, *, bridge_id: str, municipality_id: str
    ) -> None:
        """Verify a bridge-keyed (judgment) row's denormalized municipality_id equals the bridge's
        owning municipality. Raises TenantConsistencyError on drift.

        Mirrors tenant_consistency_bridge_keyed().
        """
        chain_municipality_id = self._bridges[bridge_id].municipality_id
        if municipality_id != chain_municipality_id:
            raise TenantConsistencyError(
                f"tenant drift: municipality_id {municipality_id!r} does not match bridge "
                f"{bridge_id!r}'s municipality {chain_municipality_id!r}"
            )

    # --- ownership chain (D104) -------------------------------------------------
    def ownership_chain(self, sensor_id: str) -> OwnershipChain:
        """Resolve the full sensor -> bridge -> municipality chain for a sensor (spec FR-1/FR-2).

        Raises KeyError if the sensor, its bridge, or that bridge's municipality is absent — never
        returns a partial chain, so a missing hop cannot be mistaken for a resolved one. In the live
        DB the 0013/0014 hard FKs make a missing hop structurally impossible; the raise mirrors that
        invariant for the in-memory fake.
        """
        sensor = self._sensors[sensor_id]                      # missing sensor -> KeyError
        bridge = self._bridges[sensor.bridge_id]               # 0014 FK guarantees this exists live
        municipality = self._municipalities[bridge.municipality_id]  # 0013 FK guarantees this
        return OwnershipChain(
            sensor_id=sensor.id,
            bridge_id=bridge.id,
            municipality_id=municipality.id,
        )
