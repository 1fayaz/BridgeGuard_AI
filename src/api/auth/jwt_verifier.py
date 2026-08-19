"""P302 — verify a bearer JWT, or 401. There is no third outcome.

[AUTH-DEP] Issuance, signing keys, rotation, and refresh belong to a separate auth spec.
This layer consumes and enforces.

The design is shaped by what a JWT verifier gets wrong in practice, which is never
"rejects a good token" — it is always accepting something it shouldn't:

**The algorithm list is pinned to exactly one.** PyJWT requires `algorithms=` and this
passes `[self.algorithm]`, so a token cannot nominate its own verification scheme. That
closes both `alg: none` and the HS256/RS256 confusion where an attacker signs with the
public key.

**A missing tenant claim is a rejection, not an unscoped pass.** The tempting reading is
"the signature is valid, so the user is real — let RLS handle scope." That path fails
open in the quiet way: the request runs with an unset GUC, reads zero rows, and presents
as "no data" instead of "your token is malformed." Rejecting here means the failure is
visible at the boundary where it can be fixed.

**No expiry means rejection.** `require=["exp"]` — a non-expiring bearer token is a
permanent credential sitting in a header.

**Every failure produces one identical client-facing detail.** A caller who can tell
"bad signature" from "missing claim" from "wrong audience" is being handed a probe into
the verifier's configuration. The specific `Failure` class is preserved for the log
(`handle_api_error` records it), and the client gets one flat answer.
"""
from __future__ import annotations

from typing import Any, Final

import jwt

from api.auth.principal import CredentialClass, Principal, resolve_principal
from api.status_policy import ApiError, Failure

# The claim carrying the tenant. Pinned like the GUC name (P206): renaming it would 401
# every real token simultaneously, so it is a constant with a test on it, not a literal
# scattered through the verifier.
TENANT_CLAIM: Final = "municipality_id"

_SUBJECT_CLAIM: Final = "sub"
_BEARER: Final = "bearer"

# One message for every rejection. See the module docstring — telling a caller *why*
# their token failed tells them about the verifier.
_GENERIC_DETAIL: Final = (
    "The supplied credential could not be verified. Obtain a new token and retry."
)


class JwtVerifier:
    """Verifies engineer/dashboard tokens against one pinned algorithm."""

    __slots__ = ("_secret", "algorithm", "issuer", "audience")

    def __init__(
        self,
        *,
        secret: str,
        algorithm: str = "HS256",
        issuer: str | None = None,
        audience: str | None = None,
    ) -> None:
        self._secret = secret
        self.algorithm = algorithm
        self.issuer = issuer
        self.audience = audience

    @property
    def algorithms(self) -> list[str]:
        """Exactly the one configured algorithm — never a permissive list."""
        return [self.algorithm]

    def __repr__(self) -> str:
        # The secret must not reach a log via an incidental repr of the verifier.
        return (
            f"JwtVerifier(algorithm={self.algorithm!r}, issuer={self.issuer!r}, "
            f"audience={self.audience!r}, secret=<redacted>)"
        )

    def verify(self, credential: str | None) -> Principal:
        """Verify a token (bare or `Bearer …`) and resolve it to a Principal."""
        token = self._strip_bearer(credential)

        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=self.algorithms,
                issuer=self.issuer,
                audience=self.audience,
                options={
                    # An unexpiring bearer token is a permanent credential.
                    "require": ["exp"],
                    "verify_exp": True,
                    "verify_signature": True,
                    "verify_aud": self.audience is not None,
                    "verify_iss": self.issuer is not None,
                },
            )
        except jwt.ExpiredSignatureError:
            # Distinguished for the log only; the client-facing detail is identical.
            raise ApiError(Failure.EXPIRED_CREDENTIAL, _GENERIC_DETAIL) from None
        except jwt.PyJWTError:
            # Covers bad signature, alg mismatch, malformed token, wrong iss/aud, and a
            # missing `exp`. Deliberately not re-raised with the library's message,
            # which can quote token internals.
            raise ApiError(Failure.INVALID_CREDENTIAL, _GENERIC_DETAIL) from None

        return self._to_principal(claims)

    # --- internals --------------------------------------------------------------------
    @staticmethod
    def _strip_bearer(credential: str | None) -> str:
        if not credential or not credential.strip():
            raise ApiError(Failure.MISSING_CREDENTIAL)
        value = credential.strip()
        if value.lower().startswith(_BEARER):
            value = value[len(_BEARER):].strip()
        if not value:
            raise ApiError(Failure.MISSING_CREDENTIAL)
        return value

    @staticmethod
    def _to_principal(claims: dict[str, Any]) -> Principal:
        subject = claims.get(_SUBJECT_CLAIM)
        if not isinstance(subject, str) or not subject.strip():
            raise ApiError(Failure.INVALID_CREDENTIAL, _GENERIC_DETAIL)

        tenants = JwtVerifier._tenant_values(claims.get(TENANT_CLAIM))
        try:
            return resolve_principal(
                CredentialClass.ENGINEER_JWT,
                municipality_ids=tenants,
                user_id=subject.strip(),
            )
        except ApiError:
            # resolve_principal already fails closed on zero/ambiguous tenants; re-raise
            # with the flat detail so the JWT path cannot be probed for claim shape.
            raise ApiError(Failure.INVALID_CREDENTIAL, _GENERIC_DETAIL) from None

    @staticmethod
    def _tenant_values(claim: object) -> list[str]:
        """Normalize the claim to a list of strings without coercing non-strings.

        An integer tenant id is rejected rather than str()'d: it would compare unequal
        to every TEXT `municipality_id` and read as an empty tenant instead of an error.
        """
        if claim is None:
            return []
        if isinstance(claim, str):
            return [claim]
        if isinstance(claim, (list, tuple)):
            return [v for v in claim if isinstance(v, str)]
        return []
