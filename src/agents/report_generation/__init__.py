"""Report Generation Agent (Agent 004) — the assembly layer of BridgeGuard.

A deterministic Python service (NOT a model-calling Agent — the same Option A as the DCA and
Structural Analysis agents): it turns a completed, persisted risk assessment into a professional,
government-ready report. It ASSEMBLES, it does not re-decide — every number and every sentence in
the report is COPIED from an upstream agent's already-finalized output, never recalculated or
reworded independently.

No model is used anywhere in this package. See specs/report-generation-agent/{spec,plan,tasks}.md.
"""
