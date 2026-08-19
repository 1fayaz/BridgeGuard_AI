"""Database access for the API layer.

Everything in here exists to make one thing true: a query cannot run without a tenant
scope. `scope.py` holds the only way to obtain a usable handle.
"""
