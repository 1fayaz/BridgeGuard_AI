"""Read-only data-source tools for the Risk Reasoning Agent (FR-3).

Three distinct read-only retrievals — calculation results, historical baseline, engineering
standard — each a plain injectable function over a source protocol. The @function_tool decoration
and SDK wiring are applied in R701; keeping the read logic pure here makes it testable without the
SDK (whose top-level import name `agents` collides with this repo's own `agents` package).
"""
