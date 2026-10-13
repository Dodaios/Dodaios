"""``DODAIOS_`` is the prefix to write; ``JARVIS_`` is the prefix the code reads.

Every variable the app reads is spelled ``JARVIS_<NAME>`` in the code
(``JARVIS__<SECTION>__<KEY>`` for a config override, ``JARVISCTL_<NAME>`` for
the control CLI). People and scripts may write ``DODAIOS_<NAME>``,
``DODAIOS__<SECTION>__<KEY>`` and ``DODAIOSCTL_<NAME>`` instead. No reader
changes: :func:`adopt_environment` runs once, when the ``jarvis`` package is
first imported, and moves every new-prefix variable to the name the readers
use before any of them runs.

Precedence
----------
* Only the ``DODAIOS_`` name is set: its value becomes the ``JARVIS_`` value.
* Both are set to the same value, or the ``DODAIOS_`` one is blank: the
  ``JARVIS_`` value stands.
* Both are set to different values: **the ``DODAIOS_`` name wins**, and one line
  names the variable (never its value).

Why the new name is moved, not mirrored
---------------------------------------
After the adoption the process environment holds one spelling, the one all
existing code is written against. Keeping (or adding) a ``DODAIOS_`` twin beside
every ``JARVIS_`` variable would break two things that work today:

* **Scrubbing.** Code that starts an external tool removes credentials from the
  child's environment by name (``JARVIS_CONTROL_API_KEY`` before a vendor CLI
  starts). A twin under a second name would carry the same credential past it.
* **Overrides.** The app sets, replaces and deletes ``JARVIS_`` variables for
  its children: its own data directory for a worker, a one-shot marker dropped
  before a restart, a persisted override re-read from the registry. A child
  that still saw the twin's earlier value, and let the new name win, would undo
  each of those.

So a child process and a plugin read the ``JARVIS_`` name; they never see a
``DODAIOS_`` one, whoever set it.

Standard library only and no I/O besides the environment: this runs before
logging exists and on every process start. ``packaging/pyinstaller_rthook_frozen.py``
cannot import the package and carries a copy of :func:`_adopt`;
``tests/unit/core/test_env_prefix.py`` holds the two copies identical.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping

# (prefix to write, prefix the code reads). No prefix is the start of another:
# ``DODAIOSCTL_X`` does not begin with ``DODAIOS_``.
_PREFIXES = (("DODAIOS_", "JARVIS_"), ("DODAIOSCTL_", "JARVISCTL_"))

#: Config overrides (``<PREFIX>_<SECTION>__<KEY>``) under the two prefixes.
CONFIG_ENV_PREFIX = f"{_PREFIXES[0][0]}_"
LEGACY_CONFIG_ENV_PREFIX = f"{_PREFIXES[0][1]}_"


def _adopt(environ):
    """Move every new-prefix variable to the name the code reads; return the clashing names."""
    clashes = []
    for name in list(environ):
        for new_prefix, old_prefix in _PREFIXES:
            if not name.startswith(new_prefix) or name == new_prefix:
                continue
            value = environ.pop(name)
            old_name = old_prefix + name[len(new_prefix) :]
            if value:
                if environ.get(old_name) not in (None, "", value):
                    clashes.append(name)
                environ[old_name] = value
            elif old_name not in environ:
                environ[old_name] = value
            break
    return clashes


def old_name_of(new_name: str) -> str | None:
    """The name the code reads for a new-prefix variable, ``None`` for any other name."""
    for new_prefix, old_prefix in _PREFIXES:
        if new_name.startswith(new_prefix) and new_name != new_prefix:
            return old_prefix + new_name[len(new_prefix) :]
    return None


def accepted_names(name: str) -> tuple[str, ...]:
    """Every spelling of a variable the code reads, the one that wins first.

    For a reader of something that is not the process environment (a ``.env``
    file) and therefore never passed through :func:`adopt_environment`.
    """
    for new_prefix, old_prefix in _PREFIXES:
        if name.startswith(old_prefix) and name != old_prefix:
            return (new_prefix + name[len(old_prefix) :], name)
    return (name,)


def adopt_environment(environ: MutableMapping[str, str] | None = None) -> tuple[str, ...]:
    """Run the adoption on ``environ`` (the process environment by default).

    Returns the new-prefix names that were set to a different value than the
    variable the code reads, and won. Safe to call again: after one pass there
    is no new-prefix variable left to move.
    """
    clashes = tuple(_adopt(os.environ if environ is None else environ))
    if clashes:
        # Imported only now: a clash is rare, and ``import jarvis`` stays light.
        import logging

        log = logging.getLogger(__name__)
        for new_name in clashes:
            log.warning(
                "%s and %s are set to different values; using %s.",
                new_name,
                old_name_of(new_name),
                new_name,
            )
    return clashes


__all__ = [
    "CONFIG_ENV_PREFIX",
    "LEGACY_CONFIG_ENV_PREFIX",
    "accepted_names",
    "adopt_environment",
    "old_name_of",
]
