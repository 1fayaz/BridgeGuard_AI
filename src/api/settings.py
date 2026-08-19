"""Application settings (P102) — environment-only secrets, no guessed limits.

Two disciplines, both load-bearing:

1. **No secret has a usable default.** Every secret defaults to None, and in
   production mode a missing one raises at startup. A silent insecure fallback in
   the auth path is worse than a crash: the crash is noticed (INV-4).
2. **A value a stakeholder must supply is a loud TODO sentinel**, never a
   plausible number. Rate limits are NaN — the same choice as ReportConfig /
   ScoreConfig / SensorProfile, because 0 and None are both plausible real
   limits and would hide an unset field (spec §Rate limiting: "do not guess").

`max_ingest_batch_size` is deliberately NOT a TODO: it is a memory-safety bound
(reject an oversized payload), not a throughput policy — a real safe default, the
same category as the report agent's `fidelity_tolerance = 0.0`.

Dev mode stays importable with no environment at all, so Phase 1 runs without
external services.
"""
from __future__ import annotations

from typing import Final

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Sentinel for "a human must still supply this". NaN is the only value not equal
# to itself, so it cannot be confused with a real limit.
TODO: Final[float] = float("nan")


def is_todo(value: float) -> bool:
    return value != value


_REQUIRED_SECRETS: Final = (
    "jwt_secret",
    "internal_trigger_secret",
    "r2_access_key_id",
    "r2_secret_access_key",
)

_RATE_LIMIT_FIELDS: Final = (
    "ingest_rate_per_minute",
    "ingest_burst_allowance",
    "read_rate_per_minute",
    "trigger_rate_per_minute",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BRIDGEGUARD_", extra="ignore")

    # "production" turns the secret checks from advisory into fatal. Any
    # unrecognised value means non-production, so the gate can only be bypassed
    # by explicitly writing "production" — never by a typo turning it off.
    app_env: str = "development"

    # Infra connection strings (consumed in later, DB-dependent tasks).
    database_url: str = "postgresql://localhost:5432/bridgeguard"
    queue_url: str = "redis://localhost:6379/0"
    report_job_max_tries: int = 3

    # --- Secrets: environment only, never a literal here. SecretStr keeps them
    #     out of repr/str/logs; .get_secret_value() is the deliberate read. ---
    jwt_secret: SecretStr | None = None
    internal_trigger_secret: SecretStr | None = None
    r2_access_key_id: SecretStr | None = None
    r2_secret_access_key: SecretStr | None = None

    # JWT verification params (issuance is a separate auth spec).
    jwt_algorithm: str = "HS256"
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    gateway_key_store: str = "memory"

    # --- Cloudflare R2 via the S3-compatible SDK (plan §5). Endpoint/bucket are
    #     deployment facts, not guesses. TTL default is the confirmed 900 s. ---
    r2_endpoint_url: str | None = None
    r2_bucket: str | None = None
    r2_region: str = "auto"
    report_url_ttl_seconds: int = 900

    # --- Rate limits: stakeholder input, TODO until supplied (spec §Rate limiting). ---
    ingest_rate_per_minute: float = TODO
    ingest_burst_allowance: float = TODO
    read_rate_per_minute: float = TODO
    trigger_rate_per_minute: float = TODO

    # Request limits (Principle: bound resource use; tuned later, see Q-5).
    max_ingest_batch_size: int = 1000
    default_page_size: int = 50
    max_page_size: int = 500

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in ("production", "prod")

    @property
    def rate_limits_are_todo(self) -> bool:
        """True while ANY stakeholder-supplied limit is still unset."""
        return any(is_todo(getattr(self, f)) for f in _RATE_LIMIT_FIELDS)

    @property
    def is_fully_configured(self) -> bool:
        return not self.rate_limits_are_todo and not self._missing_required()

    def _missing_required(self) -> list[str]:
        missing = [f for f in _REQUIRED_SECRETS if getattr(self, f) is None]
        # Credentials without a target still fail — at request time, not boot time.
        missing += [
            f for f in ("r2_bucket", "r2_endpoint_url") if getattr(self, f) is None
        ]
        return missing

    @model_validator(mode="after")
    def _production_requires_real_secrets(self) -> "Settings":
        if self.is_production and (missing := self._missing_required()):
            raise ValueError(
                "Missing required production configuration: "
                + ", ".join(missing)
                + ". Supply each as BRIDGEGUARD_<NAME>; there is no default."
            )
        return self


def get_settings() -> Settings:
    return Settings()
