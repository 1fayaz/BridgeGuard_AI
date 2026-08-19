"""Alert dispatch policy configuration (A101) — configuration, not code.

An AlertPolicy carries the operational constants the deterministic alert service needs: who to
notify at each severity band and in what escalation order, which channel to use per band, how many
times to retry / how long to back off / how long to wait before escalating, and which recipients
count as "authority-facing" (the FR-3 blast-radius override set). None of these are computed at
runtime; the service only reads them.

Discipline (same as the Report ReportConfig, the Risk ScoreConfig, the DCA SensorProfile): a value
a human must still supply is a loudly-flagged TODO sentinel — NaN for numbers, None for references
— never silently defaulted to a plausible value. We do NOT guess an on-call roster, a retry count,
an escalation timeout, or which recipients are authority-facing for a safety-critical system.

Unlike the report's `fidelity_tolerance` (whose 0.0 default is a genuine safe value), there is NO
safe default here: every operational field is a real policy choice, so all of them gate
`is_fully_configured`. The one legitimately-concrete field is `policy_version` — a non-physical
audit stamp recording WHICH policy an alert was dispatched under, for reproducibility.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# Sentinel marking a numeric value a human must still supply. Not 0: zero retries / zero timeout
# are plausible real values and would hide an unset field (same choice as the sibling configs).
TODO: Final[float] = float("nan")


def _is_todo(value: float) -> bool:
    return value != value  # NaN is the only value not equal to itself


@dataclass(frozen=True, slots=True)
class AlertPolicy:
    """Immutable operational policy for dispatching + escalating alerts.

    `policy_version` is the one always-present field (an audit stamp, not a safety number). Every
    other field stays a TODO sentinel until a stakeholder supplies it — there is no safe default
    for a roster, a retry count, an escalation window, or the authority-recipient set.
    """

    # Audit stamp — WHICH policy this config represents (non-physical; always present).
    policy_version: str

    # --- Retry / backoff / escalation timing (FR-8): how many dispatch retries, the backoff
    #     between them, and how long to wait for delivery/ack before escalating. All TODO — a
    #     wrong escalation window on a Critical alert is itself a safety failure. ---
    retry_max: float = TODO
    backoff_seconds: float = TODO
    escalation_timeout_seconds: float = TODO

    # --- Roster / routing references (FR-2/FR-3/FR-6): who is notified, the escalation order, the
    #     per-band channel, and which recipients are authority-facing. None until supplied — we do
    #     not invent who gets paged for a bridge closure. Modelled as tuples (frozen dataclass). ---
    contact_roster: tuple[tuple[str, str], ...] | None = None
    escalation_order: tuple[str, ...] | None = None
    channel_per_band: tuple[tuple[str, str], ...] | None = None
    authority_recipients: tuple[str, ...] | None = None

    # ------------------------------------------------------------------ band routing lookups ---
    def channel_for(self, severity_value: str) -> str | None:
        """The configured channel for a severity band, or None if unset/unmapped (pure lookup)."""
        if self.channel_per_band is None:
            return None
        for band, channel in self.channel_per_band:
            if band == severity_value:
                return channel
        return None

    def recipient_for(self, severity_value: str) -> str | None:
        """The configured recipient for a severity band, or None if unset/unmapped (pure lookup)."""
        if self.contact_roster is None:
            return None
        for band, recipient in self.contact_roster:
            if band == severity_value:
                return recipient
        return None

    def is_authority_recipient(self, recipient: str | None) -> bool:
        """True if the recipient is in the authority-facing set (drives the FR-3 blast-radius gate).

        An unset authority set (None) means "undecided": no recipient can be classified authority-
        facing yet, so this returns False — the tiering layer treats the band default as the floor
        and the blast-radius override simply does not fire until the set is supplied.
        """
        if recipient is None or self.authority_recipients is None:
            return False
        return recipient in self.authority_recipients

    # ------------------------------------------------------------------ helpers ---
    @property
    def retry_config_is_todo(self) -> bool:
        """True if any of the retry / backoff / escalation-timeout values is unset."""
        return (
            _is_todo(self.retry_max)
            or _is_todo(self.backoff_seconds)
            or _is_todo(self.escalation_timeout_seconds)
        )

    @property
    def roster_is_todo(self) -> bool:
        """True if the contact roster or the escalation order is unset."""
        return self.contact_roster is None or self.escalation_order is None

    @property
    def channels_are_todo(self) -> bool:
        """True if the per-band channel mapping is unset."""
        return self.channel_per_band is None

    @property
    def authority_set_is_todo(self) -> bool:
        """True if the authority-recipient set is unset.

        None means "we have not decided which recipients are authority-facing" (unset, do not
        guess). An explicitly-empty tuple means "no recipient is authority-facing" — a real,
        reviewed choice — and is NOT treated as unset.
        """
        return self.authority_recipients is None

    @property
    def is_fully_configured(self) -> bool:
        """True only when every value a human must supply is set.

        The audit version alone is never enough: the retry/backoff/timeout, the roster + escalation
        order, the per-band channels, and the authority-recipient set must all be supplied.
        """
        return not (
            self.retry_config_is_todo
            or self.roster_is_todo
            or self.channels_are_todo
            or self.authority_set_is_todo
        )
