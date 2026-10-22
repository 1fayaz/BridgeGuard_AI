"""The demo sensor's configured design limit (specs/005-demo-mode-and-approval §1.3, FR-1.5).

Structural Analysis has no runner or registry mapping a sensor to an `AnalysisProfile` today — this
feature adds the first one, and it exists for exactly one sensor.

**Keyed by this one sensor's individual id, never by `sensor_type`.** A real bridge may well have
an `accelerometer` too; if this profile were keyed by type, giving the demo type a concrete
`design_limit` would silently hand every real accelerometer the same "demonstration" limit. Keyed
by `sensor_id`, that is structurally impossible — a real sensor's id never matches this one.

The number itself is a round, clearly-synthetic value chosen only so the demo's accelerometer spike
exceeds it — explicitly NOT the `0.5 m/s^2` figure that appeared in old frontend copy, which must
never be reused as if it were a real engineering value. `limit_basis` is what the frontend and the
score-trace response show instead of (or beside) the number, so it is never mistaken for one.
"""
from __future__ import annotations

from typing import Final

from agents.structural_analysis.config.analysis_profiles import AnalysisProfile
from agents.structural_analysis.config.calculations import Calculation

DEMO_SENSOR_ID: Final = "sensor-demo-accel-01"
DEMO_BRIDGE_ID: Final = "bridge-demo-01"
DEMO_MUNICIPALITY_ID: Final = "municipality-demo"

DEMO_DESIGN_LIMIT: Final[float] = 1.0  # m/s^2 — synthetic, chosen only so the demo spike exceeds it.
DEMO_LIMIT_BASIS: Final = "Demonstration limit, not a safety value"

DEMO_ANALYSIS_PROFILE: Final = AnalysisProfile(
    sensor_type="accelerometer",
    calcs=(Calculation.THRESHOLD,),
    design_limit=DEMO_DESIGN_LIMIT,
    limit_basis=DEMO_LIMIT_BASIS,
)
