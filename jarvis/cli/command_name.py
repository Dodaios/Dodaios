"""The command name help text and hints should show.

The app answers to ``dodaios`` and to its earlier names (``jarvis``,
``personal-jarvis``). A usage line or a "run this next" hint is most useful
when it repeats the name the person actually typed, so the entry points ask
here: the earlier name when the process was started under one, ``dodaios``
otherwise (``python -m jarvis``, the frozen executable, a launcher).

Standard library and ``jarvis.core.branding`` only: ``dodaios update`` imports
this before anything heavy is loaded.
"""

from __future__ import annotations

import sys
from pathlib import Path

from jarvis.core.branding import CLI_COMMAND_NAME, LEGACY_CLI_COMMAND_NAMES


def main_command(argv0: str | None = None) -> str:
    """``dodaios``, or the earlier command name this process was started under."""
    stem = Path(sys.argv[0] if argv0 is None else argv0).stem.lower()
    return stem if stem in LEGACY_CLI_COMMAND_NAMES else CLI_COMMAND_NAME


__all__ = ["main_command"]
