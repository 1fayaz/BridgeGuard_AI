"""P303 — resolve a Pi's API key to exactly one bridge and one tenant.

[DB-DEP] Runs against `FakeCredentialStore` locally; the real path reads
`device_credentials` (migration 0017).

**This is the layer's one pre-scope database read**, and the inversion is deliberate
rather than an oversight: authenticating a Pi requires looking up a key hash *before* any
tenant scope exists, because that lookup is what determines the scope. 0017's header
documents the narrowly-privileged path this uses in production — it may read only
`(key_hash, bridge_id, municipality_id, status)` and can write nothing. Every query after
resolution runs inside a normal scoped transaction.

What this module is careful about, and why:

**The raw key never appears in a message, an exception, or a log.** A field-installed
Raspberry Pi is simultaneously the credential most likely to be physically extracted and
the one most likely to be pasted into a debug log during a 3am outage. So no error text
interpolates the presented value — not even a prefix of it, since a prefix plus a known
key format narrows a brute force considerably.

**Comparison is by stored salted hash, never plaintext.** And presenting the *stored
hash* resolves nothing, because the store re-derives the hash from whatever was
presented. A database dump is therefore not a set of usable credentials.

**Revoked and unknown are the same 401 to the client, different classes in the log.**
They mean genuinely different things operationally: a revoked key still arriving is a
decommissioned Pi nobody unplugged, while an unknown key may be an attack. An operator
needs that distinction; a caller must not have it, because "this key was once valid" is
information.
"""
from __future__ import annotations

from typing import Final

from api.auth.principal import CredentialClass, Principal, resolve_principal
from api.status_policy import ApiError, Failure
from db.credential_store import (
    MIN_KEY_LENGTH,
    FakeCredentialStore,
    RevokedCredentialError,
    UnknownCredentialError,
)

_API_KEY_PREFIX: Final = "apikey"

# One message for every rejection. Identical for revoked, unknown, and malformed — the
# client must not learn that a key was ever issued.
_GENERIC_DETAIL: Final = (
    "The supplied device credential is not valid. Contact the operator who provisioned "
    "this gateway."
)


class DeviceKeyResolver:
    """Turns a presented device key into a bridge-pinned `Principal`."""

    __slots__ = ("_store",)

    def __init__(self, store: FakeCredentialStore) -> None:
        self._store = store

    def __repr__(self) -> str:
        # No key material, no store contents — this can land in a log line.
        return f"DeviceKeyResolver(store={type(self._store).__name__})"

    def resolve(self, credential: str | None) -> Principal:
        key = self._strip_prefix(credential)

        if len(key) < MIN_KEY_LENGTH:
            # Reject before touching the store: a guessable key is not a credential, and
            # this keeps trivially-malformed input off the lookup path entirely.
            raise ApiError(Failure.INVALID_CREDENTIAL, _GENERIC_DETAIL)

        try:
            scope = self._store.resolve(key)
        except RevokedCredentialError:
            # EXPIRED_CREDENTIAL is also 401. The class is what reaches the log.
            raise ApiError(Failure.EXPIRED_CREDENTIAL, _GENERIC_DETAIL) from None
        except UnknownCredentialError:
            raise ApiError(Failure.INVALID_CREDENTIAL, _GENERIC_DETAIL) from None

        return resolve_principal(
            CredentialClass.DEVICE_KEY,
            municipality_ids=[scope.municipality_id],
            bridge_id=scope.bridge_id,
        )

    @staticmethod
    def _strip_prefix(credential: str | None) -> str:
        if not credential or not credential.strip():
            raise ApiError(Failure.MISSING_CREDENTIAL)
        value = credential.strip()
        if value.lower().startswith(_API_KEY_PREFIX):
            value = value[len(_API_KEY_PREFIX):].strip()
        if not value:
            raise ApiError(Failure.MISSING_CREDENTIAL)
        return value
