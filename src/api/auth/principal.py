"""P301 — the one shape every authenticated request converges to.

An engineer's JWT, a Pi's device key, and n8n's shared secret are three very different
credentials. They resolve here to one immutable `Principal` carrying **exactly one**
`municipality_id`. Everything downstream — the scope primitive, the endpoint allow-list,
the audit writer — reads a Principal and never the credential behind it, so a bug in one
credential path cannot produce a differently-shaped authorisation somewhere else.

Two decisions carry the weight.

**Ambiguity is rejected, never narrowed.** A credential naming two tenants could be
resolved by taking the first. That version is more dangerous than a crash precisely
because it *works*: the request proceeds, reads real rows, returns 200 — under a tenant
the issuer may never have intended, and the audit row records it as legitimate. So the
resolver raises. There is no default tenant anywhere in this module, and P301's test
greps for one.

**A Principal is frozen.** It is built once at the boundary and then read by the scope
primitive, the allow-list, and the audit writer. If any of those could reassign
`municipality_id`, the tenant a request *ran* under and the tenant it was *audited* as
could diverge — worse than either being wrong alone, because the audit trail would then
confidently testify to the wrong thing.

The per-class field rules in `__post_init__` are not tidiness. A device key that
resolved no `bridge_id` has not finished resolving — the bridge pin is the entire reason
a stolen field-device key cannot append readings for a whole municipality. An engineer
JWT carrying a `bridge_id` would silently narrow a legitimate municipality-wide read.

[AUTH-DEP] Signature verification (P302), the credential lookup (P303), and secret
comparison (P305) implement the three paths against this contract; issuance and
provisioning belong to a separate auth spec.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from api.status_policy import ApiError, Failure


class CredentialClass(str, Enum):
    """Who is calling. A closed set — P304's allow-list is keyed on it."""

    ENGINEER_JWT = "engineer_jwt"
    DEVICE_KEY = "device_key"
    INTERNAL_SECRET = "internal_secret"


class UnresolvedPrincipalError(ApiError):
    """The credential yielded no usable tenant, or lacks its required identity.

    401, not 403: a credential that cannot be resolved has not authenticated at all.
    403 would imply a valid caller reaching for something they may not have, which
    concedes more than is true.
    """

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(Failure.INVALID_CREDENTIAL, detail)


class AmbiguousTenantError(ApiError):
    """The credential named more than one tenant.

    Also 401. An ambiguous credential is an unusable credential, not a permission
    question — and answering it by picking one would be the silent cross-tenant read
    this whole layer exists to prevent.
    """

    def __init__(self, count: int | None = None) -> None:
        # Deliberately does NOT name the tenants involved. Naming one would suggest it
        # was selected, and this text can reach a log an operator reads under pressure.
        detail = (
            "The credential names more than one municipality and cannot be resolved "
            "to a single scope."
        )
        if count is not None:
            detail += f" ({count} distinct values presented.)"
        super().__init__(Failure.INVALID_CREDENTIAL, detail)


@dataclass(frozen=True, slots=True)
class Principal:
    """One authenticated caller, pinned to exactly one municipality.

    `slots=True` as well as `frozen=True`: frozen blocks reassignment, slots blocks
    smuggling a second tenant on as a new attribute.
    """

    credential_class: CredentialClass
    municipality_id: str
    user_id: str | None = None
    bridge_id: str | None = None

    def __post_init__(self) -> None:
        if not self.municipality_id or not self.municipality_id.strip():
            raise UnresolvedPrincipalError(
                "A credential must resolve to exactly one municipality."
            )

        if self.credential_class is CredentialClass.ENGINEER_JWT:
            if not self.user_id:
                raise UnresolvedPrincipalError(
                    "An engineer credential must carry an identity."
                )
            if self.bridge_id is not None:
                # An engineer reads their whole municipality; a bridge pin here would
                # silently narrow a legitimate read.
                raise ValueError(
                    "an engineer principal must not pin a bridge — only a device key does"
                )

        elif self.credential_class is CredentialClass.DEVICE_KEY:
            if not self.bridge_id:
                # The pin is the point: it is what stops a stolen field-device key from
                # appending readings across a whole municipality.
                raise UnresolvedPrincipalError(
                    "A device credential must resolve to exactly one bridge."
                )
            if self.user_id is not None:
                raise ValueError(
                    "a device principal has no human identity; use device_label for "
                    "operator-facing labelling"
                )

        else:  # INTERNAL_SECRET
            if self.user_id is not None or self.bridge_id is not None:
                raise ValueError(
                    "an internal principal carries a tenant only — no identity, no bridge"
                )

    # --- one constructor per credential class ---------------------------------------
    @classmethod
    def for_engineer(cls, *, municipality_id: str, user_id: str) -> "Principal":
        return cls(
            credential_class=CredentialClass.ENGINEER_JWT,
            municipality_id=municipality_id,
            user_id=user_id,
        )

    @classmethod
    def for_device(cls, *, municipality_id: str, bridge_id: str) -> "Principal":
        return cls(
            credential_class=CredentialClass.DEVICE_KEY,
            municipality_id=municipality_id,
            bridge_id=bridge_id,
        )

    @classmethod
    def for_internal(cls, *, municipality_id: str) -> "Principal":
        return cls(
            credential_class=CredentialClass.INTERNAL_SECRET,
            municipality_id=municipality_id,
        )


def resolve_principal(
    credential_class: CredentialClass,
    *,
    municipality_ids: Sequence[str] | None,
    user_id: str | None = None,
    bridge_id: str | None = None,
) -> Principal:
    """Collapse whatever tenant values a credential presented into exactly one.

    Takes a sequence rather than a single value deliberately: a JWT claim can legitimately
    arrive as a list, and the collapsing rule is the thing that must be tested. Duplicates
    of the same tenant are malformed but unambiguous, so they resolve; two *distinct*
    tenants do not.
    """
    values = [m.strip() for m in (municipality_ids or []) if m and m.strip()]
    if not values:
        raise UnresolvedPrincipalError("The credential carries no municipality scope.")

    if len(set(values)) > 1:
        raise AmbiguousTenantError(len(set(values)))

    return Principal(
        credential_class=credential_class,
        municipality_id=values[0],
        user_id=user_id,
        bridge_id=bridge_id,
    )
