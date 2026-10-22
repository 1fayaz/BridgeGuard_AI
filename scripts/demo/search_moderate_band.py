#!/usr/bin/env python3
"""One-shot background search for a REAL daytime (14:00-18:00) Damage State 1
or Damage State 2 recording whose RMS ratio (channel 29, vs the daytime
Reference baseline in prepare_research_data.py) lands in the 2.5-4.0 MODERATE
band. Writes frontend/public/replay/research/moderate.json only if a real
file is found in that band - never fabricates one. Run once; does not loop
or retry forever. Intended to be launched detached and checked once later,
not polled.
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_research_data import (  # noqa: E402
    BASE_URL,
    CHANNEL,
    STATES,
    _fetch_entry,
    _parse_central_directory,
    _range_get,
    classify,
    compute_rms_and_series,
    write_condition_file,
)

HARD_STOP = datetime.datetime(2026, 10, 22, 14, 0, 0)

STATE_SIZES = {
    "little_moderate": 15_296_362_177,  # Damage State 1 archive size (bytes)
    "danger": 18_581_121_867,  # Damage State 2 archive size (bytes)
}


def candidates_for(state_key: str, bitstream_uuid: str, archive_size: int) -> list[dict]:
    url = BASE_URL.format(uuid=bitstream_uuid)
    tail = _range_get(url, archive_size - 70_000, archive_size - 1)
    entries = _parse_central_directory(tail, archive_size - 70_000)
    h5 = [e for e in entries if e["name"].endswith(".h5") and "Messung_Bautzen" in e["name"]]
    out = []
    for e in h5:
        # filename: .../YYYY-MM-DD_Messung_Bautzen_hhmm.h5
        hhmm = e["name"].rsplit("_", 1)[-1].replace(".h5", "")
        try:
            hh = int(hhmm[:2])
        except ValueError:
            continue
        if 14 <= hh < 18:
            out.append(e)
    return sorted(out, key=lambda e: e["name"])


def main() -> None:
    cache_dir = Path(__file__).resolve().parent / ".cache" / "openbridgelab"
    out_dir = Path(__file__).resolve().parents[2] / "frontend" / "public" / "replay" / "research"
    log_path = Path(__file__).resolve().parent / "search_moderate_band.log"
    log = []

    def record(msg: str) -> None:
        print(msg, flush=True)
        log.append(msg)
        log_path.write_text("\n".join(log), encoding="utf-8")

    record(f"Hard stop: {HARD_STOP.isoformat()}")

    ref_state = next(s for s in STATES if s.key == "safe")
    ref_h5 = cache_dir / f"{ref_state.bitstream_uuid}.h5"
    if not ref_h5.exists():
        record("ERROR: reference .h5 not cached - run prepare_research_data.py first")
        return
    reference_rms, _, _ = compute_rms_and_series(ref_h5, CHANNEL)
    record(f"Daytime Reference RMS = {reference_rms:.6f} m/s^2")

    ds1 = next(s for s in STATES if s.key == "little_moderate")
    ds2 = next(s for s in STATES if s.key == "danger")

    all_candidates: list[tuple] = []
    for state, size in ((ds1, STATE_SIZES["little_moderate"]), (ds2, STATE_SIZES["danger"])):
        if datetime.datetime.now() >= HARD_STOP:
            record("Hard stop reached before listing candidates - stopping.")
            return
        cands = candidates_for(state.key, state.bitstream_uuid, size)
        record(f"{state.condition_name}: {len(cands)} real files recorded 14:00-18:00")
        for c in cands:
            all_candidates.append((state, c))

    found = False
    for state, entry in all_candidates:
        if datetime.datetime.now() >= HARD_STOP:
            record("Hard stop reached - no more downloads started. No moderate.json written.")
            break
        safe_name = entry["name"].split("/")[-1]
        h5_path = cache_dir / f"search_{state.key}_{safe_name}"
        url = BASE_URL.format(uuid=state.bitstream_uuid)
        archive_size = STATE_SIZES[state.key]
        try:
            if not h5_path.exists():
                record(f"trying {state.condition_name} {safe_name} ({entry['csize']/1e6:.1f} MB)...")
                _fetch_entry(url, entry, h5_path, archive_size)
            rms, meta, series = compute_rms_and_series(h5_path, CHANNEL)
            ratio = rms / reference_rms
            status = classify(ratio)
            record(f"  {safe_name}: rms={rms:.6f} ratio={ratio:.4f} status={status}")
            if status == "MODERATE":
                out_path = write_condition_file(out_dir, "moderate", state, rms, ratio, status, meta, series)
                record(f"FOUND real MODERATE file: {entry['name']} (ratio {ratio:.4f}) -> wrote {out_path}")
                found = True
                break
        except Exception as ex:
            record(f"  failed on {safe_name}: {ex}")
            continue

    if not found:
        record("No real file in the 14:00-18:00 sample landed in the 2.5-4.0 band (or time ran out). "
               "moderate.json was NOT created.")


if __name__ == "__main__":
    main()
