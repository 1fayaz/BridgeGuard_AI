"""P301 — one resolver, one `Principal`, exactly one tenant.

Three credential classes enter (engineer JWT, Pi device key, n8n internal secret); one
shape comes out. That convergence is the point: everything downstream — the scope
primitive, the endpoint allow-list, the audit row — deals with a `Principal` and never
with the credential that produced it. A bug in one credential path cannot therefore
produce a *differently-shaped* authorisation elsewhere.

The property this file exists to pin:

**A credential naming more than one tenant is REJECTED, never narrowed.** Silently
taking the first entry of a multi-tenant claim is the dangerous version, because it
succeeds. The request proceeds, reads real data, returns 200 — under a tenant the
credential's issuer may not have meant. Every ambiguity here fails closed instead.

Also pinned: the `Principal` is immutable after construction. It is created once at the
boundary and then read by the scope primitive, the allow-list, and the audit writer. If
any of those could reassign `municipality_id`, the tenant a request *ran* under and the
tenant it was *audited* as could differ — which is worse than either being wrong alone,
because the audit trail would then testify to the wrong thing.

[AUTH-DEP] Signature verification, issuance, and key provisioning are a separate auth
spec. This is the contract every credential path must satisfy; P302/P303/P305 implement
the three paths against it.

Ties to tasks.md P301, spec AC-6/AC-7, plan §2.
"""
from __future__ import annotations

import dataclasses

import pytest

from api.auth.principal import (
    AmbiguousTenantError,
    CredentialClass,
    Principal,
    UnresolvedPrincipalError,
    resolve_principal,
)
from api.status_policy import ApiError, Failure


# ------------------------------------------------------------------ the three classes ---
def test_credential_class_is_a_closed_set():
    assert {c.value for c in CredentialClass} == {
        "engineer_jwt", "device_key", "internal_secret"
    }


def test_engineer_jwt_resolves_to_one_tenant_and_a_user():
    p = Principal.for_engineer(municipality_id="MUNI_A", user_id="eng-7")
    assert p.credential_class is CredentialClass.ENGINEER_JWT
    assert p.municipality_id == "MUNI_A"
    assert p.user_id == "eng-7"
    assert p.bridge_id is None


def test_device_key_resolves_to_one_tenant_and_one_bridge():
    p = Principal.for_device(municipality_id="MUNI_A", bridge_id="BRIDGE_1")
    assert p.credential_class is CredentialClass.DEVICE_KEY
    assert p.municipality_id == "MUNI_A"
    assert p.bridge_id == "BRIDGE_1"
    assert p.user_id is None


def test_internal_secret_resolves_to_one_tenant_and_no_identity():
    """n8n is a machine caller. Its tenant comes from the request's scope key."""
    p = Principal.for_internal(municipality_id="MUNI_A")
    assert p.credential_class is CredentialClass.INTERNAL_SECRET
    assert p.municipality_id == "MUNI_A"
    assert p.user_id is None
    assert p.bridge_id is None


# ------------------------------------------------- exactly one tenant, never narrowed ---
def test_a_multi_tenant_claim_is_rejected_not_narrowed():
    """The headline check. Two tenants is an error, not a menu."""
    with pytest.raises(AmbiguousTenantError):
        resolve_principal(
            CredentialClass.ENGINEER_JWT,
            municipality_ids=["MUNI_A", "MUNI_B"],
            user_id="eng-7",
        )


def test_the_rejection_does_not_pick_the_first_tenant():
    """Explicitly documents the rejected alternative — the version that returns 200."""
    with pytest.raises(AmbiguousTenantError) as exc:
        resolve_principal(
            CredentialClass.ENGINEER_JWT,
            municipality_ids=["MUNI_A", "MUNI_B"],
            user_id="eng-7",
        )
    assert "MUNI_A" not in str(exc.value), (
        "the error names a tenant, suggesting one was selected"
    )


def test_three_tenants_is_equally_rejected():
    with pytest.raises(AmbiguousTenantError):
        resolve_principal(
            CredentialClass.ENGINEER_JWT,
            municipality_ids=["MUNI_A", "MUNI_B", "MUNI_C"],
            user_id="eng-7",
        )


def test_a_repeated_tenant_is_still_exactly_one_tenant():
    """`["MUNI_A", "MUNI_A"]` is malformed, but it is unambiguous. Resolve it."""
    p = resolve_principal(
        CredentialClass.ENGINEER_JWT,
        municipality_ids=["MUNI_A", "MUNI_A"],
        user_id="eng-7",
    )
    assert p.municipality_id == "MUNI_A"


def test_zero_tenants_is_rejected():
    with pytest.raises(UnresolvedPrincipalError):
        resolve_principal(
            CredentialClass.ENGINEER_JWT, municipality_ids=[], user_id="eng-7"
        )


