"""Verse host relays: one module per surface the host streams to a client.

The folder had no ``__init__.py``, so ``setuptools.find_packages`` (see
``setup.py``) left it out of every wheel and sdist while ``verse_host.host``
imports ``.relays.chat_tails`` at module load. A source checkout worked and an
installed build crashed on startup with ``ModuleNotFoundError``.
"""
