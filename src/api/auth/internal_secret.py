"""P305 — the n8n shared secret, and the network restriction that backs it up.

Plan §7: *a leaked shared secret must not be sufficient to trigger the pipeline from
outside.* Hence two independent factors, each load-bearing on its own.

Why this credential specifically needs a second factor: unlike a JWT it never expires,
unlike a device key it is not bound to one bridge, and it lives in an n8n workflow
configuration — a thing that gets exported, copied between environments, and pasted into
support threads. It is the credential in this system most likely to leak *without anyone
knowing it leaked*. The origin check turns that from a pipeline compromise into a failed
request from an unexpected address.

Three details that are not incidental:

**`secrets.compare_digest`, not `==`.** A byte-by-byte comparison returns sooner on an
early mismatch. Trigger endpoints are remotely reachable and deliberately retry-friendly
(n8n redelivers), so there is no rate limit to blunt a timing attack against a fixed,
non-expiring secret.

**Both failure modes produce one identical 403.** If "right secret, wrong network" looked
different from "wrong secret", a caller would learn they hold a valid credential and need
only find an allowed address.

**Misconfiguration fails closed at construction.** An empty allow-list permits nothing
(not everything), a wildcard CIDR is refused outright, and a blank secret is refused —
because `compare_digest("", "")` is true, and an unset secret would otherwise make the
whole check trivially satisfiable.
"""
from __future__ import annotations

import ipaddress
import secrets
from typing import Final, Sequence

from api.auth.principal import CredentialClass, Principal, resolve_principal
from api.status_policy import ApiError, Failure

# Long enough that a leak is the realistic threat, not a guess.
MIN_SECRET_LENGTH: Final = 32

_WILDCARDS: Final = frozenset({"*", "0.0.0.0/0", "::/0"})

# One message for both factors. See the module docstring.
_GENERIC_DETAIL: Final = (
    "This endpoint is restricted to internal callers."
)


class InternalSecretVerifier:
    """Verifies the n8n shared secret and the caller's address, together."""

    __slots__ = ("_secret", "_networks")

    def __init__(
        self, *, secret: str | None, allowed_origins: Sequence[str]
    ) -> None:
        if not secret or not secret.strip():
            raise ValueError(
                "the internal trigger secret is unset; compare_digest against an empty "
                "value would accept an empty presented secret"
            )
        if len(secret.strip()) < MIN_SECRET_LENGTH:
            raise ValueError(
                f"the internal trigger secret must be at least {MIN_SECRET_LENGTH} "
                "characters"
            )

        networks = []
        for origin in allowed_origins:
            cleaned = origin.strip()
            if cleaned in _WILDCARDS:
                raise ValueError(
                    f"{origin!r} allows every address, which removes the second factor "
                    "entirely; list the actual n8n hosts or subnets"
                )
            try:
                # strict=False so a host address with a prefix is accepted as written.
                networks.append(ipaddress.ip_network(cleaned, strict=False))
            except ValueError:
                raise ValueError(
                    f"{origin!r} is not a valid IP address or CIDR range"
                ) from None

        self._secret = secret.strip()
        self._networks = tuple(networks)

    def __repr__(self) -> str:
        # Neither the secret nor the network map belongs in an incidental log line.
        return (
            f"InternalSecretVerifier(secret=<redacted>, "
            f"allowed=<{len(self._networks)} redacted>)"
        )

    def verify(
        self, presented: str | None, *, origin: str | None, municipality_id: str
    ) -> Principal:
        """Check both factors, then resolve the trigger's scope key to a Principal."""
        secret_ok = self._secret_matches(presented)
        origin_ok = self._origin_allowed(origin)

        # Evaluated separately, reported together: the caller cannot tell which failed.
        if not (secret_ok and origin_ok):
            raise ApiError(Failure.WRONG_CREDENTIAL_CLASS, _GENERIC_DETAIL)

        return resolve_principal(
            CredentialClass.INTERNAL_SECRET, municipality_ids=[municipality_id]
        )

    # --- factors --------------------------------------------------------------------
    def _secret_matches(self, presented: str | None) -> bool:
        if not presented or not presented.strip():
            return False
        return secrets.compare_digest(presented.strip(), self._secret)

    def _origin_allowed(self, origin: str | None) -> bool:
        if not origin or not origin.strip():
            return False
        try:
            address = ipaddress.ip_address(origin.strip())
        except ValueError:
            # A hostname or malformed value is not an allowed origin. Resolving names
            # here would make the check depend on DNS, which an attacker can influence.
            return False
        return any(address in network for network in self._networks)
