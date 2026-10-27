#!/usr/bin/env python3
"""Give every native installer both of its release names, with identical bytes.

The build names every installer with the current prefix (``Dodaios-``), while
installs frozen before the rename only look for the earlier one
(``PersonalJarvis-``). This runs AFTER signing, so both names always carry the
same signed file.

    python scripts/ci/installer_aliases.py installers
    python scripts/ci/installer_aliases.py --names    # what a release must carry

For every pair in ``release_assets.INSTALLER_NAME_PAIRS`` exactly one file must
exist (it is copied to the other name), or both with identical content. A
pair with neither file, or with two different files, fails.

Sunset: the earlier names are published only while
``release_assets.PUBLISH_EARLIER_INSTALLER_NAMES`` is True (the one switch; its
comment and docs/rename/migration-plan.md give the planned end). With the
switch off this script writes no copies, only checks that every current name
exists, and ``--names`` lists the current names alone, so the checksum
manifest and the release follow without another edit.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci.release_assets import (  # noqa: E402
    INSTALLER_NAME_PAIRS,
    INSTALLERS,
    PUBLISH_EARLIER_INSTALLER_NAMES,
)


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def add_aliases(directory: Path, *, publish_earlier: bool | None = None) -> list[str]:
    """Copy each installer to its missing name; return the names it wrote."""
    if publish_earlier is None:
        publish_earlier = PUBLISH_EARLIER_INSTALLER_NAMES
    written = []
    for current, earlier in INSTALLER_NAME_PAIRS:
        paths = (directory / current, directory / earlier)
        present = [path for path in paths if path.is_file() and not path.is_symlink()]
        if not publish_earlier:
            if paths[0] not in present:
                raise ValueError(f"no installer under its current name: {current}")
            continue
        if not present:
            raise ValueError(f"no installer under either name: {current}, {earlier}")
        if len(present) == 2:
            if _digest(paths[0]) != _digest(paths[1]):
                raise ValueError(f"installer names differ in content: {current} and {earlier}")
            continue
        source = present[0]
        target = paths[1] if source == paths[0] else paths[0]
        if target.exists() or target.is_symlink():
            raise ValueError(f"refusing to replace a non-file installer name: {target.name}")
        shutil.copyfile(source, target)
        if _digest(source) != _digest(target):
            raise ValueError(f"copy of {source.name} does not match its source")
        written.append(target.name)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", type=Path, nargs="?")
    parser.add_argument(
        "--names",
        action="store_true",
        help="print every installer name a release must carry, one per line",
    )
    args = parser.parse_args(argv)
    if args.names:
        print("\n".join(sorted(INSTALLERS)))
        return 0
    if args.directory is None:
        parser.error("the installer directory is required")
    try:
        written = add_aliases(args.directory)
    except (OSError, ValueError) as exc:
        print(f"::error::{exc}")
        return 1
    for name in written:
        print(f"[release] {name}: byte-identical copy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
