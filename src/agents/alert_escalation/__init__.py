"""Alert & Escalation Agent (Agent 005) — the real-world-action chokepoint.

A deterministic Python service (Option A, like the DCA/SA/Report agents — NOT a model-calling
Agent). It consumes a completed, persisted risk assessment (the Risk Agent's verdict) and turns it
into notifications dispatched to humans (email/SMS), escalating until the alert is confirmed
handled. It is the single place BridgeGuard touches the outside world, so it is the single place
the human-approval gate (`needs_approval`) lives (Principle I; Risk FR-5).

It NOTIFIES and ESCALATES; it never re-judges. The verdict — score, severity, recommendation, and
its verbatim explanation — was already decided and audited upstream by Agent 003. This agent copies
that verdict, decides the dispatch tier from the settled severity->approval mapping, gates real-world
dispatch behind human approval, dispatches, escalates, and logs. No model anywhere.
"""
