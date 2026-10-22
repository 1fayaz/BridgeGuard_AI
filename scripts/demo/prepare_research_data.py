#!/usr/bin/env python3
"""Build frontend/public/replay/research/{safe,little_moderate,moderate,danger}.json
from real, published vibration-monitoring data of ONE real structure.

Dataset (the only one of the three candidates researched that is both legally
redistributable in a public hackathon demo AND gives more than one real,
same-structure severity level):

  "OpenBridgeLAB Output-Only Acceleration Data - Reference State, Damage
   State 1, and Damage State 2"
  Moeller, M.; Juler, T.; Patzelt, A.; Lenzen, A. (I4S / HTWK Leipzig)
  OPARA (TU Dresden research data repository), DOI: 10.25532/OPARA-1548
  https://opara.zih.tu-dresden.de/items/83bdfd26-ecae-452d-86a0-44d7e4958c33
  License: Creative Commons Attribution-NonCommercial-ShareAlike 4.0
  International (CC BY-NC-SA 4.0) - https://creativecommons.org/licenses/by-nc-sa/4.0/
  Suggested citation (constructed - the item page has no pre-formatted "cite
  as" string):
    Moeller, M., Juler, T., Patzelt, A., & Lenzen, A. (2026). OpenBridgeLAB
    Output-Only Acceleration Data - Reference State, Damage State 1, and
    Damage State 2 [Data set]. OPARA. https://doi.org/10.25532/OPARA-1548
    Licensed CC BY-NC-SA 4.0.

NOT used, and why:
  - Z24 benchmark (KU Leuven): has the richest documented damage ladder, but
    its terms require a manual registration request AND state "the data may
    not be transferred to third parties" - incompatible with a public repo
    or public demo deployment. Excluded entirely; no Z24 bytes are fetched
    or embedded anywhere in this project.
  - KW51 railway bridge (Zenodo 3745914, CC-BY-NC-SA-4.0): legally usable,
    but it is a retrofit-monitoring campaign, not a graded damage-severity
    benchmark, and is a DIFFERENT structure - "use only one structure per
    card; never combine data from different bridges." Not used.

Time-of-day finding (why the baseline is the DAYTIME Reference recording):
  A second real Reference-State file, recorded at night (2025-04-29 23:29),
  has RMS = 0.000303 m/s^2 on channel 29 - about 10x quieter than the daytime
  Reference recording (2025-04-29 15:56, RMS = 0.004495 m/s^2). Ambient
  excitation (traffic, wind, pedestrians) is much lower at night, so RMS
  swings with time of day independent of any damage. Using the night file as
  "the" baseline would make DS1/DS2 look far more severe than the damage
  alone explains. The daytime recording is used as the Reference baseline,
  and the status rule is phrased as "a similar time of day" rather than
  "the Reference recording", full stop, to keep that caveat visible on the
  card. The night reading is recorded in NIGHT_REFERENCE_NOTE below and
  echoed into every output file so the limitation isn't hidden.

Severity rule (stated once, applied mechanically - see STATUS_RULE below):
  ratio = RMS(this window, channel 29) / RMS(daytime Reference window, channel 29)
  ratio <= 1.5          -> SAFE
  1.5  < ratio <= 2.5   -> LITTLE MODERATE
  2.5  < ratio <= 4.0   -> MODERATE
  ratio > 4.0           -> DANGER

Channel 29 was chosen, not any channel, because the dataset's own datasheet
(Table 6, sensor-position map) places channel 29 in "Field 2" = Span 2 - the
span Damage State 1 physically damaged. Channel 12 is excluded project-wide
per the datasheet's own reliability note ("reduced reliability ... especially
during the night").

Only conditions with a REAL recording get a JSON file. As of this run:
  safe.json            <- Reference State, daytime recording (ratio 1.00)
  little_moderate.json <- Damage State 1, first recording (ratio ~2.49)
  danger.json           <- Damage State 2, first recording (ratio ~5.79)
There is no moderate.json yet - no real file in hand lands in the 2.5-4.0
band. search_moderate_band.py (same technique, run separately/in the
background) looks for a real daytime DS1 or DS2 file that does. If one is
found, it is added the same way, from a real file, never fabricated. If none
is found, moderate.json stays absent - no card is invented for it.
"""
from __future__ import annotations

import json
import struct
import sys
import urllib.request
import zlib
from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np

