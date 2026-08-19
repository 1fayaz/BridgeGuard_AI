"""BridgeGuard Data Collection Agent.

First validation checkpoint for incoming IoT sensor data. Deterministic,
no LLM (Constitution Principle IV). Produces a structured per-sensor status
each cycle: OK | OFFLINE | CORRUPT | SPIKE | NO_DATA.
"""
