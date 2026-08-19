"""P305 — the internal trigger secret, plus the network restriction behind it.

The requirement that shapes this file is one line in plan §7: *"A leaked shared secret
must not be sufficient to trigger the pipeline from outside."* So there are two
independent factors, and the tests assert each is load-bearing on its own — a correct
secret from a disallowed origin fails, and an allowed origin with a wrong secret fails.
Neither is decorative.

Why a shared secret needs a second factor at all: unlike a JWT it does not expire, unlike
a device key it is not bound to one bridge, and it sits in an n8n workflow configuration
that gets exported, copied between environments, and pasted into support threads. It is
the credential in this system most likely to leak *without anyone knowing it leaked*. The
network restriction is what converts that from a pipeline compromise into a failed
request from an unexpected address.

**Comparison is constant-time.** A byte-by-byte `==` returns faster on an early mismatch,
and a trigger endpoint is remotely reachable and unrate-limited by definition (n8n
retries). That is a workable timing oracle against a fixed, non-expiring secret.

**Both failures are 403, and identical.** A caller must not be able to tell "right
secret, wrong network" from "wrong secret" — the first would confirm they hold a valid
credential and reduce the problem to finding an allowed origin.

Ties to tasks.md P305, spec AC-7, plan §7.
"""
from __future__ import annotations

import inspect
import logging

import pytest

from api.auth.internal_secret import InternalSecretVerifier
from api.auth.principal import CredentialClass
from api.status_policy import ApiError, Failure

SECRET = "n8n-shared-trigger-secret-0123456789abcdef"
WRONG = "not-the-secret-0123456789abcdefghijklmnop"
ALLOWED = ("10.0.0.0/8", "192.168.1.50")


@pytest.fixture
def verifier() -> InternalSecretVerifier:
    return InternalSecretVerifier(secret=SECRET, allowed_origins=ALLOWED)


# ------------------------------------------------------------------ the happy path ---
def test_a_correct_secret_from_an_allowed_origin_resolves(verifier):
    p = verifier.verify(SECRET, origin="10.1.2.3", municipality_id="MUNI_A")
    assert p.credential_class is CredentialClass.INTERNAL_SECRET
    assert p.municipality_id == "MUNI_A"
    assert p.user_id is None and p.bridge_id is None


def test_an_exact_host_in_the_allow_list_is_accepted(verifier):
    assert verifier.verify(SECRET, origin="192.168.1.50",
                           municipality_id="MUNI_A").municipality_id == "MUNI_A"


def test_the_tenant_comes_from_the_request_scope_key(verifier):
    """n8n has no tenant of its own — the trigger body names the municipality."""
    assert verifier.verify(SECRET, origin="10.0.0.1",
                           municipality_id="MUNI_B").municipality_id == "MUNI_B"


# ------------------------------------------------- neither factor is sufficient alone ---
def test_a_wrong_secret_from_an_allowed_origin_is_refused(verifier):
    with pytest.raises(ApiError) as exc:
        verifier.verify(WRONG, origin="10.1.2.3", municipality_id="MUNI_A")
    assert exc.value.status_code == 403


def test_a_correct_secret_from_a_disallowed_origin_is_refused(verifier):
    """The headline check: a leaked secret alone does not trigger the pipeline."""
    with pytest.raises(ApiError) as exc:
        verifier.verify(SECRET, origin="203.0.113.9", municipality_id="MUNI_A")
    assert exc.value.status_code == 403


def test_a_correct_secret_with_no_origin_is_refused(verifier):
    """An absent origin is not an allowed origin."""
    with pytest.raises(ApiError) as exc:
        verifier.verify(SECRET, origin=None, municipality_id="MUNI_A")
    assert exc.value.status_code == 403


@pytest.mark.parametrize("origin", ["", "   ", "not-an-ip", "10.0.0", "::1"])
def test_a_malformed_origin_is_refused(verifier, origin: str):
    with pytest.raises(ApiError):
        verifier.verify(SECRET, origin=origin, municipality_id="MUNI_A")


def test_a_near_miss_subnet_is_refused(verifier):
    """11.x is not 10.x. The CIDR must actually be evaluated, not prefix-matched."""
    with pytest.raises(ApiError):
        verifier.verify(SECRET, origin="11.0.0.1", municipality_id="MUNI_A")


def test_a_host_that_merely_starts_with_an_allowed_host_is_refused(verifier):
    """String-prefix matching would let 192.168.1.500 through."""
    with pytest.raises(ApiError):
        verifier.verify(SECRET, origin="192.168.1.5", municipality_id="MUNI_A")


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_a_missing_secret_is_refused(verifier, blank):
    with pytest.raises(ApiError) as exc:
        verifier.verify(blank, origin="10.1.2.3", municipality_id="MUNI_A")
    assert exc.value.status_code in (401, 403)