DATASET_NAME = "OpenBridgeLAB Output-Only Acceleration Data - Reference State, Damage State 1, and Damage State 2"
DATASET_AUTHORS = "Moeller, M.; Juler, T.; Patzelt, A.; Lenzen, A. (I4S / HTWK Leipzig)"
DATASET_YEAR = 2026
DATASET_LINK = "https://opara.zih.tu-dresden.de/items/83bdfd26-ecae-452d-86a0-44d7e4958c33"
DATASET_DOI = "https://doi.org/10.25532/OPARA-1548"
DATASET_LICENSE = "CC BY-NC-SA 4.0 (Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International)"
DATASET_LICENSE_URL = "https://creativecommons.org/licenses/by-nc-sa/4.0/"
DATASET_CITATION = (
    "Moeller, M., Juler, T., Patzelt, A., & Lenzen, A. (2026). OpenBridgeLAB "
    "Output-Only Acceleration Data - Reference State, Damage State 1, and Damage "
    "State 2 [Data set]. OPARA. https://doi.org/10.25532/OPARA-1548. "
    "Licensed CC BY-NC-SA 4.0."
)

CHANNEL = 29  # 1-based, per the dataset's own datasheet channel numbering (Field 2 / Span 2)
SAMPLE_RATE_HZ = 1000  # confirmed from the datasheet (downsampled from an original 10 kHz)
UNIT = "m/s^2"  # datasheet: "data is in [m/s^2], all quantification factors and sensitivities are already factored in"

SERIES_STRIDE = 1000  # 1000 raw samples (1s @ 1kHz) per plotted point -> 600 points for a 600s window

STATUS_RULE = (
    "Status is calculated by BridgeGuard AI: the RMS is compared with this structure's own "
    "healthy recording from a similar time of day. 1.5x or less = safe, 1.5x to 2.5x = little "
    "moderate, 2.5x to 4x = moderate, above 4x = danger. These thresholds (1.5 / 2.5 / 4.0) are "
    "BridgeGuard AI's own choice, not values from the OpenBridgeLAB paper. Never compared "
    "against a fixed absolute limit - always against this same structure's own baseline."
)

NIGHT_REFERENCE_NOTE = (
    "A second real Reference State recording, taken at night (2025-04-29 23:29), measured RMS "
    "= 0.000303 m/s^2 on channel 29 - about 10x quieter than the daytime Reference recording "
    "used as the baseline here (2025-04-29 15:56, RMS = 0.004495 m/s^2). Ambient excitation "
    "(traffic, wind, pedestrians) is much lower at night, so time of day matters and this is "
    "why a daytime baseline was used rather than an arbitrary single Reference file."
)


def classify(ratio: float) -> str:
    if ratio <= 1.5:
        return "SAFE"
    if ratio <= 2.5:
        return "LITTLE MODERATE"
    if ratio <= 4.0:
        return "MODERATE"
    return "DANGER"


@dataclass
class StateSpec:
    key: str  # output filename stem: "safe" | "little_moderate" | "moderate" | "danger"
    condition_name: str  # "Reference State" | "Damage State 1" | "Damage State 2"
    bitstream_uuid: str
    damage_note: str


STATES = [
    StateSpec(
        "safe",
        "Reference State",
        "a6ee23b8-6223-4684-997e-d1eb6b0a5fc2",
        "Undamaged bridge configuration. Daytime recording (see NIGHT_REFERENCE_NOTE for why).",
    ),
    StateSpec(
        "little_moderate",
        "Damage State 1",
        "4ead3923-b404-4e5d-b180-3e81a6ac80f5",
        "Damage introduced in Span 2 (Field 2) - the span channel 29 is on.",
    ),
    StateSpec(
        "danger",
        "Damage State 2",
        "d8c3d26f-58cd-438c-8bd5-82b2e505a82b",
        "Additional damage introduced in Span 1 (Field 1), on top of Damage State 1's Span 2 damage.",
    ),
]

BASE_URL = "https://opara.zih.tu-dresden.de/bitstreams/{uuid}/download"


def _range_get(url: str, start: int, end: int) -> bytes:
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def _content_length(url: str) -> int:
    req = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        content_range = resp.headers.get("Content-Range", "")
    if "/" in content_range:
        return int(content_range.rsplit("/", 1)[-1])
    raise RuntimeError(f"server did not return Content-Range for {url}")