def test_a_none_tenant_is_rejected():
    with pytest.raises(UnresolvedPrincipalError):
        resolve_principal(
            CredentialClass.ENGINEER_JWT, municipality_ids=None, user_id="eng-7"
        )


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_blank_tenant_is_rejected(blank: str):
    """A whitespace claim is not a tenant named ' '."""
    with pytest.raises(UnresolvedPrincipalError):
        resolve_principal(
            CredentialClass.ENGINEER_JWT, municipality_ids=[blank], user_id="eng-7"
        )


def test_no_default_tenant_exists_anywhere():
    """There must be no fallback. An unresolvable credential is 401, not MUNI_DEFAULT."""
    import api.auth.principal as mod
    import inspect

    src = inspect.getsource(mod).lower()
    for smell in ("default_municipality", "muni_default", "fallback_tenant", '= "muni'):
        assert smell not in src, f"a default tenant appears in the resolver: {smell!r}"


# ------------------------------------------------------- per-class field requirements ---
def test_a_device_principal_without_a_bridge_is_rejected():
    """A device key that resolved no bridge has not resolved — its whole point is the pin."""
    with pytest.raises(UnresolvedPrincipalError):
        Principal.for_device(municipality_id="MUNI_A", bridge_id=None)  # type: ignore[arg-type]


def test_an_engineer_principal_without_a_user_is_rejected():
    with pytest.raises(UnresolvedPrincipalError):
        Principal.for_engineer(municipality_id="MUNI_A", user_id=None)  # type: ignore[arg-type]


def test_an_engineer_cannot_carry_a_bridge_pin():
    """Only a device key pins a bridge. An engineer reads their whole municipality."""
    with pytest.raises(ValueError):
        Principal(
            credential_class=CredentialClass.ENGINEER_JWT,
            municipality_id="MUNI_A",
            user_id="eng-7",
            bridge_id="BRIDGE_1",
        )


def test_a_device_cannot_carry_a_user_identity():
    with pytest.raises(ValueError):
        Principal(
            credential_class=CredentialClass.DEVICE_KEY,
            municipality_id="MUNI_A",
            bridge_id="BRIDGE_1",
            user_id="eng-7",
        )


def test_an_internal_principal_carries_neither():
    with pytest.raises(ValueError):
        Principal(
            credential_class=CredentialClass.INTERNAL_SECRET,
            municipality_id="MUNI_A",
            bridge_id="BRIDGE_1",
        )


# ----------------------------------------------------------------------- immutability ---
def test_principal_is_frozen():
    """The tenant a request runs under must equal the tenant it is audited as."""
    p = Principal.for_engineer(municipality_id="MUNI_A", user_id="eng-7")
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.municipality_id = "MUNI_B"  # type: ignore[misc]


def test_principal_cannot_be_given_new_attributes():
    p = Principal.for_engineer(municipality_id="MUNI_A", user_id="eng-7")
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        p.extra_tenant = "MUNI_B"  # type: ignore[attr-defined]


def test_credential_class_cannot_be_reassigned():
    """Class-swapping post-resolution would defeat P304's allow-list."""
    p = Principal.for_device(municipality_id="MUNI_A", bridge_id="BRIDGE_1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.credential_class = CredentialClass.ENGINEER_JWT  # type: ignore[misc]


# --------------------------------------------------------------- leaks nothing on repr ---
def test_repr_carries_no_credential_material():
    """A Principal lands in logs and audit rows. It must be safe there by construction."""
    p = Principal.for_device(municipality_id="MUNI_A", bridge_id="BRIDGE_1")
    blob = repr(p).lower()
    for banned in ("secret", "token", "key_hash", "password", "bearer", "jwt "):
        assert banned not in blob


def test_principal_holds_no_credential_field():
    """It must not even be possible to stash the raw credential on it."""
    fields = {f.name for f in dataclasses.fields(Principal)}
    assert fields == {"credential_class", "municipality_id", "user_id", "bridge_id"}


# ------------------------------------------------------------- boundary error mapping ---
def test_unresolved_principal_maps_to_401():
    """No tenant resolved = not authenticated. Never 403, which implies a valid caller."""
    assert UnresolvedPrincipalError().failure is Failure.INVALID_CREDENTIAL
    assert isinstance(UnresolvedPrincipalError(), ApiError)


def test_ambiguous_tenant_maps_to_401():
    """An ambiguous credential is an unusable credential, not a permission problem."""
    assert AmbiguousTenantError().failure is Failure.INVALID_CREDENTIAL


def test_neither_error_maps_to_403():
    """403 is reserved for wrong credential CLASS (P104/P304). These are not that."""
    for exc in (UnresolvedPrincipalError(), AmbiguousTenantError()):
        assert exc.failure is not Failure.WRONG_CREDENTIAL_CLASS


# ----------------------------------------------------------- the seam it feeds into ---
@pytest.mark.asyncio
async def test_a_principal_scopes_a_transaction():
    """End-to-end: the resolved tenant is what the GUC gets set to."""
    from api.db.fake_connection import FakeConnection
    from api.db.scope import scoped_transaction

    conn = FakeConnection()
    p = Principal.for_engineer(municipality_id="MUNI_A", user_id="eng-7")
    async with scoped_transaction(conn, p.municipality_id):
        assert conn.current_scope == "MUNI_A"
