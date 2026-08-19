"""Authentication for the API layer.

Three credential classes enter; one `Principal` comes out. Everything downstream deals
with the Principal and never with the credential that produced it.
"""
