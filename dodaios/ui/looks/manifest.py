"""The ``look.json`` manifest of a look pack (format ``dodaios-look/1``).

A look is a folder with ``look.json``, an HTML entry page, a preview picture
and the files the page loads (``docs/looks.md``). The page only ever runs
inside a sandboxed frame; this module owns the rules a manifest must satisfy.

Every rejection raises :class:`LookManifestError` with a short, user-readable
English sentence, because the message reaches the settings page verbatim.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

LOOK_FORMAT = "dodaios-look/1"

#: A look id: a lowercase slug. Ids are matched before they touch the disk.
LOOK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,47}$")

#: Ids no pack may take: ``orb`` is the built-in voice orb.
RESERVED_IDS = frozenset({"orb", "none", "default"})

#: A file path inside the pack: forward slashes, no dot segments, no drive.
_SEGMENT = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}"
_REL_PATH_RE = re.compile(rf"^(?:{_SEGMENT}/){{0,4}}{_SEGMENT}$")

_VERSION_RE = re.compile(r"^\d{1,4}\.\d{1,4}\.\d{1,4}$")
_SPDX_RE = re.compile(r"^[A-Za-z0-9.+-]{2,40}(?: (?:AND|OR) [A-Za-z0-9.+-]{2,40}){0,3}$")

#: File kinds a pack may hold, by lowercase suffix, with the media type the
#: server sends. Anything else makes the pack invalid.
ALLOWED_TYPES: Mapping[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".bin": "application/octet-stream",
    ".ktx2": "image/ktx2",
    ".hdr": "application/octet-stream",
    ".woff2": "font/woff2",
    ".wasm": "application/wasm",
}

PREVIEW_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".svg"})

#: Limits of one pack on disk.
MAX_PACK_BYTES = 25 * 1024 * 1024
MAX_PACK_FILES = 300
MAX_MANIFEST_BYTES = 16 * 1024

MAX_NAME_CHARS = 40
MAX_DESCRIPTION_CHARS = 200
MAX_AUTHOR_CHARS = 60
MAX_ATTRIBUTION_CHARS = 200
MAX_HOMEPAGE_CHARS = 200


class LookManifestError(ValueError):
    """A look pack breaks a rule of the ``dodaios-look/1`` format."""


@dataclass(frozen=True)
class LookManifest:
    """A validated ``look.json``."""

    id: str
    name: str
    description: str
    author: str
    version: str
    license: str
    entry: str
    preview: str
    attribution: str = ""
    homepage: str = ""
    builtin: bool = False

    def to_public(self) -> dict[str, Any]:
        """The fields the settings page and the marketplace show."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "author": self.author,
            "version": self.version,
            "license": self.license,
            "attribution": self.attribution,
            "homepage": self.homepage,
            "builtin": self.builtin,
        }


def is_safe_rel_path(value: object) -> bool:
    """True for a relative pack path such as ``assets/core.glb``."""
    if not isinstance(value, str) or not _REL_PATH_RE.match(value):
        return False
    return all(part not in {".", ".."} for part in value.split("/"))


def suffix_of(rel_path: str) -> str:
    dot = rel_path.rfind(".")
    return rel_path[dot:].lower() if dot > rel_path.rfind("/") else ""


def _text(data: Mapping[str, Any], key: str, limit: int, *, required: bool) -> str:
    value = data.get(key, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise LookManifestError(f"'{key}' must be text.")
    value = value.strip()
    if required and not value:
        raise LookManifestError(f"look.json needs a '{key}'.")
    if len(value) > limit:
        raise LookManifestError(f"'{key}' is longer than {limit} characters.")
    if any(ord(ch) < 32 for ch in value):
        raise LookManifestError(f"'{key}' contains control characters.")
    return value


def parse_manifest(data: object, *, builtin: bool = False) -> LookManifest:
    """Validate a decoded ``look.json``; raise :class:`LookManifestError`."""
    if not isinstance(data, Mapping):
        raise LookManifestError("look.json must hold one JSON object.")
    if data.get("format") != LOOK_FORMAT:
        raise LookManifestError(f'look.json must say "format": "{LOOK_FORMAT}".')

    look_id = data.get("id")
    if not isinstance(look_id, str) or not LOOK_ID_RE.match(look_id):
        raise LookManifestError(
            "'id' must be 2 to 48 lowercase letters, digits or dashes, "
            "starting with a letter or digit."
        )
    if look_id in RESERVED_IDS:
        raise LookManifestError(f"The id '{look_id}' is reserved.")

    version = _text(data, "version", 14, required=True)
    if not _VERSION_RE.match(version):
        raise LookManifestError("'version' must look like 1.0.0.")

    license_id = _text(data, "license", 120, required=True)
    if not _SPDX_RE.match(license_id):
        raise LookManifestError("'license' must be an SPDX license id such as Apache-2.0.")

    entry = data.get("entry", "index.html")
    if not is_safe_rel_path(entry) or suffix_of(entry) != ".html":
        raise LookManifestError("'entry' must be a relative path to an .html file in the pack.")

    preview = data.get("preview")
    if not is_safe_rel_path(preview) or suffix_of(preview) not in PREVIEW_SUFFIXES:
        raise LookManifestError(
            "'preview' must be a relative path to a .png, .jpg, .webp or .svg file."
        )

    homepage = _text(data, "homepage", MAX_HOMEPAGE_CHARS, required=False)
    if homepage and not homepage.startswith("https://"):
        raise LookManifestError("'homepage' must start with https://.")

    return LookManifest(
        id=look_id,
        name=_text(data, "name", MAX_NAME_CHARS, required=True),
        description=_text(data, "description", MAX_DESCRIPTION_CHARS, required=False),
        author=_text(data, "author", MAX_AUTHOR_CHARS, required=True),
        version=version,
        license=license_id,
        entry=entry,
        preview=preview,
        attribution=_text(data, "attribution", MAX_ATTRIBUTION_CHARS, required=False),
        homepage=homepage,
        builtin=builtin,
    )
