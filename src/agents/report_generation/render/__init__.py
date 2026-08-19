"""Rendering seam for the Report Generation Agent.

The one [RENDER-DEP] boundary: turning an assembled ReportModel into PDF bytes needs ReportLab +
matplotlib, neither of which is installed. Everything else in the agent is deterministic and
testable without them. `port.RenderPort` is the interface the service depends on; `FakeRenderer`
stands in for tests; the real ReportLab/matplotlib renderer (G602/G603) implements the same port
so swapping it in changes only the produced bytes, never the control flow.
"""
