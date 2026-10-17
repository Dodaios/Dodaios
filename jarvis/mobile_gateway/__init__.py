"""The phone app's gateway: pinned TLS, one-time pairing, per-device keys.

The web UI never leaves loopback. The phone talks to this narrow API instead,
on its own port, and can only do what the routes in :mod:`.app` allow.
"""
