"""P304 — every endpoint declares who may call it; undeclared means unreachable.

This is a **positive allow-list**, and the direction matters more than anything else in
the file. A negative check ("reject Pi keys on read endpoints") protects the endpoints
someone remembered to think about. An allow-list protects the ones they didn't: an
endpoint added next year with no declaration is *unreachable* rather than open to all
three credential classes.

That is the difference between a security control that decays and one that doesn't. New
endpoints get added under deadline; the failure mode of forgetting must be a 500 in
staging, not a silently world-readable route in production.

The three separations being enforced (spec AC-7):

- **A Pi key reaches ingestion and nothing else.** A field device is the most likely
  credential to be physically extracted. Confining it to one bridge's append path means
  a stolen key writes readings for one bridge — it does not read a municipality's
  assessments, request reports, or fire triggers.
- **An engineer JWT never reaches ingestion or a trigger.** A human's token appending
  sensor readings would break the provenance chain that says raw data came from a
  device.
- **The internal secret reaches only the trigger endpoints.** n8n is glue; it has no
  business reading consumer data.

**Wrong class is 403 — the only 403 in the system** (P104). It reveals nothing about any
tenant's data because it is a fact about the caller's credential, not about a resource.
That is why it is safe to be honest here, where cross-tenant must lie with a 404.

Ties to tasks.md P304, spec AC-7, plan §2b.
"""
from __future__ import annotations

import pytest

from api.auth.allowlist import (
    ENDPOINT_CREDENTIALS,
    EndpointNotDeclaredError,
    allowed_classes,
    require_class,
)
from api.auth.principal import CredentialClass, Principal
from api.status_policy import ApiError, Failure

ENGINEER = Principal.for_engineer(municipality_id="MUNI_A", user_id="eng-7")
DEVICE = Principal.for_device(municipality_id="MUNI_A", bridge_id="BRIDGE_1")
INTERNAL = Principal.for_internal(municipality_id="MUNI_A")

INGEST = "ingest_readings"
TRIGGERS = (
    "trigger_validation", "trigger_analysis", "trigger_risk",
    "trigger_report", "trigger_alert",
)
READS = (
    "list_bridges", "get_bridge", "list_readings", "get_assessment",
    "list_reports", "get_report",
)


# ------------------------------------------------------- the allow-list is positive ---
def test_an_undeclared_endpoint_is_unreachable_not_open():
    """The headline check. Forgetting to declare must fail, not default to open."""
    with pytest.raises(EndpointNotDeclaredError):
        allowed_classes("some_endpoint_added_next_year")


def test_an_undeclared_endpoint_rejects_every_credential_class():
    for principal in (ENGINEER, DEVICE, INTERNAL):
        with pytest.raises(EndpointNotDeclaredError):
            require_class("brand_new_endpoint", principal)


def test_the_undeclared_error_is_not_an_api_error():
    """It must not become a tidy 403 — it is a programming error, not a caller error.

    A 403 would let a missing declaration ship quietly. An unhandled exception surfaces
    as a 500 in staging, which is exactly the noise a forgotten declaration deserves.
    """
    with pytest.raises(EndpointNotDeclaredError) as exc:
        allowed_classes("undeclared")
    assert not isinstance(exc.value, ApiError)


def test_no_endpoint_declares_an_empty_class_set():
    """An empty set is unreachable-but-declared — almost certainly a mistake."""
    for name, classes in ENDPOINT_CREDENTIALS.items():
        assert classes, f"{name} declares no credential class at all"


def test_every_declared_value_is_a_real_credential_class():
    for name, classes in ENDPOINT_CREDENTIALS.items():
        for c in classes:
            assert isinstance(c, CredentialClass), f"{name} declares a non-class: {c!r}"


# --------------------------------------------------------- the Pi key is write-only ---
def test_a_device_key_reaches_ingestion():
    require_class(INGEST, DEVICE)  # must not raise


@pytest.mark.parametrize("endpoint", READS)
def test_a_device_key_is_refused_on_every_read_endpoint(endpoint: str):
    with pytest.raises(ApiError) as exc:
        require_class(endpoint, DEVICE)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("endpoint", TRIGGERS)
def test_a_device_key_is_refused_on_every_trigger(endpoint: str):
    with pytest.raises(ApiError) as exc:
        require_class(endpoint, DEVICE)
    assert exc.value.status_code == 403


