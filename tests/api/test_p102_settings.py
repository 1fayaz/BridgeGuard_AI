"""P102 — settings for the confirmed stack; no silent insecure fallback.

Two things are being guarded here.

**A missing secret must be a startup error, not a default.** The Spec-003 scaffolding
shipped `jwt_secret = "dev-insecure-change-me"`. Deploy with the env var unset and the
app boots happily and validates tokens against a string that is in the repository. The
failure is silent, and the thing that fails silently is authentication. So in production
mode a missing secret must *raise*.

**A limit nobody chose must not look like a limit somebody chose.** Rate limits are a
stakeholder input (spec §Rate limiting: "do not guess"). They are NaN TODO sentinels —
the same discipline as `ReportConfig` / `ScoreConfig` / `SensorProfile` — because 0 and
None are both plausible real values and would hide an unset field.

Ties to tasks.md P102, spec INV-4 + §Rate limiting, plan §5 (R2 / 900 s TTL).
"""
from __future__ import annotations

import pytest
from pydantic import SecretStr

from api.settings import Settings, is_todo

# Every secret that must have no usable default.
SECRET_FIELDS = ("jwt_secret", "r2_secret_access_key", "r2_access_key_id",
                 "internal_trigger_secret")

# Config a stakeholder supplies; must ship as TODO, never as a guessed number.
TODO_FIELDS = ("ingest_rate_per_minute", "ingest_burst_allowance",
               "read_rate_per_minute", "trigger_rate_per_minute")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """A stray BRIDGEGUARD_* var in the developer's shell must not decide these tests."""
    for name in (*SECRET_FIELDS, *TODO_FIELDS, "app_env", "r2_bucket",
                 "r2_endpoint_url", "report_url_ttl_seconds"):
        monkeypatch.delenv(f"BRIDGEGUARD_{name.upper()}", raising=False)


# --------------------------------------------------------------- the insecure default ---
def test_no_secret_has_a_usable_default():
    s = Settings()
    for name in SECRET_FIELDS:
        assert getattr(s, name) is None, (
            f"{name} must default to None — a usable default is a silent insecure fallback"
        )


def test_old_insecure_placeholder_is_gone():
    src = __import__("api.settings", fromlist=["x"]).__file__
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    assert "dev-insecure-change-me" not in text
    assert "changeme" not in text.lower()


def test_production_mode_raises_when_secrets_are_missing(monkeypatch):
    monkeypatch.setenv("BRIDGEGUARD_APP_ENV", "production")
    with pytest.raises(ValueError) as exc:
        Settings()
    msg = str(exc.value)
    # The error must name what is missing, so the operator can fix it without guessing.
    for name in SECRET_FIELDS:
        assert name in msg, f"startup error should name the missing {name}"


def test_production_mode_passes_when_secrets_are_supplied(monkeypatch):
    monkeypatch.setenv("BRIDGEGUARD_APP_ENV", "production")
    for name in SECRET_FIELDS:
        monkeypatch.setenv(f"BRIDGEGUARD_{name.upper()}", "supplied")
    monkeypatch.setenv("BRIDGEGUARD_R2_BUCKET", "bg-reports")
    monkeypatch.setenv("BRIDGEGUARD_R2_ENDPOINT_URL", "https://acct.r2.cloudflarestorage.com")
    s = Settings()
    assert s.is_production is True


def test_production_mode_raises_when_r2_target_is_missing(monkeypatch):
    # Credentials alone are not enough: without a bucket, downloads fail at request time
    # rather than at boot. Fail at boot.
    monkeypatch.setenv("BRIDGEGUARD_APP_ENV", "production")
    for name in SECRET_FIELDS:
        monkeypatch.setenv(f"BRIDGEGUARD_{name.upper()}", "supplied")
    with pytest.raises(ValueError) as exc:
        Settings()
    assert "r2_bucket" in str(exc.value)


def test_secrets_do_not_leak_in_repr(monkeypatch):
    monkeypatch.setenv("BRIDGEGUARD_JWT_SECRET", "topsecretvalue")
    s = Settings()
    assert isinstance(s.jwt_secret, SecretStr)
    for rendered in (repr(s), str(s), repr(s.jwt_secret)):
        assert "topsecretvalue" not in rendered
    # Still retrievable deliberately.
    assert s.jwt_secret.get_secret_value() == "topsecretvalue"


# ------------------------------------------------------------------- the confirmed stack ---
def test_signed_url_ttl_default_is_exactly_900_seconds():
    assert Settings().report_url_ttl_seconds == 900


def test_r2_config_present_and_env_overridable(monkeypatch):
    s = Settings()
    for name in ("r2_endpoint_url", "r2_bucket"):
        assert hasattr(s, name)
        assert getattr(s, name) is None, f"{name} must not be guessed"
    monkeypatch.setenv("BRIDGEGUARD_R2_BUCKET", "other-bucket")
    assert Settings().r2_bucket == "other-bucket"


def test_queue_config_present(monkeypatch):
    s = Settings()
    assert s.queue_url.startswith("redis://")
    assert s.report_job_max_tries >= 1
    monkeypatch.setenv("BRIDGEGUARD_QUEUE_URL", "redis://other:6379/3")
    assert Settings().queue_url == "redis://other:6379/3"


def test_jwt_verification_params_present(monkeypatch):
    s = Settings()
    assert s.jwt_algorithm == "HS256"
    assert s.jwt_issuer is None and s.jwt_audience is None
    monkeypatch.setenv("BRIDGEGUARD_JWT_ALGORITHM", "RS256")
    assert Settings().jwt_algorithm == "RS256"


# --------------------------------------------------------------------- TODO discipline ---
def test_rate_limits_ship_as_todo_not_guessed():
    s = Settings()
    for name in TODO_FIELDS:
        assert is_todo(getattr(s, name)), f"{name} must be a TODO sentinel, not a guess"
    assert s.rate_limits_are_todo is True


def test_rate_limits_are_env_overridable(monkeypatch):
    monkeypatch.setenv("BRIDGEGUARD_INGEST_RATE_PER_MINUTE", "600")
    s = Settings()
    assert s.ingest_rate_per_minute == 600
    assert is_todo(s.ingest_rate_per_minute) is False
    # One value supplied is not all of them.
    assert s.rate_limits_are_todo is True


def test_fully_configured_requires_every_stakeholder_value(monkeypatch):
    assert Settings().is_fully_configured is False
    for name in TODO_FIELDS:
        monkeypatch.setenv(f"BRIDGEGUARD_{name.upper()}", "100")
    for name in SECRET_FIELDS:
        monkeypatch.setenv(f"BRIDGEGUARD_{name.upper()}", "supplied")
    monkeypatch.setenv("BRIDGEGUARD_R2_BUCKET", "bg-reports")
    monkeypatch.setenv("BRIDGEGUARD_R2_ENDPOINT_URL", "https://acct.r2.cloudflarestorage.com")
    assert Settings().is_fully_configured is True


def test_dev_mode_stays_importable_without_any_env():
    # Phase 1 must remain runnable with no external services (the scaffolding's promise).
    s = Settings()
    assert s.is_production is False
    assert s.database_url.startswith("postgresql://")
