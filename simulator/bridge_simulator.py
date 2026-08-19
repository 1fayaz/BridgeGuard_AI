import requests
import time
import random
import math
import sys
from datetime import datetime, timezone

API_URL = "https://bridgeguard-api.onrender.com"
API_KEY = "your-pi-device-key-here"
SENSOR_ID = "acc-ravi-01"

MODE = "normal"

def generate_block(mode: str) -> dict:
    if mode == "normal":
        base = 0.3
        noise = 0.05
    else:
        base = 2.8
        noise = 0.3

    samples = [
        round(base + random.gauss(0, noise), 4)
        for _ in range(100)
    ]

    return {
        "sensor_id": SENSOR_ID,
        "sensor_type": "accelerometer",
        "sensor_time": datetime.now(timezone.utc).isoformat(),
        "value": samples,
        "sample_rate_hz": 100,
        "sample_count": 100,
        "unit": "m/s²",
        "declared_sample_rate_hz": 100,
        "declared_sample_count": 100,
    }

def send_block(block: dict) -> int:
    try:
        r = requests.post(
            f"{API_URL}/v1/ingest",
            json={"readings": [block]},
            headers={"X-API-Key": API_KEY},
            timeout=10,
        )
        return r.status_code
    except Exception as e:
        print(f"  Error: {e}")
        return 0

def wake_server():
    print("Waking up server (takes up to 60 seconds)...")
    for i in range(12):
        try:
            r = requests.get(f"{API_URL}/v1/health", timeout=10)
            if r.status_code == 200:
                print("Server is awake. Ready.")
                return
        except:
            pass
        print(f"  Waiting... ({(i+1)*5}s)")
        time.sleep(5)
    print("Server may still be starting. Continuing anyway.")

print("BridgeGuard Sensor Simulator")
print("Commands: n = normal mode | d = danger mode | q = quit")
print("─────────────────────────────────────────────")

wake_server()

import threading

def input_listener():
    global MODE
    while True:
        cmd = input().strip().lower()
        if cmd == "n":
            MODE = "normal"
            print(f"→ Switched to NORMAL mode")
        elif cmd == "d":
            MODE = "danger"
            print(f"→ Switched to DANGER mode (triggers alert)")
        elif cmd == "q":
            print("Stopping simulator.")
            sys.exit(0)

t = threading.Thread(target=input_listener, daemon=True)
t.start()

while True:
    block = generate_block(MODE)
    status = send_block(block)
    rms = round((sum(x**2 for x in block["value"]) / len(block["value"])) ** 0.5, 3)
    print(f"[{MODE.upper()}] RMS={rms} m/s² → HTTP {status}")
    time.sleep(5)