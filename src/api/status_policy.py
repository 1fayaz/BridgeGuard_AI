"""Failure class → HTTP status, in exactly one place (P104).

Handlers raise an `ApiError(Failure.X)` and never choose a status. The mapping below
is the whole policy; there is no second copy and no inline literal.

Two rules carry real weight:

**INV-3 — a cross-tenant resource is 404, never 403.** 403 would confirm the resource
exists, which is precisely the leak the isolation design prevents. Under RLS the
handler genuinely cannot tell "absent" from "another tenant's", so 404 is not a
convention layered on top — it is the honest answer. `CROSS_TENANT` and `NOT_FOUND`
therefore produce **byte-identical** responses (bar the correlation id): matching only
the status would still leak existence through `detail`.

**403 means exactly one thing** — the wrong *credential class* (a Pi key on a read
endpoint, a JWT on an internal trigger). That reveals nothing about any tenant's data,
because it is a fact about the caller's credential, not about a resource.
"""
from __future__ import annotations

from enum import Enum
from typing import Final


class Failure(str, Enum):
    """Every way a request can fail at this boundary. A closed set."""

    MISSING_CREDENTIAL = "missing_credential"
    INVALID_CREDENTIAL = "invalid_credential"
    EXPIRED_CREDENTIAL = "expired_credential"
    WRONG_CREDENTIAL_CLASS = "wrong_credential_class"
    CROSS_TENANT = "cross_tenant"
    NOT_FOUND = "not_found"
    VALIDATION = "validation"
    NOT_COMPLETE = "not_complete"
    RATE_LIMITED = "rate_limited"
    INTERNAL = "internal"


STATUS_POLICY: Final[dict[Failure, int]] = {
    Failure.MISSING_CREDENTIAL: 401,
    Failure.INVALID_CREDENTIAL: 401,
    Failure.EXPIRED_CREDENTIAL: 401,
    # The only 403. Wrong credential *class*, never wrong tenant.
    Failure.WRONG_CREDENTIAL_CLASS: 403,
    # INV-3: indistinguishable from NOT_FOUND, by design.
    Failure.CROSS_TENANT: 404,
    Failure.NOT_FOUND: 404,
    Failure.NOT_COMPLETE: 409,
    Failure.VALIDATION: 422,
    Failure.RATE_LIMITED: 429,
    Failure.INTERNAL: 500,
}

# Client-visible text per failure class. CROSS_TENANT and NOT_FOUND deliberately share
# one entry — the same object, so they cannot drift apart in a later edit.
_NOT_FOUND_MESSAGE: Final = "Not found."
_NOT_FOUND_DETAIL: Final = "No such resource."

# The client-visible machine code per failure class. This is NOT the enum value:
# CROSS_TENANT must present as `not_found`, or the code field itself confirms the
# resource exists — the leak INV-3 exists to close. The enum value stays distinct for
# the internal log, which is the one place the distinction belongs.
_CLIENT_CODES: Final[dict[Failure, str]] = {
    Failure.CROSS_TENANT: Failure.NOT_FOUND.value,
}

_MESSAGES: Final[dict[Failure, tuple[str, str]]] = {
    Failure.MISSING_CREDENTIAL: (
        "Authentication required.", "No credential was supplied."),
    Failure.INVALID_CREDENTIAL: (
        "Authentication failed.", "The supplied credential is not valid."),
    Failure.EXPIRED_CREDENTIAL: (
        "Authentication failed.", "The supplied credential has expired."),
    Failure.WRONG_CREDENTIAL_CLASS: (
        "Not permitted.", "This credential type cannot be used on this endpoint."),
    Failure.CROSS_TENANT: (_NOT_FOUND_MESSAGE, _NOT_FOUND_DETAIL),
    Failure.NOT_FOUND: (_NOT_FOUND_MESSAGE, _NOT_FOUND_DETAIL),
    Failure.VALIDATION: (
        "Request validation failed.", "One or more fields are missing or malformed."),
    Failure.NOT_COMPLETE: (
        "Not ready.", "The requested job has not completed."),
    Failure.RATE_LIMITED: (
        "Too many requests.", "The rate limit for this credential was exceeded."),
    Failure.INTERNAL: (
        "An internal error occurred.",
        "The request could not be completed. Quote the correlation_id when reporting this.",
    ),
}


def status_for(failure: Failure) -> int:
    """The documented status for a failure class.

    Raises rather than defaulting: an unmapped failure is a policy gap, and defaulting
    to 500 would hide it behind a plausible response.
    """
    try:
        return STATUS_POLICY[failure]
    except KeyError:  # pragma: no cover - guarded by test_policy_is_total
        raise LookupError(f"no status declared for {failure!r}") from None


def messages_for(failure: Failure) -> tuple[str, str]:
    """`(error, detail)` for a failure class — both safe by construction."""
    return _MESSAGES[failure]


class ApiError(Exception):
    """The only way a handler reports a failure.

    Carries a failure *class*, not a status. `detail_override` exists for the cases
    where safe specifics genuinely help (which field, which job state) — it is never
    populated from exception text or request input, and it is ignored for
    `CROSS_TENANT`, so no caller can accidentally make a cross-tenant 404
    distinguishable from a genuine miss.
    """

    __slots__ = ("failure", "detail_override", "retry_after")

    def __init__(
        self,
        failure: Failure,
        detail_override: str | None = None,
        *,
        retry_after: int | None = None,
    ) -> None:
        self.failure = failure
        self.detail_override = (
            None if failure is Failure.CROSS_TENANT else detail_override
        )
        self.retry_after = retry_after
        super().__init__(failure.value)

    @property
    def status_code(self) -> int:
        return status_for(self.failure)

    @property
    def code(self) -> str:
        """The client-visible code — masked for CROSS_TENANT (see `_CLIENT_CODES`)."""
        return _CLIENT_CODES.get(self.failure, self.failure.value)

    @property
    def error(self) -> str:
        return messages_for(self.failure)[0]

    @property
    def detail(self) -> str:
        return self.detail_override or messages_for(self.failure)[1]
