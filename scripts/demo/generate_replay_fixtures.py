"""The ONE script allowed to write the public replay fixtures (specs/005-demo-mode-and-approval,
"Replay fixtures (round 5)"). Nobody hand-edits `frontend/public/replay/demo-run.json` or
`demo-report.pdf` — this script is the sole writer, in both modes it will ever have:

- `--mode mock` (today): uses slice 1's REAL computed numbers (the actual deterministic scorer,
  via `demo.pipeline.run_slice1`) wherever they exist, and hand-shaped-but-contract-accurate stand-
  ins for pipeline-status/approve, because slices 2-4 (background runner, approval, score-trace as
  an HTTP endpoint) are not built yet. Writes `"recorded": false`.
- `--mode record` (after slices 2-4 land): will run one real local demo end to end over HTTP —
  simulate -> poll pipeline-status through all five stages -> score-trace -> approve — and save the
  actual response bodies with real timings, plus render the real demo PDF. Writes
  `"recorded": true`. **Not implemented yet** — raises clearly rather than faking a recorded run.

Every value in a `mock` run is demonstration data: no secret, no real recipient, no token.
`ALERT_TEST_RECIPIENT`/`N8N_ALERT_WEBHOOK_URL` are never read here — `notification_status` is always
the literal string `"not configured"`, matching what an unset recipient produces for real.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from demo.pipeline import run_slice1  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_JSON = REPO_ROOT / "frontend" / "public" / "replay" / "demo-run.json"
OUTPUT_PDF = REPO_ROOT / "frontend" / "public" / "replay" / "demo-report.pdf"

BRIDGE_ID = "bridge-demo-01"
CYCLE_ID = "demo-mock-0001"
DISPATCH_ID = "demo-alert-mock-0001"
_BASE_TIME = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)


def _iso(offset_seconds: float) -> str:
    return (_BASE_TIME + timedelta(seconds=offset_seconds)).isoformat().replace("+00:00", "Z")


def _stage(helper_name: str, plain_text: str, done: bool, completed_at: str | None, **extra):
    stage: dict[str, Any] = {
        "helper_name": helper_name, "plain_text": plain_text,
        "done": done, "completed_at": completed_at,
    }
    stage.update(extra)
    return stage


def _pipeline_status(*, ingestion, signal, risk, alert, report, alert_awaiting=False):
    return {
        "bridge_id": BRIDGE_ID, "cycle_id": CYCLE_ID, "is_demo": True,
        "stages": {
            "ingestion": _stage("The Listener", "Sensor heard it", ingestion is not None, ingestion),
            "signal": _stage("The Analyst", "Vibration checked", signal is not None, signal),
            "risk": _stage("The Explainer", "Risk scored", risk is not None, risk),
            "alert": _stage(
                "The Messenger", "Alert prepared", alert is not None, alert,
                awaiting_engineer=alert_awaiting,
            ),
            "report": _stage("The Writer", "Report written", report is not None, report),
        },
    }


def build_mock_timeline() -> dict[str, Any]:
    """Build the full mock fixture. Real numbers from slice 1; the rest is contract-shaped filler."""
    result = run_slice1(reading_value=3.4, cycle_id=CYCLE_ID)
    a = result.assessment
    row = result.analysis_row

    timeline = [
        {
            "at_ms": 0,
            "endpoint": "POST /v1/demo/simulate-heavy-truck",
            "response": {"cycle_id": CYCLE_ID, "status": "accepted", "is_demo": True},
        },
        {
            "at_ms": 600,
            "endpoint": "GET /v1/bridges/{bridge_id}/pipeline-status",
            "response": _pipeline_status(
                ingestion=_iso(0.6), signal=None, risk=None, alert=None, report=None,
            ),
        },
        {
            "at_ms": 1600,
            "endpoint": "GET /v1/bridges/{bridge_id}/pipeline-status",
            "response": _pipeline_status(
                ingestion=_iso(0.6), signal=_iso(1.6), risk=None, alert=None, report=None,
            ),
        },
        {
            "at_ms": 2600,
            "endpoint": "GET /v1/bridges/{bridge_id}/pipeline-status",
            "response": _pipeline_status(
                ingestion=_iso(0.6), signal=_iso(1.6), risk=_iso(2.6), alert=None, report=None,
            ),
        },
        {
            "at_ms": 3600,
            "endpoint": "GET /v1/bridges/{bridge_id}/pipeline-status",
            "response": _pipeline_status(
                ingestion=_iso(0.6), signal=_iso(1.6), risk=_iso(2.6), alert=_iso(3.6),
                report=None, alert_awaiting=True,
            ),
        },
        {
            "at_ms": 4000,
            "endpoint": "GET /v1/bridges/{bridge_id}/score-trace",
            "response": {
                "bridge_id": BRIDGE_ID,
                "is_demo": True,
                "assessment_id": 1,
                "risk_score": a.risk_score,
                "severity": a.severity.value,
                "review_status": a.review_status.value,
                "bridge_status": a.severity.value,
                "sensor_offline_note": False,
                "reading": {
                    "sensor_id": row.sensor_id,
                    "value": row.result["value"],
                    "unit": "m/s^2",
                    "sensor_time": _iso(2.0),
                },
                "limit": {
                    "value": row.result["limit_value"],
                    "ratio": row.result["ratio"],
                    "basis_label": row.result["limit_basis"],
                    "is_configured": True,
                },
                "explanation": {
                    "text": a.explanation,
                    "kind": result.explanation_kind.value,
                    "source_label": a.explanation,
                },
            },
        },
        {
            "at_ms": 7000,
            "endpoint": "POST /v1/alerts/{alert_dispatch_id}/approve",
            "response": {
                "alert_dispatch_id": DISPATCH_ID,
                "approval_state": "APPROVED",
                "approved_by": "demo-engineer",
                "approved_at": _iso(7.0),
                "note": None,
                "delivery_state": "QUEUED",
                "notification_status": "not configured",
            },
        },
        {
            "at_ms": 7600,
            "endpoint": "GET /v1/bridges/{bridge_id}/pipeline-status",
            "response": _pipeline_status(
                ingestion=_iso(0.6), signal=_iso(1.6), risk=_iso(2.6), alert=_iso(3.6),
                report=_iso(7.6), alert_awaiting=False,
            ),
        },
    ]

    return {
        "recorded": False,
        "generated_at": _BASE_TIME.isoformat().replace("+00:00", "Z"),
        "generated_by": "scripts/demo/generate_replay_fixtures.py --mode mock",
        "contract_version": "round 4 (2026-10-17)",
        "note": (
            "MOCK fixtures. Slice 1's numbers (reading/limit/ratio/score/severity/explanation) are "
            "real, computed by the actual deterministic scorer. Pipeline-status timings and the "
            "approve response are hand-shaped contract filler because slices 2-4 are not built yet. "
            "Must stay recorded:false until --mode record replaces this with a real run."
        ),
        "bridge_id": BRIDGE_ID,
        "cycle_id": CYCLE_ID,
        "is_demo": True,
        "timeline": timeline,
    }


def _write_json(payload: dict[str, Any]) -> None:
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT_JSON.relative_to(REPO_ROOT)} (recorded={payload['recorded']})")


def run_mock() -> None:
    _write_json(build_mock_timeline())


def run_record() -> None:
    raise NotImplementedError(
        "record mode requires slices 2-4 (background runner, approval, score-trace as an HTTP "
        "endpoint) to exist first. Not implemented yet — see "
        "specs/005-demo-mode-and-approval/spec.md, 'Replay fixtures (round 5)', FR-R.2."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["mock", "record"], default="mock")
    args = parser.parse_args()
    if args.mode == "mock":
        run_mock()
    else:
        run_record()


if __name__ == "__main__":
    main()
