"""Where a release keeps the files its updater has to find.

An update is applied by the PREVIOUS version's code: the detached restart
helper resets the checkout to the new revision, runs that revision's installer
and then has to verify and start a tree it has never seen. Every location it
needs for that is stated by the tree itself in ``install/update-contract.json``,
so a release may move its package, its launcher or its config file and still be
reachable from the version before it.

A tree without the file — every release before the file existed — is described
by :data:`DEFAULT_CONTRACT`, which holds exactly the locations those releases
use. The same answer is given for a file this version cannot trust: an unknown
schema, malformed JSON, or a value that is not a plain relative location.
Falling back is the fail-closed choice: the update then looks for the UI bundle
in the default place, does not find it, and rolls back to the previous revision.

Standard library only and no I/O at import time — the restart helper loads this
module, and it must stay a throwaway process.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, replace
from pathlib import Path

from jarvis.core.branding import CONFIG_FILE_NAME, MACOS_APP_DIR_NAME, MACOS_BUNDLE_ID

log = logging.getLogger(__name__)

__all__ = [
    "CONTRACT_PATH",
    "CONTRACT_SCHEMA",
    "DEFAULT_CONTRACT",
    "UpdateContract",
    "VERSION_PATTERN",
    "parse_update_contract",
    "read_update_contract",
]

#: Location of the contract inside a checkout, POSIX-style so the same string
#: addresses the file on disk and at a git revision (``git show <rev>:<path>``).
CONTRACT_PATH = "install/update-contract.json"
CONTRACT_SCHEMA = 1

#: How the version is written in a release's version file. Fixed here rather
#: than read from the contract: a pattern taken from the target tree would be a
#: regular expression this process runs on someone else's say-so.
VERSION_PATTERN = r'__version__\s*=\s*"([^"]+)"'

# A contract is a handful of short lines; anything larger is not one.
_MAX_CONTRACT_BYTES = 16_384

_RELATIVE_PATH_RE = re.compile(r"^(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+$")
_FILE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_APP_DIR_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]*\.app$")
_BUNDLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*(\.[A-Za-z0-9][A-Za-z0-9-]*)+$")
_MAX_VALUE_LENGTH = 240


@dataclass(frozen=True)
class UpdateContract:
    """The locations one release publishes for the updater of the one before."""

    #: Directory holding the built web UI (``index.html`` plus ``assets/``).
    ui_bundle_dir: str = "jarvis/ui/web/dist"
    #: Module ``python -m`` runs to start the desktop app.
    launcher_module: str = "jarvis.ui.web.launcher"
    #: File whose ``__version__ = "..."`` line names the release.
    version_file: str = "jarvis/__init__.py"
    #: Name of the user's config file in the checkout root.
    config_file: str = CONFIG_FILE_NAME
    #: Directory name of the macOS application bundle the installer builds.
    macos_app_dir_name: str = MACOS_APP_DIR_NAME
    #: ``CFBundleIdentifier`` of that bundle. A bundle of the right name with
    #: another identifier is a different app and is never started in its place.
    macos_bundle_id: str = MACOS_BUNDLE_ID
    #: Script the release wants run when its install failed and the checkout is
    #: about to return to the previous revision - the place to undo what its
    #: installer changed outside the checkout. Run as
    #: ``<checkout python> <hook> <previous revision> <target revision>`` with
    #: the checkout as working directory, while the release's own tree is still
    #: checked out. It must be a file the release tracks; a non-zero exit or a
    #: timeout is logged and the rollback continues.
    rollback_hook: str | None = None


DEFAULT_CONTRACT = UpdateContract()


def _is_relative_path(value: object) -> bool:
    """A POSIX path that stays inside the checkout it is resolved against."""
    if not isinstance(value, str) or len(value) > _MAX_VALUE_LENGTH:
        return False
    if not _RELATIVE_PATH_RE.fullmatch(value):
        return False
    return all(segment not in {".", ".."} for segment in value.split("/"))


def _is_file_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= _MAX_VALUE_LENGTH
        and bool(_FILE_NAME_RE.fullmatch(value))
        and value not in {".", ".."}
    )


def _is_module_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= _MAX_VALUE_LENGTH
        and bool(_MODULE_RE.fullmatch(value))
    )


def _is_app_dir_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= _MAX_VALUE_LENGTH
        and bool(_APP_DIR_NAME_RE.fullmatch(value))
    )


def _is_bundle_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= _MAX_VALUE_LENGTH
        and bool(_BUNDLE_ID_RE.fullmatch(value))
    )


def _is_rollback_hook(value: object) -> bool:
    return value is None or (_is_relative_path(value) and str(value).endswith(".py"))


_FIELD_CHECKS = (
    ("ui_bundle_dir", _is_relative_path),
    ("launcher_module", _is_module_name),
    ("version_file", _is_relative_path),
    ("config_file", _is_file_name),
    ("macos_app_dir_name", _is_app_dir_name),
    ("macos_bundle_id", _is_bundle_id),
    ("rollback_hook", _is_rollback_hook),
)


def parse_update_contract(text: str) -> UpdateContract:
    """Validate one contract document; anything doubtful is the default contract.

    A key the document leaves out keeps its default, so a release states only
    what it moved. A key this version does not know is ignored. One invalid
    value rejects the whole document: a contract that is half believed could
    point the bundle check at one tree layout and the launcher at another.
    """
    try:
        payload = json.loads(text)
    except (ValueError, TypeError, RecursionError):
        log.warning("update contract is not valid JSON; using the default locations")
        return DEFAULT_CONTRACT
    if not isinstance(payload, dict):
        log.warning("update contract is not a JSON object; using the default locations")
        return DEFAULT_CONTRACT
    schema = payload.get("schema")
    if type(schema) is not int or schema != CONTRACT_SCHEMA:
        # A newer schema may mean the same keys differently. The default
        # locations are the only ones this version can vouch for.
        log.warning(
            "update contract schema %r is not %d; using the default locations",
            schema,
            CONTRACT_SCHEMA,
        )
        return DEFAULT_CONTRACT

    stated: dict[str, str | None] = {}
    for name, is_valid in _FIELD_CHECKS:
        if name not in payload:
            continue
        value = payload[name]
        if not is_valid(value):
            log.warning(
                "update contract has an invalid %s; using the default locations", name
            )
            return DEFAULT_CONTRACT
        stated[name] = value
    return replace(DEFAULT_CONTRACT, **stated)


def read_update_contract(root: str | Path) -> UpdateContract:
    """The contract of the tree currently checked out at ``root``."""
    path = Path(root) / CONTRACT_PATH
    try:
        with path.open("rb") as stream:
            raw = stream.read(_MAX_CONTRACT_BYTES + 1)
    except OSError:
        # Absent in every release before the file existed, and in any
        # directory that is not a checkout (a frozen build's config folder).
        return DEFAULT_CONTRACT
    if len(raw) > _MAX_CONTRACT_BYTES:
        log.warning("update contract at %s is too large; using the default locations", path)
        return DEFAULT_CONTRACT
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        log.warning("update contract at %s is not UTF-8; using the default locations", path)
        return DEFAULT_CONTRACT
    return parse_update_contract(text)