def test_ingestion_is_the_only_endpoint_a_device_key_may_reach():
    """Stated as a global property, so a future endpoint cannot quietly widen it."""
    reachable = [
        name for name, classes in ENDPOINT_CREDENTIALS.items()
        if CredentialClass.DEVICE_KEY in classes
    ]
    assert reachable == [INGEST], f"a device key can reach {reachable}"


# ------------------------------------------------------- the engineer JWT is read-only ---
@pytest.mark.parametrize("endpoint", READS)
def test_an_engineer_reaches_every_read_endpoint(endpoint: str):
    require_class(endpoint, ENGINEER)


def test_an_engineer_is_refused_on_ingestion():
    """A human token appending sensor readings would break raw-data provenance."""
    with pytest.raises(ApiError) as exc:
        require_class(INGEST, ENGINEER)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("endpoint", TRIGGERS)
def test_an_engineer_is_refused_on_every_trigger(endpoint: str):
    with pytest.raises(ApiError) as exc:
        require_class(endpoint, ENGINEER)
    assert exc.value.status_code == 403


# ------------------------------------------------ the internal secret is trigger-only ---
@pytest.mark.parametrize("endpoint", TRIGGERS)
def test_the_internal_secret_reaches_every_trigger(endpoint: str):
    require_class(endpoint, INTERNAL)


@pytest.mark.parametrize("endpoint", READS)
def test_the_internal_secret_is_refused_on_consumer_endpoints(endpoint: str):
    with pytest.raises(ApiError) as exc:
        require_class(endpoint, INTERNAL)
    assert exc.value.status_code == 403


def test_the_internal_secret_is_refused_on_ingestion():
    with pytest.raises(ApiError) as exc:
        require_class(INGEST, INTERNAL)
    assert exc.value.status_code == 403


def test_triggers_are_the_only_endpoints_the_internal_secret_may_reach():
    reachable = {
        name for name, classes in ENDPOINT_CREDENTIALS.items()
        if CredentialClass.INTERNAL_SECRET in classes
    }
    assert reachable == set(TRIGGERS), f"the internal secret can reach {reachable}"


# --------------------------------------------------------------- the 403 says little ---
def test_wrong_class_is_403_and_the_documented_failure():
    with pytest.raises(ApiError) as exc:
        require_class(INGEST, ENGINEER)
    assert exc.value.failure is Failure.WRONG_CREDENTIAL_CLASS
    assert exc.value.status_code == 403


def test_the_403_body_names_no_tenant_and_no_resource():
    """It may say 'wrong credential type'. It must not describe what is behind the door."""
    with pytest.raises(ApiError) as exc:
        require_class("get_assessment", DEVICE)
    blob = (exc.value.error + " " + exc.value.detail).lower()
    for banned in ("muni_", "bridge_", "assessment", "risk", "score", "report"):
        assert banned not in blob, f"the 403 body mentions {banned!r}"


def test_the_403_body_does_not_enumerate_the_accepted_classes():
    """Telling a caller which credential *would* work is a map of the auth model."""
    with pytest.raises(ApiError) as exc:
        require_class(INGEST, ENGINEER)
    blob = (exc.value.error + " " + exc.value.detail).lower()
    for banned in ("device_key", "engineer_jwt", "internal_secret", "api key", "jwt"):
        assert banned not in blob


def test_403_is_used_for_nothing_but_wrong_class():
    """Re-asserted here because P304 is the only thing that should ever produce one."""
    from api.status_policy import STATUS_POLICY

    assert [f for f, s in STATUS_POLICY.items() if s == 403] == [
        Failure.WRONG_CREDENTIAL_CLASS
    ]


# ------------------------------------------------------------ structural completeness ---
def test_every_router_endpoint_is_declared():
    """A route in the app with no declaration is the failure this task exists to catch.

    Health is the documented carve-out (P103): it is the single anonymous route, touches
    no database, and discloses nothing.
    """
    from api.main import create_app

    anonymous = {"/v1/health", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    undeclared = []
    for route in create_app().routes:
        path = getattr(route, "path", "")
        name = getattr(route, "name", "")
        if path in anonymous or not name:
            continue
        if name not in ENDPOINT_CREDENTIALS:
            undeclared.append(f"{path} ({name})")
    assert not undeclared, f"routes with no declared credential class: {undeclared}"


def test_health_is_deliberately_absent_from_the_allowlist():
    """It is anonymous by carve-out, not by omission — assert the carve-out holds."""
    assert "health" not in ENDPOINT_CREDENTIALS
