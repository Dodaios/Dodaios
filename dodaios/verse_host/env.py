"""Read a ``DODAIOS_VERSE_*`` switch the way the app's environment holds it.

Importing ``dodaios`` moves every ``DODAIOS_<NAME>`` variable to
``JARVIS_<NAME>`` (``dodaios/core/env_prefix.py``), so a plain
``os.environ.get("DODAIOS_VERSE_QA")`` never sees what the user set. The verse
host documents and reads the ``DODAIOS_`` names; this helper looks at both
spellings, the ``DODAIOS_`` one first (a test or a late ``os.environ`` write).
"""

from __future__ import annotations

import os

_NEW = "DODAIOS_"
_OLD = "JARVIS_"


def getenv(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value not in (None, ""):
        return value
    if name.startswith(_NEW):
        value = os.environ.get(_OLD + name[len(_NEW) :])
        if value not in (None, ""):
            return value
    return default
