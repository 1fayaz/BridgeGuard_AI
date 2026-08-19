"""Risk Reasoning Agent (Agent 003) — the judgment layer of BridgeGuard.

The one agent in BridgeGuard that is genuinely a model-calling Agent: it fuses the Structural
Analysis Agent's calculation results, historical baseline, and the applicable engineering
standard into a 0-100 risk score with a plain-language explanation a government engineer acts on.

The SCORE is computed deterministically (see config/score_config.ScoreConfig); the model only
EXPLAINS it. See specs/risk-reasoning-agent/{spec,plan,tasks}.md.
"""
