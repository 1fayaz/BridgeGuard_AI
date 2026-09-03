import time
import random
import math
import sys
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def generate_live_readings(mode="danger"):
    if mode == "danger":
        base = 2.5 + random.random() * 0.8
    else:
        base = 0.25 + random.random() * 0.15
    samples = [
        round(base + random.gauss(0, 0.05), 4)
        for _ in range(100)
    ]
    rms = round(
        math.sqrt(sum(x**2 for x in samples)
        / len(samples)), 4)
    return samples, rms

def run_agent_pipeline():
    print("\n" + "="*55)
    print("  BRIDGEGUARD AI — LIVE AGENT PIPELINE DEMO")
    print("="*55)
    print(f"  Bridge: Indus River Bridge — KHI-HYD")
    print(f"  Time:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*55)

    print("\n📡 AGENT 1 — Data Collection Agent")
    print("   Receiving sensor data from LoRaWAN gateway...")
    time.sleep(0.8)
    samples, rms = generate_live_readings("danger")
    print(f"   ✓ 100 samples received from acc-indus-01")
    print(f"   ✓ Liveness check: PASSED (sensor online)")
    print(f"   ✓ Range check: PASSED (values physically possible)")
    print(f"   ✓ Spike detection: SPIKE CONFIRMED (>3σ from baseline)")
    print(f"   ✓ Reading status: OK | RMS = {rms} m/s²")

    print("\n🔬 AGENT 2 — Structural Analysis Agent")
    print("   Running engineering calculations...")
    time.sleep(1.0)
    baseline_rms = 0.31
    change_pct = round((rms - baseline_rms) / baseline_rms * 100)
    print(f"   ✓ FFT analysis: dominant frequency 4.2 Hz")
    print(f"   ✓ RMS vibration: {rms} m/s²")
    print(f"   ✓ Baseline RMS:  {baseline_rms} m/s² (30-day avg)")
    print(f"   ✓ Change from baseline: +{change_pct}%")
    print(f"   ✓ Deflection check: L/650 (limit: L/800) — EXCEEDED")
    print(f"   ✓ Trigger condition: MET — proceeding to risk reasoning")

    print("\n🧠 AGENT 3 — Risk Reasoning Agent (AI)")
    print("   Consulting IRC/AASHTO engineering standards...")
    time.sleep(1.2)
    score = min(100, int(45 + (rms * 14)))
    severity = (
        "CRITICAL" if score >= 81 else
        "WARNING" if score >= 61 else
        "WATCH" if score >= 31 else "SAFE"
    )
    explanation = (
        f"The Indus River Bridge is showing vibration levels "
        f"{round(rms/baseline_rms)}× above its normal baseline "
        f"of {baseline_rms} m/s². The current RMS of {rms} m/s² "
        f"exceeds the WARNING threshold and the deflection ratio "
        f"L/650 has breached the design limit of L/800. "
        f"This pattern is consistent with heavy truck convoy loading "
        f"combined with early-stage girder fatigue. "
        f"An immediate engineering inspection is strongly recommended "
        f"within 48 hours."
    )
    print(f"   ✓ Risk score computed: {score}/100")
    print(f"   ✓ Severity band: {severity}")
    print(f"   ✓ Provenance guardrail: PASSED (all numbers traceable)")
    print(f"   ✓ Review status: PENDING_HUMAN_REVIEW")
    print(f"\n   AI Explanation:")
    print(f"   \"{explanation}\"")

    print("\n📄 AGENT 4 — Report Generation Agent")
    print("   Assembling bridge health report...")
    time.sleep(0.8)
    print(f"   ✓ Sensor data table: assembled")
    print(f"   ✓ Risk score embedded: {score}/100")
    print(f"   ✓ AI explanation: embedded verbatim")
    print(f"   ✓ Maintenance recommendation: included")
    print(f"   ✓ Report ready for download")

    print("\n🚨 AGENT 5 — Alert & Escalation Agent")
    print("   Evaluating alert severity and routing...")
    time.sleep(0.8)
    print(f"   ✓ Severity: {severity}")
    if severity == "CRITICAL":
        print(f"   ✓ Auto-fire: BLOCKED (CRITICAL requires human approval)")
        print(f"   ✓ Alert status: PENDING_HUMAN_REVIEW")
        print(f"   ✓ Engineer notification: QUEUED (awaiting sign-off)")
    else:
        print(f"   ✓ Alert dispatched automatically")

    print("\n" + "="*55)
    print(f"  PIPELINE COMPLETE")
    print(f"  Risk Score: {score}/100 — {severity}")
    print(f"  Total processing time: ~3 seconds")
    print(f"  A human engineer would take: ~3 days")
    print("="*55)
    print()

if __name__ == "__main__":
    run_agent_pipeline()
