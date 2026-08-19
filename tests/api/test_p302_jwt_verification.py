"""P302 — JWT verification and tenant-claim extraction.

[AUTH-DEP] Issuance, signing-key management, rotation, and refresh belong to a separate
auth spec. This layer **consumes and enforces**: given a bearer token, either produce a
`Principal` pinned to one municipality, or 401.

Every failure here is 401. Not 403, and — this is the part worth stating — not a
*partial* success. The dangerous shapes a JWT verifier can take are all variations on
accepting something it shouldn't:

**`verify=False` / `algorithms` unpinned.** The classic. A token signed with `alg: none`,
or signed with the *public* key under HS256 when the verifier expects RS256, must be
rejected. The algorithm list is pinned to exactly what settings declare, so a token
cannot choose its own verification scheme.

**A token with no tenant claim.** It is tempting to treat this as "a valid user, just
unscoped" and let RLS handle it. That is the fail-open path: the request would proceed
with an unset GUC and read zero rows, presenting as "no data" rather than "your token is
broken." Reject at the boundary instead.

**Expiry treated as advisory.** A token that expired is not a token.

The tenant claim itself goes through `resolve_principal` (P301), so a multi-tenant claim
is rejected rather than narrowed — that rule is tested there and re-asserted here at the
JWT boundary, because this is where a list-valued claim actually arrives.

Ties to tasks.md P302, spec AC-6/AC-7, plan §2.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from api.auth.jwt_verifier import (
    TENANT_CLAIM,
    JwtVerifier,
)
from api.auth.principal import CredentialClass
from api.status_policy import ApiError, Failure

SECRET = "test-signing-secret-not-a-real-one-0123456789"
WRONG_SECRET = "a-different-secret-0123456789abcdefghijkl"
ISSUER = "bridgeguard-auth"
AUDIENCE = "bridgeguard-api"


@pytest.fixture
def verifier() -> JwtVerifier:
    return JwtVerifier(
        secret=SECRET, algorithm="HS256", issuer=ISSUER, audience=AUDIENCE
    )


def make_token(
    *,
    secret: str = SECRET,
    algorithm: str = "HS256",
    municipality_id: object = "MUNI_A",
    subject: object = "eng-7",
    expires_in: timedelta | None = timedelta(minutes=15),
    issuer: str | None = ISSUER,
    audience: str | None = AUDIENCE,
    omit_claims: tuple[str, ...] = (),
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": subject,
        TENANT_CLAIM: municipality_id,
        "iat": now,
    }
    if expires_in is not None:
        payload["exp"] = now + expires_in
    if issuer is not None:
        payload["iss"] = issuer
    if audience is not None:
        payload["aud"] = audience
    for claim in omit_claims:
        payload.pop(claim, None)
    return jwt.encode(payload, secret, algorithm=algorithm)


# ------------------------------------------------------------------ the happy path ---
def test_a_valid_token_resolves_to_a_principal(verifier: JwtVerifier):
    p = verifier.verify(make_token())
    assert p.credential_class is CredentialClass.ENGINEER_JWT
    assert p.municipality_id == "MUNI_A"
    assert p.user_id == "eng-7"
    assert p.bridge_id is None


def test_a_bearer_prefix_is_accepted(verifier: JwtVerifier):
    """Handlers pass the Authorization header through; both spellings must work."""
    p = verifier.verify(f"Bearer {make_token()}")
    assert p.municipality_id == "MUNI_A"


def test_the_tenant_claim_is_the_documented_name():
    """Pinned like the GUC: a renamed claim would 401 every real token at once."""
    assert TENANT_CLAIM == "municipality_id"


# --------------------------------------------------------------------- expiry → 401 ---
def test_an_expired_token_is_rejected(verifier: JwtVerifier):
    with pytest.raises(ApiError) as exc:
        verifier.verify(make_token(expires_in=timedelta(minutes=-1)))
    assert exc.value.status_code == 401
    assert exc.value.failure is Failure.EXPIRED_CREDENTIAL


def test_a_token_with_no_expiry_is_rejected(verifier: JwtVerifier):
    """A non-expiring bearer token is a permanent credential in a header. No."""
    with pytest.raises(ApiError) as exc:
        verifier.verify(make_token(expires_in=None))
    assert exc.value.status_code == 401


# ----------------------------------------------------------------- signature → 401 ---
def test_a_bad_signature_is_rejected(verifier: JwtVerifier):
    with pytest.raises(ApiError) as exc:
        verifier.verify(make_token(secret=WRONG_SECRET))
    assert exc.value.status_code == 401
    assert exc.value.failure is Failure.INVALID_CREDENTIAL


def test_an_alg_none_token_is_rejected(verifier: JwtVerifier):
    """The classic bypass: a token asserting it needs no signature."""
    unsigned = jwt.encode(
        {"sub": "eng-7", TENANT_CLAIM: "MUNI_A",
         "exp": datetime.now(UTC) + timedelta(minutes=5),
         "iss": ISSUER, "aud": AUDIENCE},
        key="",
        algorithm="none",
    )
    with pytest.raises(ApiError) as exc:
        verifier.verify(unsigned)
    assert exc.value.status_code == 401


def test_the_algorithm_list_is_pinned(verifier: JwtVerifier):
    """A token must not choose its own verification scheme."""
    assert verifier.algorithms == ["HS256"]
    assert "none" not in verifier.algorithms


def test_a_garbage_string_is_rejected(verifier: JwtVerifier):
    with pytest.raises(ApiError) as exc:
        verifier.verify("not-a-jwt-at-all")
    assert exc.value.status_code == 401


@pytest.mark.parametrize("empty", ["", "   ", "Bearer ", "Bearer"])
def test_an_empty_credential_is_missing_not_invalid(verifier: JwtVerifier, empty: str):
    """No credential is MISSING_CREDENTIAL — a distinct, still-401 failure class."""
    with pytest.raises(ApiError) as exc:
        verifier.verify(empty)
    assert exc.value.status_code == 401
    assert exc.value.failure is Failure.MISSING_CREDENTIAL


def test_none_is_rejected(verifier: JwtVerifier):
    with pytest.raises(ApiError) as exc:
        verifier.verify(None)  # type: ignore[arg-type]
    assert exc.value.status_code == 401


# ------------------------------------------------------------ tenant claim → 401 ---
def test_a_token_with_no_tenant_claim_is_rejected(verifier: JwtVerifier):
    """The headline check. Never a default tenant, never an unscoped pass."""
    with pytest.raises(ApiError) as exc:
        verifier.verify(make_token(omit_claims=(TENANT_CLAIM,)))
    assert exc.value.status_code == 401


def test_a_tokenless_tenant_does_not_become_an_unscoped_principal(verifier: JwtVerifier):
    """Explicitly documents the rejected alternative: 'valid user, let RLS sort it out'.

    That path proceeds with an unset GUC and reads zero rows — presenting as 'no data'
    rather than 'your token is broken'. Reject at the boundary.
    """
    with pytest.raises(ApiError):
        verifier.verify(make_token(municipality_id=None))


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_tenant_claim_is_rejected(verifier: JwtVerifier, blank: str):
    with pytest.raises(ApiError) as exc:
        verifier.verify(make_token(municipality_id=blank))
    assert exc.value.status_code == 401


def test_a_multi_tenant_claim_is_rejected_not_narrowed(verifier: JwtVerifier):
    """A list-valued claim actually arrives here, so P301's rule is re-asserted."""
    with pytest.raises(ApiError) as exc:
        verifier.verify(make_token(municipality_id=["MUNI_A", "MUNI_B"]))
    assert exc.value.status_code == 401