def _parse_central_directory(tail: bytes, tail_start: int) -> list[dict]:
    """Parse a ZIP's central directory out of its tail bytes (handles ZIP64)."""
    eocd_sig = b"PK\x05\x06"
    idx = tail.rfind(eocd_sig)
    if idx == -1:
        raise RuntimeError("EOCD not found - tail window too small")
    zip64_loc_sig = b"PK\x06\x07"
    loc_idx = tail.rfind(zip64_loc_sig)
    if loc_idx != -1 and loc_idx < idx:
        (_, _, zip64_eocd_offset, _) = struct.unpack("<IIQI", tail[loc_idx : loc_idx + 20])
        rel = zip64_eocd_offset - tail_start
        (_, _, _, _, _, _, _, _total_entries, cd_size, cd_offset) = struct.unpack(
            "<IQHHIIQQQQ", tail[rel : rel + 56]
        )
    else:
        (_, _, _, _, _total_entries, cd_size, cd_offset, _) = struct.unpack(
            "<IHHHHIIH", tail[idx : idx + 22]
        )
    rel_cd = cd_offset - tail_start
    cd = tail[rel_cd : rel_cd + cd_size]

    entries = []
    pos = 0
    while pos < len(cd):
        if cd[pos : pos + 4] != b"PK\x01\x02":
            break
        (_, _, _, _, method, _, _, _, csize, usize, nlen, elen, clen, _, _, _, lho) = struct.unpack(
            "<IHHHHHHIIIHHHHHII", cd[pos : pos + 46]
        )
        name = cd[pos + 46 : pos + 46 + nlen].decode("utf-8", "replace")
        extra = cd[pos + 46 + nlen : pos + 46 + nlen + elen]
        real_lho, real_csize, real_usize = lho, csize, usize
        if lho == 0xFFFFFFFF or csize == 0xFFFFFFFF or usize == 0xFFFFFFFF:
            epos = 0
            while epos < len(extra):
                eid, esize = struct.unpack("<HH", extra[epos : epos + 4])
                if eid == 0x0001:
                    body = extra[epos + 4 : epos + 4 + esize]
                    bpos = 0
                    if usize == 0xFFFFFFFF:
                        real_usize = struct.unpack("<Q", body[bpos : bpos + 8])[0]
                        bpos += 8
                    if csize == 0xFFFFFFFF:
                        real_csize = struct.unpack("<Q", body[bpos : bpos + 8])[0]
                        bpos += 8
                    if lho == 0xFFFFFFFF:
                        real_lho = struct.unpack("<Q", body[bpos : bpos + 8])[0]
                epos += 4 + esize
        entries.append({"name": name, "method": method, "csize": real_csize, "usize": real_usize, "lho": real_lho})
        pos += 46 + nlen + elen + clen
    return entries


def fetch_first_measurement(bitstream_uuid: str, cache_dir: Path) -> Path:
    """Return a local .h5 path for the chronologically-first ambient measurement
    in this state's archive, downloading only that one entry's bytes (not the
    whole multi-GB zip) via HTTP Range requests. Cached - safe to re-run."""
    url = BASE_URL.format(uuid=bitstream_uuid)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{bitstream_uuid}.h5"
    if cached.exists():
        return cached

    size = _content_length(url)
    tail_window = 70_000
    tail = _range_get(url, size - tail_window, size - 1)
    entries = _parse_central_directory(tail, size - tail_window)

    h5_entries = sorted(e for e in entries if e["name"].endswith(".h5") and "Messung_Bautzen" in e["name"])
    if not h5_entries:
        raise RuntimeError(f"no ambient measurement .h5 files found in {url}")
    entry = h5_entries[0]  # chronologically first, by filename's YYYY-MM-DD_hhmm sort order
    return _fetch_entry(url, entry, cached, size)


def _fetch_entry(url: str, entry: dict, cached: Path, archive_size: int) -> Path:
    raw = _range_get(url, entry["lho"], entry["lho"] + entry["csize"] + 300)
    if raw[0:4] != b"PK\x03\x04":
        raise RuntimeError("local file header signature mismatch - offset calculation is wrong")
    (_, _, method, _, _, _, _csize2, _usize2, nlen, elen) = struct.unpack("<HHHHHIIIHH", raw[4:30])
    data_start = 30 + nlen + elen
    compressed = raw[data_start : data_start + entry["csize"]]
    if method != 8:
        raise RuntimeError(f"unexpected compression method {method} (expected DEFLATE)")
    decompressed = zlib.decompressobj(-15).decompress(compressed)
    cached.write_bytes(decompressed)
    print(f"  fetched {entry['name']} ({len(decompressed)/1e6:.1f} MB actual data, not the {archive_size/1e9:.1f} GB archive)")
    return cached


