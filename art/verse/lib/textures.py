"""CC0 texture and HDRI cache backed by the Poly Haven public API.

Standard library only, so it runs inside Blender and outside it:

    from lib import textures
    paths = textures.ensure("metal_plate_02", ["Diffuse", "nor_gl", "Rough"], res="2k")
    paths["Rough"]  # Path to .../.cache/textures/metal_plate_02/metal_plate_02_rough_2k.jpg

Files land in `art/verse/.cache/textures/<asset>/` (git-ignored; the resolution
is part of every file name). Each download is checked against the API's MD5,
then recorded once in `art/verse/LICENSES.md` with its URL and SHA-256 (the
ledger is shared with the kit and append-only).

API terms (https://github.com/Poly-Haven/Public-API/blob/master/ToS.md): free
for any use; every request carries this pipeline's own User-Agent. The assets
are CC0. Map keys are Poly Haven's ("Diffuse", "nor_gl", "Rough", "arm",
"AO", "Displacement", "Metal", "Bump"; "hdri" for HDRIs).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
from collections.abc import Iterable
from pathlib import Path

API = "https://api.polyhaven.com"
PAGE = "https://polyhaven.com/a/{asset}"
USER_AGENT = "dodaios-verse-pipeline/1.0 (build-time CC0 asset cache)"
VERSE_ROOT = Path(__file__).resolve().parents[1]
CACHE = VERSE_ROOT / ".cache" / "textures"
LEDGER = VERSE_ROOT / "LICENSES.md"
LEDGER_HEADER = (
    "# Third-party content ledger\n\n"
    "Every third-party file used by the Verse cook. CC0 only. Append-only.\n\n"
    "| Asset | File | License | Source URL | SHA-256 |\n"
    "|---|---|---|---|---|\n"
)
# Data maps keep full precision in PNG; colour, normal and roughness maps use JPG.
LOSSLESS_MAPS = {"Displacement"}


def _get(url: str, timeout: float = 120.0) -> bytes:
    if not url.startswith(("https://api.polyhaven.com/", "https://dl.polyhaven.org/")):
        raise ValueError(f"refusing to fetch outside Poly Haven: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed hosts
        return response.read()


def _files(asset: str) -> dict:
    """The API's file listing for `asset`, cached next to the downloads."""
    cached = CACHE / asset / "files.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    listing = json.loads(_get(f"{API}/files/{asset}"))
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(listing), encoding="utf-8")
    return listing


def _format_preference(key: str) -> tuple[str, ...]:
    if key == "hdri":
        return ("hdr", "exr")
    return ("png", "jpg") if key in LOSSLESS_MAPS else ("jpg", "png")


def _pick(listing: dict, key: str, res: str, fmt: str | None) -> dict:
    if key not in listing:
        raise KeyError(f"map {key!r} not offered; available: {sorted(listing)}")
    by_res = listing[key]
    if res not in by_res:
        raise KeyError(f"{key}: resolution {res!r} not offered; available: {sorted(by_res)}")
    formats = by_res[res]
    if fmt is None:
        fmt = next((f for f in _format_preference(key) if f in formats), None)
    if fmt not in formats:
        raise KeyError(f"{key} {res}: format {fmt!r} not offered; available: {sorted(formats)}")
    return formats[fmt]


def _download(entry: dict, destination: Path) -> None:
    data = _get(entry["url"], timeout=600.0)
    if hashlib.md5(data).hexdigest() != entry["md5"]:  # noqa: S324 - upstream checksum
        raise RuntimeError(f"checksum mismatch for {entry['url']}")
    partial = destination.with_suffix(destination.suffix + ".part")
    partial.write_bytes(data)
    os.replace(partial, destination)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _record(asset: str, path: Path, url: str) -> None:
    """Append one ledger row unless the URL is already recorded."""
    lock = LEDGER.with_suffix(".lock")
    deadline = time.monotonic() + 30
    while True:
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() > deadline:
                raise TimeoutError(f"ledger lock {lock} held for 30 s") from None
            time.sleep(0.1)
    try:
        text = LEDGER.read_text(encoding="utf-8") if LEDGER.exists() else ""
        if url in text:
            return
        page = PAGE.format(asset=asset)
        row = f"| {asset} ({page}) | {path.name} | CC0 | {url} | {_sha256(path)} |\n"
        with LEDGER.open("a", encoding="utf-8") as ledger:
            if not text:
                ledger.write(LEDGER_HEADER)
            elif not text.endswith("\n"):
                ledger.write("\n")
            ledger.write(row)
    finally:
        os.close(handle)
        os.unlink(lock)


def ensure(
    asset: str,
    maps: Iterable[str] = ("Diffuse", "nor_gl", "Rough"),
    res: str = "2k",
    fmt: str | None = None,
) -> dict[str, Path]:
    """Download (once) the requested maps of a Poly Haven asset; return map -> local path."""
    listing = _files(asset)
    folder = CACHE / asset
    paths: dict[str, Path] = {}
    for key in maps:
        entry = _pick(listing, key, res, fmt)
        destination = folder / entry["url"].rsplit("/", 1)[-1]
        if not destination.exists():
            _download(entry, destination)
        _record(asset, destination, entry["url"])
        paths[key] = destination
    return paths


def ensure_hdri(asset: str, res: str = "2k") -> Path:
    """Download (once) a Poly Haven HDRI as Radiance .hdr; return its path."""
    return ensure(asset, ["hdri"], res=res, fmt="hdr")["hdri"]
