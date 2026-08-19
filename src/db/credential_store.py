"""In-memory device-credential store (P201) — mirrors migration 0017.

There is no Neon instance locally, so this fake stands in for `device_credentials` in
the logic tests, exactly as `FakeTenantStore` does for the ownership chain. It mirrors
the migration's three disciplines rather than merely storing rows:

1. **No plaintext key is ever retained.** `issue()` hashes and discards. A stolen dump
   of this store yields no working credentials — and, importantly, presenting a stored
   *hash* does not authenticate either, or a leak would be a master key.
2. **Revocation is a state change.** There is deliberately no `delete()`. The row
   survives revocation so an auditor can still answer "was this device authorised when
   it sent that reading?"
3. **A credential resolves to exactly one bridge + municipality**, and the tenant is
   derived from the ownership chain — never passed in by a caller who might get it
   wrong. That mirrors the migration's guard trigger by making the inconsistent state
   unrepresentable instead of merely rejected.

The hash is SHA-256 with a per-credential random salt. This is the *fake*, so the choice
that matters here is only that it is one-way and salted; the production hashing decision
(and its cost parameters) belongs to P301 with the real credential path.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from db.tenant_store import FakeTenantStore, UnknownBridgeError

# A device key below this length is guessable, so it is not a credential.
MIN_KEY_LENGTH = 16


class CredentialStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


class DuplicateCredentialError(Exception):
    """The presented key is already issued (mirrors the UNIQUE key_hash constraint)."""


class UnknownCredentialError(Exception):
    """No active or revoked credential matches the presented key."""


class RevokedCredentialError(Exception):
    """The credential exists but has been revoked; it must not authenticate."""


class PlaintextKeyRejected(Exception):
    """The supplied raw key is blank or too short to be a credential."""


@dataclass(frozen=True, slots=True)
class DeviceScope:
    """What a resolved credential grants: exactly one bridge in exactly one tenant."""

    credential_id: int
    bridge_id: str
    municipality_id: str


@dataclass(frozen=True, slots=True)
class CredentialIdentity:
    """The part of a credential row that can never change: who it is and what it opens.

    Frozen and held on a read-only attribute, so rotating a key by assigning over the old
    hash raises rather than succeeding. That is deliberate over a convention: an in-place
    overwrite leaves one row claiming it always held the new key, which makes every reading
    the old key authorised trace to a credential that did not exist at the time. The data
    survives and the audit trail becomes wrong — the failure mode that looks like nothing
    happened (P306, 0018).
    """

    credential_id: int
    key_hash: str
    bridge_id: str
    municipality_id: str
    device_label: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # Kept alongside the hash so a presented key can be re-hashed for comparison. Not
    # secret on its own — a salt's job is to make precomputed tables useless, not to hide.
    # Frozen with the hash: changing the salt invalidates the hash just as effectively.
    salt: str = ""


@dataclass(slots=True)
class DeviceCredential:
    """One row of `device_credentials`. Carries a hash — never the key.

    Split in two: `identity` is frozen (key material, bridge, tenant), while `status`,
    `revoked_at`, and `last_used_at` stay writable — the three updates 0017 permits.
    """

    identity: CredentialIdentity
    status: CredentialStatus = CredentialStatus.ACTIVE
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    @property
    def credential_id(self) -> int:
        return self.identity.credential_id

    @property
    def key_hash(self) -> str:
        return self.identity.key_hash

    @property
    def bridge_id(self) -> str:
        return self.identity.bridge_id

    @property
    def municipality_id(self) -> str:
        return self.identity.municipality_id

    @property
    def device_label(self) -> str:
        return self.identity.device_label

    @property
    def created_at(self) -> datetime:
        return self.identity.created_at

    @property
    def salt(self) -> str:
        return self.identity.salt

    @property
    def is_active(self) -> bool:
        return self.status is CredentialStatus.ACTIVE


def hash_key(raw_key: str, salt: str) -> str:
    """One-way hash of a raw device key. Never reversible, never stored alongside the key."""
    return hashlib.sha256(f"{salt}:{raw_key}".encode()).hexdigest()


class FakeCredentialStore:
    """In-memory `device_credentials`. Not thread-safe; tests are serial."""

    def __init__(self, tenants: FakeTenantStore) -> None:
        self._tenants = tenants
        self._rows: dict[int, DeviceCredential] = {}
        self._next_id = 1

    # --- issuance -----------------------------------------------------------------
    def issue(
        self, bridge_id: str, *, device_label: str, key: str
    ) -> DeviceCredential:
        """Issue a credential for one bridge. The raw key is hashed and discarded here.

        The tenant is derived from the ownership chain, not accepted from the caller —
        so the inconsistent state the migration's guard trigger rejects cannot even be
        constructed. An unknown bridge raises (the hard FK).
        """
        if not key or not key.strip():
            raise PlaintextKeyRejected("a device key must be non-blank")
        if len(key.strip()) < MIN_KEY_LENGTH:
            raise PlaintextKeyRejected(
                f"a device key must be at least {MIN_KEY_LENGTH} characters; "
                "a guessable key is not a credential"
            )
        if not device_label or not device_label.strip():
            raise ValueError("device_label must be non-blank (0017 CHECK)")

        # The hard FK, in-fake: a credential for a non-existent bridge is refused.
        # `municipality_of_bridge` raises a bare KeyError, so translate it to the domain
        # error — a caller catching UnknownBridgeError should not have to also guess KeyError.
        if not self._tenants.has_bridge(bridge_id):
            raise UnknownBridgeError(
                f"cannot issue a credential for unknown bridge {bridge_id!r} "
                "(0017 hard FK bridge_id REFERENCES bridges(id))"
            )
        municipality_id = self._tenants.municipality_of_bridge(bridge_id)

        if self._find_by_key(key) is not None:
            raise DuplicateCredentialError(
                "this key is already issued (0017 UNIQUE key_hash)"
            )

        salt = secrets.token_hex(16)
        row = DeviceCredential(
            identity=CredentialIdentity(
                credential_id=self._next_id,
                key_hash=hash_key(key, salt),
                bridge_id=bridge_id,
                municipality_id=municipality_id,
                device_label=device_label,
                salt=salt,
            )
        )
        self._rows[row.credential_id] = row
        self._next_id += 1
        return row

    def rotate(self, credential_id: int, *, new_key: str) -> DeviceCredential:
        """Issue a replacement credential for the same device. Appends; never overwrites.

        The old row is left ACTIVE on purpose. A Pi is re-flashed by a person standing on a
        bridge, and closing the window here would turn a failed re-flash into a sensor data
        gap. The operator revokes the old credential once the new key is confirmed working
        (plan §2a).

        Refuses a revoked credential: rotating a retired device would resurrect it under a
        new key, which is a provisioning decision, not a rotation.
        """
        current = self.get(credential_id)
        if not current.is_active:
            raise RevokedCredentialError(
                f"credential {credential_id} is revoked; a retired device is re-provisioned "
                "with issue(), not rotated"
            )
        # Goes through issue() so every guard applies — weak key, duplicate hash, the
        # bridge FK. A refusal happens before anything is written, so a rejected rotation
        # leaves the store exactly as it was.
        return self.issue(
            current.bridge_id,
            device_label=current.device_label,
            key=new_key,
        )

    # --- authentication -----------------------------------------------------------
    def resolve(self, key: str) -> DeviceScope:
        """Resolve a presented raw key to its bridge + tenant, stamping last_used_at.

        A revoked credential raises rather than returning a scope — the distinction
        matters, because a revoked key is an *operational* signal (a decommissioned Pi
        still talking) whereas an unknown key may be an attack.
        """
        row = self._find_by_key(key)
        if row is None:
            raise UnknownCredentialError("no credential matches the presented key")
        if not row.is_active:
            raise RevokedCredentialError(
                f"credential {row.credential_id} was revoked at {row.revoked_at}"
            )
        row.last_used_at = datetime.now(UTC)
        return DeviceScope(
            credential_id=row.credential_id,
            bridge_id=row.bridge_id,
            municipality_id=row.municipality_id,
        )

    # --- revocation (never deletion) ----------------------------------------------
    def revoke(self, credential_id: int) -> DeviceCredential:
        """Retire a device. The row is RETAINED — this is a state change, not a delete."""
        row = self.get(credential_id)
        if not row.is_active:
            return row  # idempotent: re-revoking must not move the original timestamp
        row.status = CredentialStatus.REVOKED
        row.revoked_at = datetime.now(UTC)
        return row

    # --- reads --------------------------------------------------------------------
    def get(self, credential_id: int) -> DeviceCredential:
        try:
            return self._rows[credential_id]
        except KeyError:
            raise UnknownCredentialError(
                f"no credential with id {credential_id}"
            ) from None

    def active_for_municipality(self, municipality_id: str) -> tuple[DeviceCredential, ...]:
        """Live credentials for one tenant (mirrors the partial index)."""
        return tuple(
            r for r in self._rows.values()
            if r.municipality_id == municipality_id and r.is_active
        )

    def count(self) -> int:
        """Total rows, including revoked — revocation never reduces this."""
        return len(self._rows)

    # --- internals ----------------------------------------------------------------
    def _find_by_key(self, key: str) -> DeviceCredential | None:
        """Match a presented RAW key against stored hashes.

        Note what this cannot do: a caller presenting a stored `key_hash` finds nothing,
        because the hash is re-derived from the presented value. A database leak is
        therefore not a set of usable credentials.
        """
        for row in self._rows.values():
            if secrets.compare_digest(row.key_hash, hash_key(key, row.salt)):
                return row
        return None
