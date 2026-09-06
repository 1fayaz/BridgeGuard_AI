"""BridgeGuard sensor simulator — sends scalar RMS values to the ingest endpoint.

Each cycle computes one RMS value from a synthetic 100-sample vibration signal and
POSTs it as a single reading. The backend's ingest pipeline requires scalar floats
(not arrays), so the simulator sends one pre-computed RMS per reading rather than
the raw sample block.

Commands:
    n  →  normal mode   (RMS ~0.3, SAFE band)
    d  →  danger mode   (RMS ~2.8, CRITICAL band)
    q  →  quit
"""
import requests
import time
import random
import math
import sys
import threading
from datetime import datetime, timezone

API_URL = "https://bridge-guard-ai.vercel.app"
API_KEY = "d882d4183f5c348e74234598154b8fb09df890b9eb9c8729"
SENSOR_ID = "acc-indus-hwy-01"

MODE = "normal"


def generate_reading(mode: str) -> tuple[dict, float]:
    """One reading: a scalar RMS computed from a synthetic vibration block."""
    if mode == "normal":
        base = 0.3
        noise = 0.05
    else:
        base = 2.8
        noise = 0.3

    samples = [base + random.gauss(0, noise) for _ in range(100)]
    rms = round(math.sqrt(sum(x * x for x in samples) / len(samples)), 3)

    reading = {
        "sensor_id": SENSOR_ID,
        "sensor_type": "accelerometer",
        "sensor_time": datetime.now(timezone.utc).isoformat(),
        "value": rms,
        "unit": "m/s²",
    }
    return reading, rms


def send_reading(reading: dict) -> int:
    try:
        r = requests.post(
            f"{API_URL}/v1/ingest",
            json={"readings": [reading]},
            headers={"X-API-Key": API_KEY},
            timeout=15,
        )
        return r.status_code
    except Exception as e:
        print(f"  Error: {e}")
        return 0


print("BridgeGuard Sensor Simulator")
print(f"Target: {API_URL}/v1/ingest")
print(f"Sensor: {SENSOR_ID}")
print("Commands: n = normal mode | d = danger mode | q = quit")
print("─────────────────────────────────────────────")


def input_listener():
    global MODE
    while True:
        try:
            cmd = input().strip().lower()
        except EOFError:
            return
        if cmd == "n":
            MODE = "normal"
            print("→ Switched to NORMAL mode")
        elif cmd == "d":
            MODE = "danger"
            print("→ Switched to DANGER mode (triggers alert)")
        elif cmd == "q":
            print("Stopping simulator.")
            sys.exit(0)


t = threading.Thread(target=input_listener, daemon=True)
t.start()

while True:
    reading, rms = generate_reading(MODE)
    status = send_reading(reading)
    if status == 200:
        print(
            f"[OK] [{MODE.upper()}] RMS={rms} -> Dashboard updating at "
            f"https://bridge-guard-ai.vercel.app"
        )
    else:
        print(f"[FAIL] [{MODE.upper()}] RMS={rms} -> HTTP {status}")
    time.sleep(5)
