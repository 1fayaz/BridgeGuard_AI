#!/usr/bin/env python3
"""Computes the Overview page's "risk score out of 100" + severity badge for each of the four
named bridge cards, using the REAL deterministic scorer (agents.risk_reasoning.scorer /
.band - the same pure functions the demo pipeline's run_slice1 calls), fed with each card's
REAL ratio_vs_reference from frontend/public/replay/research/*.json. Never hand-typed.

Config choice (ScoreConfig), and why:
  ratio_at_zero_score=1.0   - the research ratio is "this recording's RMS / this structure's own
                              healthy baseline", so 1.0x (identical to the healthy recording) is
                              the true zero-risk point - unlike the truck demo's config, where
                              the ratio is against an absolute engineering limit and 0 is zero-risk.
  ratio_at_full_score=4.0   - reuses this project's own already-published DANGER threshold
                              (ratio > 4.0, see each research JSON's status_rule) as the top of
                              the score scale, rather than inventing a new number.
  watch_min/warning_min/critical_min = 31/61/81
                              - reuses lib/data.ts's existing SEVERITY_CONFIG score ranges
                              (0-30 / 31-60 / 61-80 / 81-100) verbatim, so these cards land on
                              the same scale the rest of the app already displays.

Writes frontend/public/replay/research/overview-scores.json - one entry per research condition
key, each with the real ratio it was computed from, the computed score, and the resulting
severity, so the frontend never re-derives or hand-types these numbers either.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agents.risk_reasoning.band import severity_for  # noqa: E402
from agents.risk_reasoning.config.score_config import ScoreConfig  # noqa: E402
from agents.risk_reasoning.scorer import normalise_ratio  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
RESEARCH_DIR = REPO_ROOT / "frontend" / "public" / "replay" / "research"
OUTPUT_PATH = RESEARCH_DIR / "overview-scores.json"

CONFIG = ScoreConfig(
    score_weights_version="overview-card-v1",
    weights=(("ratio_vs_reference", 1.0),),
    ratio_at_zero_score=1.0,
    ratio_at_full_score=4.0,
    watch_min=31.0,
    warning_min=61.0,
    critical_min=81.0,
)

CONDITION_KEYS = ["safe", "little_moderate", "moderate", "danger"]


def main() -> None:
    out: dict[str, dict] = {}
    for key in CONDITION_KEYS:
        path = RESEARCH_DIR / f"{key}.json"
        if not path.exists():
            print(f"skip {key}: {path} does not exist")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        ratio = data["ratio_vs_reference"]
        result = normalise_ratio(ratio, 1.0, CONFIG)
        if not result.scorable:
            raise RuntimeError(f"{key}: ratio {ratio} was not scorable: {result.reason}")
        band = severity_for(result.score, CONFIG)
        out[key] = {
            "ratio_vs_reference": ratio,
            "risk_score": round(result.score),
            "severity": band.severity.value,
            "computed_with": "agents.risk_reasoning.scorer.normalise_ratio + .band.severity_for",
        }
        print(f"{key}: ratio={ratio:.4f} -> score={round(result.score)} severity={band.severity.value}")

    OUTPUT_PATH.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
