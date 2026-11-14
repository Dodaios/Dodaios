"""Pictures from files: a node's ``image`` may name a picture on this computer.

A node page runs without network, so a picture has to be inside the page as a
``data:`` URI (:func:`dodaios.nodes.shell.safe_image`). Writing that URI by
hand is out of reach for the assistant: a product screenshot is megabytes of
base64 it would have to carry through its own context. So decks came without
pictures, all text.

Here an ``image`` value that names a local picture file (an absolute path,
``~/…`` or ``file://…``) is read, scaled to what a slide shows and embedded
before the spec is stored. Only real raster pictures are taken (the file must
decode as one); anything else stays as it was, and the type's renderer
refuses it with its own reason.
"""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse
from urllib.request import url2pathname

from dodaios.nodes.shell import MAX_IMAGE_CHARS

log = logging.getLogger(__name__)

#: File endings taken as pictures.
SUFFIXES: Final[frozenset[str]] = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
#: A file larger than this is not read at all.
MAX_FILE_BYTES: Final[int] = 25 * 1024 * 1024
#: The longest side a picture is scaled to (a slide is 1280 x 720).
MAX_SIDE: Final[int] = 1600
#: Keys whose string value is a picture.
_PICTURE_KEYS: Final[frozenset[str]] = frozenset({"image"})


def picture_path(value: Any) -> Path | None:
    """The local file an ``image`` value names, or ``None`` when it names none."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text.startswith("data:"):
        return None
    if text.startswith("file://"):
        text = url2pathname(urlparse(text).path)
    path = Path(text).expanduser() if text.startswith("~") else Path(text)
    if not path.is_absolute():
        return None
    return path if path.suffix.lower() in SUFFIXES else None


def data_url(path: Path) -> str:
    """``path`` as a ``data:`` URI a page can embed, scaled to fit ``MAX_IMAGE_CHARS``.

    Raises ``ValueError`` (with the reason) for a file that is not a picture.
    """
    from PIL import Image, UnidentifiedImageError  # noqa: PLC0415 — only for a file picture

    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"{path} cannot be read ({exc.strerror or exc})") from exc
    if not path.is_file():
        raise ValueError(f"{path} is not a file")
    if size > MAX_FILE_BYTES:
        raise ValueError(f"{path} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
    try:
        with Image.open(path) as opened:
            opened.load()
            picture = opened.copy()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError(f"{path} is not a picture") from exc
    keep_alpha = picture.mode in ("RGBA", "LA") or "transparency" in picture.info
    picture = picture.convert("RGBA" if keep_alpha else "RGB")
    side = MAX_SIDE
    quality = 86
    while True:
        scaled = picture.copy()
        scaled.thumbnail((side, side), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        if keep_alpha:
            scaled.save(buffer, format="PNG", optimize=True)
            mime = "png"
        else:
            scaled.save(buffer, format="JPEG", quality=quality, optimize=True)
            mime = "jpeg"
        encoded = f"data:image/{mime};base64," + base64.b64encode(buffer.getvalue()).decode()
        if len(encoded) <= MAX_IMAGE_CHARS:
            return encoded
        if side <= 480:
            raise ValueError(f"{path} stays too large for a page even when scaled down")
        side = int(side * 0.8)
        quality = max(70, quality - 4)


def embed_pictures(spec: Any) -> tuple[Any, list[str]]:
    """``spec`` with every ``image`` that names a local picture file embedded.

    Returns the new spec and one line per picture that could not be taken,
    for the tool's answer. The spec passed in is not changed.
    """
    problems: list[str] = []

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for key, item in value.items():
                path = picture_path(item) if key in _PICTURE_KEYS else None
                if path is None:
                    out[key] = walk(item)
                    continue
                try:
                    out[key] = data_url(path)
                except ValueError as exc:  # reported back to the model, and logged
                    log.info("node picture not taken: %s", exc)
                    problems.append(str(exc))
                    out[key] = item
            return out
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    return walk(spec), problems


__all__ = ["MAX_FILE_BYTES", "MAX_SIDE", "SUFFIXES", "data_url", "embed_pictures", "picture_path"]