def test_a_single_element_list_claim_resolves(verifier: JwtVerifier):
    p = verifier.verify(make_token(municipality_id=["MUNI_A"]))
    assert p.municipality_id == "MUNI_A"


def test_a_non_string_tenant_claim_is_rejected(verifier: JwtVerifier):
    """An integer tenant would compare unequal to every TEXT municipality_id."""
    with pytest.raises(ApiError) as exc:
        verifier.verify(make_token(municipality_id=42))
    assert exc.value.status_code == 401


def test_a_token_with_no_subject_is_rejected(verifier: JwtVerifier):
    """An engineer Principal requires an identity — the audit row names a person."""
    with pytest.raises(ApiError) as exc:
        verifier.verify(make_token(omit_claims=("sub",)))
    assert exc.value.status_code == 401


# ------------------------------------------------------- issuer / audience → 401 ---
def test_a_wrong_issuer_is_rejected(verifier: JwtVerifier):
    with pytest.raises(ApiError) as exc:
        verifier.verify(make_token(issuer="some-other-idp"))
    assert exc.value.status_code == 401


def test_a_wrong_audience_is_rejected(verifier: JwtVerifier):
    """A token minted for another service must not be replayable here."""
    with pytest.raises(ApiError) as exc:
        verifier.verify(make_token(audience="a-different-api"))
    assert exc.value.status_code == 401


def test_issuer_and_audience_are_optional_when_unconfigured():
    """Not every deployment sets them; when unset, they are not enforced."""
    v = JwtVerifier(secret=SECRET, algorithm="HS256", issuer=None, audience=None)
    p = v.verify(make_token(issuer=None, audience=None))
    assert p.municipality_id == "MUNI_A"


# ------------------------------------------------------------------- leaks nothing ---
def test_no_error_message_contains_the_token(verifier: JwtVerifier):
    """A token in an error body or log is a credential in a log."""
    token = make_token(secret=WRONG_SECRET)
    with pytest.raises(ApiError) as exc:
        verifier.verify(token)
    assert token not in exc.value.detail
    assert token[:20] not in exc.value.detail


def test_no_error_message_contains_the_signing_secret(verifier: JwtVerifier):
    with pytest.raises(ApiError) as exc:
        verifier.verify(make_token(secret=WRONG_SECRET))
    assert SECRET not in exc.value.detail


def test_the_verifier_repr_hides_the_secret(verifier: JwtVerifier):
    assert SECRET not in repr(verifier)


def test_error_detail_does_not_distinguish_forgery_from_expiry_to_the_client():
    """Both are 401 with a generic message; the distinction lives in the failure class.

    A caller learning *why* their token failed learns about the verifier's internals.
    An operator reading the log gets the specific class.
    """
    v = JwtVerifier(secret=SECRET, algorithm="HS256", issuer=ISSUER, audience=AUDIENCE)
    details = set()
    for token in (make_token(secret=WRONG_SECRET),
                  make_token(omit_claims=(TENANT_CLAIM,))):
        with pytest.raises(ApiError) as exc:
            v.verify(token)
        details.add(exc.value.detail)
    assert len(details) == 1, f"the 401 body varies by cause: {details}"
