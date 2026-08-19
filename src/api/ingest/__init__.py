"""Ingestion (endpoint 1) — shape-check, append, ack. Never validate.

The boundary's guarantee here is narrow on purpose: *raw is durable* plus a per-reading
shape outcome. It does not promise the readings are good. Validity is the Data Collection
Agent's verdict, reached on its own 1-5 minute cycle (Principle III, plan §4).
"""