def test_both_factors_wrong_is_still_one_403(verifier):
    with pytest.raises(ApiError) as exc:
        verifier.verify(WRONG, origin="203.0.113.9", municipality_id="MUNI_A")
    assert exc.value.status_code == 403


# ------------------------------------------------ the two failures are indistinguishable ---
def test_wrong_secret_and_wrong_origin_look_identical_to_the_caller(verifier):
    """Otherwise a caller learns they hold a valid secret and need only a new address."""
    with pytest.raises(ApiError) as bad_secret:
        verifier.verify(WRONG, origin="10.1.2.3", municipality_id="MUNI_A")
    with pytest.raises(ApiError) as bad_origin:
        verifier.verify(SECRET, origin="203.0.113.9", municipality_id="MUNI_A")
    assert bad_secret.value.status_code == bad_origin.value.status_code
    assert bad_secret.value.error == bad_origin.value.error
    assert bad_secret.value.detail == bad_origin.value.detail
    assert bad_secret.value.code == bad_origin.value.code


def test_no_error_body_names_the_allowed_origins(verifier):
    """The allow-list is a map of the internal network. It stays internal."""
    with pytest.raises(ApiError) as exc:
        verifier.verify(SECRET, origin="203.0.113.9", municipality_id="MUNI_A")
    blob = (exc.value.error + " " + exc.value.detail).lower()
    for banned in ("10.0.0.0", "192.168", "cidr", "subnet", "origin", "network"):
        assert banned not in blob, f"the 403 body mentions {banned!r}"


# ------------------------------------------------------------- the secret never escapes ---
def test_comparison_is_constant_time():
    """A fixed, non-expiring, retry-friendly secret is a real timing target."""
    src = inspect.getsource(InternalSecretVerifier)
    assert "compare_digest" in src, "secret comparison must use secrets.compare_digest"
    assert "== self._secret" not in src
    assert "self._secret ==" not in src


def test_the_secret_is_never_in_an_error_message(verifier):
    with pytest.raises(ApiError) as exc:
        verifier.verify(WRONG, origin="10.1.2.3", municipality_id="MUNI_A")
    assert SECRET not in exc.value.detail
    assert WRONG not in exc.value.detail


def test_the_secret_is_never_logged(verifier, caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ApiError):
        verifier.verify(WRONG, origin="10.1.2.3", municipality_id="MUNI_A")
    assert SECRET not in caplog.text
    assert WRONG not in caplog.text


def test_a_successful_verification_logs_no_secret(verifier, caplog):
    caplog.set_level(logging.DEBUG)
    verifier.verify(SECRET, origin="10.1.2.3", municipality_id="MUNI_A")
    assert SECRET not in caplog.text


def test_the_verifier_repr_hides_the_secret(verifier):
    assert SECRET not in repr(verifier)


def test_the_verifier_repr_hides_the_allowed_origins(verifier):
    """An incidental repr in a log should not publish the network map either."""
    blob = repr(verifier)
    assert "10.0.0.0/8" not in blob
    assert "192.168.1.50" not in blob


# ------------------------------------------------------------------ misconfiguration ---
def test_an_empty_allow_list_refuses_everything():
    """Fail closed: no configured origins means no origin is allowed, not all of them."""
    v = InternalSecretVerifier(secret=SECRET, allowed_origins=())
    with pytest.raises(ApiError):
        v.verify(SECRET, origin="10.1.2.3", municipality_id="MUNI_A")


def test_a_wildcard_origin_is_rejected_at_construction():
    """`0.0.0.0/0` would silently remove the second factor."""
    for wildcard in ("0.0.0.0/0", "*", "::/0"):
        with pytest.raises(ValueError):
            InternalSecretVerifier(secret=SECRET, allowed_origins=(wildcard,))


def test_an_unset_secret_is_rejected_at_construction():
    """A None/blank secret would make compare_digest trivially satisfiable."""
    for bad in (None, "", "   "):
        with pytest.raises(ValueError):
            InternalSecretVerifier(secret=bad, allowed_origins=ALLOWED)  # type: ignore[arg-type]


def test_a_short_secret_is_rejected_at_construction():
    with pytest.raises(ValueError):
        InternalSecretVerifier(secret="short", allowed_origins=ALLOWED)


# ------------------------------------------------------------- no approval surface ---
def test_the_module_exposes_no_approval_or_dispatch_verb():
    """Plan §7: the boundary must not become a second, un-gated real-world-action path.

    The Alert agent's `needs_approval` gate lives inside the agent. An API surface that
    approved a dispatch would break the single-chokepoint invariant (Alert FR-5).
    """
    import api.auth.internal_secret as mod

    src = inspect.getsource(mod).lower()
    for banned in ("def approve", "def dispatch", "def publish", "needs_approval"):
        assert banned not in src
