"""Read-only ports for the Report Generation Agent.

Each port reads finalized rows by identity from an upstream table (risk_assessments 0006 ->
analysis_results 0005 -> validated_readings 0002) and never mutates them. The agent assembles from
what these return; it never re-decides or re-computes upstream facts (FR-1, Principle III).
"""
