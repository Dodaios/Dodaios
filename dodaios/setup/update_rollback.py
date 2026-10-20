"""Undo, before a failed update rolls back, what this release's installer moved.

The updater of the release before this one runs this file when this release
failed to install (``rollback_hook`` in ``install/update-contract.json``), as
``<checkout python> dodaios/setup/update_rollback.py <previous> <target>``
while this release is still checked out, and then returns the checkout to
``<previous>`` and runs that revision's installer.

This release's installer renames the macOS app bundle to its current name
(``dodaios.setup.macos_app_bundle.rename_legacy_macos_app_bundles``). The
revision the update falls back to may only know the bundle under an earlier
name: its installer would not find the app, build a second one under that
name and leave two apps in Launchpad. So the bundle gets back the name the
previous revision's own update contract states, or the first earlier name when
that revision predates the contract. The same rules as the forward rename
apply: one ``os.rename``, only this install's bundle, never over another app.

Never fails the rollback: every problem is logged and the exit code is 0.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    # Run as a file, not as a module: the checkout itself is not on the path.
    sys.path.insert(0, str(_ROOT))

from dodaios.core.branding import (  # noqa: E402 - bootstrap source path above
    LEGACY_MACOS_APP_DIR_NAMES,
    MACOS_APP_DIR_NAME,
    MACOS_BUNDLE_ID,
)
from dodaios.core.update_contract import (  # noqa: E402 - bootstrap source path above
    CONTRACT_PATH,
    parse_update_contract,
)

log = logging.getLogger(__name__)

GitShow = Callable[[Path, str], str | None]


def _git_show(root: Path, spec: str) -> str | None:
    """``git show <spec>`` in ``root``; ``None`` when git has no such file."""
    try:
        result = subprocess.run(
            ["git", "show", spec],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("Could not run git show %s in %s: %s", spec, root, exc)
        return None
    return result.stdout if result.returncode == 0 else None


def previous_macos_app_dir_name(
    root: Path, previous: str, *, git_show: GitShow = _git_show
) -> str:
    """The bundle name the revision ``previous`` looks for.

    A revision without a contract predates every rename and uses the first
    earlier name. A contract this version cannot read leaves the bundle as it
    is: the current name is the answer that renames nothing.
    """
    document = git_show(root, f"{previous}:{CONTRACT_PATH}")
    if document is None:
        return LEGACY_MACOS_APP_DIR_NAMES[0]
    return parse_update_contract(document).macos_app_dir_name


def restore_macos_app_bundle_name(name: str, roots: Sequence[Path]) -> list[Path]:
    """Rename this install's bundle from the current name back to ``name``.

    Only to an earlier name of ours, only a bundle whose ``Info.plist`` names
    the managed bundle id, never over anything that already has that name.
    Returns the bundles now under ``name``.
    """
    if name == MACOS_APP_DIR_NAME or name not in LEGACY_MACOS_APP_DIR_NAMES:
        return []
    from dodaios.setup.macos_app_bundle import _bundle_identifier

    restored: list[Path] = []
    for root in roots:
        source = root / MACOS_APP_DIR_NAME
        target = root / name
        try:
            if source.is_symlink() or not source.is_dir():
                continue
            if _bundle_identifier(source) != MACOS_BUNDLE_ID:
                continue
            if target.exists() or target.is_symlink():
                log.warning("Keeping %s: %s already exists.", source, target)
                continue
            os.rename(source, target)
        except OSError as exc:
            log.warning("Could not rename %s back to %s: %s", source, target, exc)
            continue
        log.info("Renamed the macOS app %s back to %s for the rollback.", source, target)
        restored.append(target)
    return restored


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if sys.platform != "darwin" or not args:
        return 0
    logging.basicConfig(level=logging.INFO, format="update rollback: %(message)s")
    try:
        from dodaios.autostart.macos import retarget_launch_agent
        from dodaios.setup.macos_app_bundle import (
            SYSTEM_APPLICATIONS_DIR,
            user_applications_dir,
        )

        name = previous_macos_app_dir_name(_ROOT, args[0])
        roots = (SYSTEM_APPLICATIONS_DIR, user_applications_dir())
        for bundle in restore_macos_app_bundle_name(name, roots):
            # The login item names the bundle by path; the previous revision
            # only follows a path under its own name.
            retarget_launch_agent(bundle)
    except Exception:  # noqa: BLE001 - the rollback itself must go on
        log.exception("Could not restore the macOS app's earlier name")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
