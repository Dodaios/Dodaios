"""Download the CC0 human base mesh bundle into the cache and verify its SHA-256.

Runs in any Python 3 (standard library only), including Blender's:
    python art/verse/characters/fetch_base.py
"""

from __future__ import annotations

import hashlib
import urllib.request
import zipfile
from pathlib import Path

URL = (
    "https://download.blender.org/demo/asset-bundles/human-base-meshes/"
    "human-base-meshes-bundle-v1.4.1.zip"
)
SHA256 = "811f43accbb31a88266d932f8f5563b2d13586fca0ba2693aad1f5fe582b3515"
DEST = Path(__file__).resolve().parent.parent / ".cache" / "characters" / "download"


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    archive = DEST / URL.rsplit("/", 1)[1]
    if not archive.is_file():
        print(f"downloading {URL}")
        urllib.request.urlretrieve(URL, archive)  # noqa: S310 (fixed https URL)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != SHA256:
        raise SystemExit(f"checksum mismatch for {archive}: {digest}")
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            target = (DEST / name).resolve()
            if not str(target).startswith(str(DEST.resolve())):
                raise SystemExit(f"unsafe path in archive: {name}")
        z.extractall(DEST)
    print(f"ok: {DEST}")


if __name__ == "__main__":
    main()
