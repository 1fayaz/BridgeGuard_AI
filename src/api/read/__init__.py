"""Read endpoints (2, 3, 4, 5, 9, 12, 13) — resolve scope, read current rows, project.

One shape for all of them, and the discipline is in what the shape excludes. These modules
read published rows the agents already wrote and audited; they compute nothing. No band
thresholds, no aggregates, no interpolation, no liveness guesses. A number that reaches a
screen from here can be traced back to the row it came from (INV-6), because there is nowhere
in this package it could have been invented instead.
"""
