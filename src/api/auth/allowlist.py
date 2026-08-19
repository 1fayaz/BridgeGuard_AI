"""P304 — which credential class may reach which endpoint. Positive, not negative.

The direction of this list is the whole design. A negative check ("reject device keys on
reads") protects the endpoints someone remembered to think about. This allow-list
protects the ones they didn't: an endpoint added under deadline next year, with no entry
here, is **unreachable** — not open to all three classes.

`EndpointNotDeclaredError` is deliberately **not** an `ApiError`. If a missing
declaration produced a tidy 403, it would ship quietly and stay missing. As a plain
exception it surfaces as a 500 in staging, which is the noise a forgotten declaration
should make. The failure mode of forgetting has to be loud and local, not silent and
permissive.

The three separations, and what each one is actually protecting:

**Device key → ingestion only.** A field-installed Pi is the credential most likely to
be physically extracted. Confined here, a stolen key appends readings for one bridge; it
cannot read a municipality's assessments, pull reports, or fire triggers.

**Engineer JWT → reads only.** A human token appending sensor readings would break the
provenance chain that says raw data came from a device (Principle II).

**Internal secret → triggers only.** n8n is workflow glue. It has no business reading
consumer data, so a leaked shared secret does not become a data-exfiltration path.

The 403 body is deliberately vague about *which* class would have worked. Telling a
caller "this needs a device key" hands them a map of the auth model.
"""
from __future__ import annotations

from typing import Final

from api.auth.principal import CredentialClass, Principal
from api.status_policy import ApiError, Failure

_ENGINEER: Final = frozenset({CredentialClass.ENGINEER_JWT})
_DEVICE: Final = frozenset({CredentialClass.DEVICE_KEY})
_INTERNAL: Final = frozenset({CredentialClass.INTERNAL_SECRET})


class EndpointNotDeclaredError(RuntimeError):
    """An endpoint has no declared credential class, so nobody may reach it.

    Not an ApiError, on purpose — see the module docstring. This is a programming
    error, and it must not be catchable as a routine 403.
    """


# Keyed by route *name* (the handler function's name), not path: a path can be edited
# for cosmetic reasons, and silently losing a declaration on a rename is the exact
# failure this guards. Route names are stable identifiers.
ENDPOINT_CREDENTIALS: Final[dict[str, frozenset[CredentialClass]]] = {
    # --- Endpoint 1: ingestion. The only place a device key is accepted.
    "ingest_readings": _DEVICE,

    # --- Endpoints 2-5 + reports: consumer reads. Engineers/dashboard only.
    "list_bridges": _ENGINEER,
    "get_bridge": _ENGINEER,
    "list_readings": _ENGINEER,
    "get_assessment": _ENGINEER,
    "list_reports": _ENGINEER,
    "get_report": _ENGINEER,

    # --- The five internal triggers: n8n only.
    "trigger_validation": _INTERNAL,
    "trigger_analysis": _INTERNAL,
    "trigger_risk": _INTERNAL,
    "trigger_report": _INTERNAL,
    "trigger_alert": _INTERNAL,
}

# `/v1/health` is deliberately absent: it is the single anonymous route (spec carve-out,
# P103), touches no database, and discloses no version, hostname, or tenant data. P1007
# asserts it stays the only one.


def allowed_classes(endpoint: str) -> frozenset[CredentialClass]:
    """The classes that may reach `endpoint`. Raises if it was never declared."""
    try:
        return ENDPOINT_CREDENTIALS[endpoint]
    except KeyError:
        raise EndpointNotDeclaredError(
            f"endpoint {endpoint!r} declares no credential class, so it is unreachable. "
            "Add it to ENDPOINT_CREDENTIALS — an endpoint is never open by default."
        ) from None


def require_class(endpoint: str, principal: Principal) -> None:
    """Refuse a valid credential of the wrong class with 403.

    The credential is genuine and the caller is authenticated; they are simply the wrong
    *kind* of caller for this door. That reveals nothing about any tenant's data, which
    is why this is the one place a 403 is honest (P104).
    """
    if principal.credential_class not in allowed_classes(endpoint):
        raise ApiError(Failure.WRONG_CREDENTIAL_CLASS)
