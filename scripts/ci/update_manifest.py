#!/usr/bin/env python3
"""Write and check the signed update manifest of a desktop release (issue #810).

The in-app updater of a frozen install trusts a release's
``installers-SHA256SUMS.txt`` only when ``installers-update-manifest.json``
names that release's version and the checksum manifest's SHA-256, and an
Ed25519 signature by the release key over the manifest verifies
(``dodaios/core/update_manifest.py``). ``desktop-installers.yml`` writes the
manifest with this script, signs it with ``openssl pkeyutl`` inside the
``release-signing`` environment, and checks the result before it is uploaded:

    python scripts/ci/update_manifest.py build --tag v4.2.0 \\
        --checksums installers/installers-SHA256SUMS.txt \\
        --out installers/installers-update-manifest.json
    python scripts/ci/update_manifest.py check --tag v4.2.0 \\
        --checksums installers/installers-SHA256SUMS.txt \\
        --manifest installers/installers-update-manifest.json

``check`` covers the version and checksum binding; the signature itself is
verified by the workflow with ``openssl`` against
``install/keys/offline-ceremony.pub`` (and, when ``--signature`` is given and
``cryptography`` is importable, with the updater's own verifier too).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dodaios.core.update_manifest import (  # noqa: E402
    UpdateManifestError,
    build_manifest,
    normalize_version,
    parse_manifest,
    verify_update_manifest,
)


def _package_version() -> str:
    import re

    text = (ROOT / "dodaios" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__ = "([^"]+)"', text)
    if match is None:
        raise UpdateManifestError("dodaios/__init__.py has no __version__")
    return match.group(1)


def build(tag: str, checksums: Path, out: Path) -> None:
    version = _package_version()
    if normalize_version(tag) != version:
        raise UpdateManifestError(f"tag {tag} does not match dodaios.__version__ {version}")
    out.write_bytes(build_manifest(version=version, tag=tag, checksums=checksums.read_bytes()))
    print(f"[update-manifest] wrote {out.name} for {tag}")


def check(tag: str, checksums: Path, manifest: Path, signature: Path | None) -> None:
    data = manifest.read_bytes()
    if signature is not None:
        try:
            import cryptography  # noqa: F401
        except ImportError:
            print("[update-manifest] cryptography not installed; signature left to openssl")
        else:
            verify_update_manifest(
                data,
                signature.read_text(encoding="ascii"),
                checksums=checksums.read_bytes(),
                expected_version=tag,
            )
            print("[update-manifest] signature verified with the updater's own verifier")
    parsed = parse_manifest(data)
    expected = build_manifest(version=parsed.version, tag=tag, checksums=checksums.read_bytes())
    if data != expected:
        raise UpdateManifestError(
            f"{manifest.name} does not bind {tag} to {checksums.name} byte for byte"
        )
    print(f"[update-manifest] {manifest.name} binds {tag} to {checksums.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "check"):
        command = sub.add_parser(name)
        command.add_argument("--tag", required=True)
        command.add_argument("--checksums", type=Path, required=True)
        if name == "build":
            command.add_argument("--out", type=Path, required=True)
        else:
            command.add_argument("--manifest", type=Path, required=True)
            command.add_argument("--signature", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            build(args.tag, args.checksums, args.out)
        else:
            check(args.tag, args.checksums, args.manifest, args.signature)
    except (OSError, UpdateManifestError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