def compute_rms_and_series(h5_path: Path, channel: int, stride: int = SERIES_STRIDE) -> tuple[float, dict, dict]:
    with h5py.File(h5_path, "r") as f:
        ds = f["RecBuff"]
        arr = ds[:]
        attrs = dict(ds.attrs)
    # row 0 = timestamp (microseconds); rows 1..32 = channels 1..32
    t_us = arr[0]
    row = arr[channel]
    rms = float(np.sqrt(np.mean(np.square(row))))  # computed from the FULL, un-decimated recording
    meta = {
        "date": str(attrs.get("Datum", "")),
        "duration_s": float(np.ravel(attrs.get("Messdauer", [0]))[0]),
        "excitation": str(attrs.get("Anregung", "")),
        "project": str(attrs.get("Projektname", "")),
    }
    series = {
        "time_s": [round(float(x) / 1e6, 3) for x in t_us[::stride]],
        "value": [round(float(x), 6) for x in row[::stride]],
        "note": (
            f"Downsampled by simple decimation (every {stride}th of {len(row)} raw samples, "
            f"~{len(row)//stride} points) for plotting only. RMS and ratio above are computed "
            f"from the full, un-decimated recording, not from this series."
        ),
    }
    return rms, meta, series


def write_condition_file(out_dir: Path, key: str, state: StateSpec, rms: float, ratio: float, status: str, meta: dict, series: dict) -> Path:
    payload = {
        "dataset": {
            "name": DATASET_NAME,
            "authors": DATASET_AUTHORS,
            "year": DATASET_YEAR,
            "link": DATASET_LINK,
            "doi": DATASET_DOI,
            "license": DATASET_LICENSE,
            "license_url": DATASET_LICENSE_URL,
            "citation": DATASET_CITATION,
        },
        "condition": state.condition_name,
        "damage_note": state.damage_note,
        "sensor": {
            "channel": CHANNEL,
            "channel_location": "Field 2 / Span 2 (per the dataset's own sensor-position table, Table 6 of the datasheet)",
            "sensor_model": "PCB393A03 uniaxial piezoelectric accelerometer",
            "sampling_rate_hz": SAMPLE_RATE_HZ,
            "unit": UNIT,
        },
        "window": {
            "measurement_date": meta["date"],
            "duration_s": meta["duration_s"],
            "excitation": meta["excitation"],
            "project": meta["project"],
        },
        "time_series": series,
        "rms": rms,
        "ratio_vs_reference": ratio,
        "status_rule": STATUS_RULE,
        "status": status,
        "night_reference_note": NIGHT_REFERENCE_NOTE,
        "selection_note": "Recordings selected to represent condition levels.",
    }
    out_path = out_dir / f"{key}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    cache_dir = Path(__file__).resolve().parent / ".cache" / "openbridgelab"
    out_dir = Path(__file__).resolve().parents[2] / "frontend" / "public" / "replay" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)

    # moderate.json (2.5-4.0 band) is written only by search_moderate_band.py, from a real
    # found file (see that script) - this script never touches it, so a real find survives
    # re-runs of this script.
    computed = {}
    for state in STATES:
        print(f"[{state.key}] {state.condition_name}: locating + fetching one real measurement ...")
        h5_path = fetch_first_measurement(state.bitstream_uuid, cache_dir)
        rms, meta, series = compute_rms_and_series(h5_path, CHANNEL)
        computed[state.key] = {"state": state, "rms": rms, "meta": meta, "series": series}
        print(f"  RMS(channel {CHANNEL}) = {rms:.6f} {UNIT}  [{meta['date']}, {meta['duration_s']:.0f}s, {meta['excitation']}]")

    reference_rms = computed["safe"]["rms"]

    print()
    print("Computed ratios vs daytime Reference State:")
    for key in ("safe", "little_moderate", "danger"):
        c = computed[key]
        ratio = c["rms"] / reference_rms
        status = classify(ratio)
        c["ratio"] = ratio
        c["status"] = status
        print(f"  {key:16s} ({c['state'].condition_name:16s}) ratio={ratio:.4f}  rule says {status}")

    for key in ("safe", "little_moderate", "danger"):
        c = computed[key]
        out_path = write_condition_file(out_dir, key, c["state"], c["rms"], c["ratio"], c["status"], c["meta"], c["series"])
        print(f"wrote {out_path}")

    print()
    print(
        "No moderate.json written in this run - no real file in hand lands in the 2.5-4.0 band. "
        "Run search_moderate_band.py to look for one (real file only, never fabricated)."
    )


if __name__ == "__main__":
    sys.exit(main())
