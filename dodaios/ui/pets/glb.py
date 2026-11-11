"""The few checks a ``.glb`` upload has to pass before it is stored.

The desktop player reads the meshes. This only checks that the file is a
glTF binary and lists the clip names a ``pet.json`` is allowed to name.
"""

from __future__ import annotations

import json
import struct

from dodaios.ui.pets.manifest import PetManifestError

#: File name written for every uploaded model. The upload's own name is ignored.
MODEL_FILE = "model.glb"

#: Upper bound of one model file, in bytes.
MAX_MODEL_BYTES = 8 * 1024 * 1024


def animation_names(data: bytes) -> set[str]:
    """Clip names in a ``.glb``. Raises :class:`PetManifestError` when it is not one."""
    if not isinstance(data, bytes | bytearray) or len(data) < 20 or data[:4] != b"glTF":
        raise PetManifestError("The model must be a .glb file.")
    if len(data) > MAX_MODEL_BYTES:
        raise PetManifestError("The model is larger than 8 MB.")
    length = struct.unpack_from("<I", data, 8)[0]
    if length > len(data):
        raise PetManifestError("The model file is truncated.")
    off = 12
    gltf: dict | None = None
    while off + 8 <= length:
        size, kind = struct.unpack_from("<II", data, off)
        chunk = data[off + 8 : off + 8 + size]
        off += 8 + size
        if kind == 0x4E4F534A:  # JSON
            try:
                parsed = json.loads(chunk)
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise PetManifestError("The model file could not be read.") from exc
            if isinstance(parsed, dict):
                gltf = parsed
    if gltf is not None:
        _reject_external_media(gltf)
    if gltf is None or not gltf.get("meshes"):
        raise PetManifestError("The model file has no mesh.")
    names: set[str] = set()
    for anim in gltf.get("animations") or []:
        if isinstance(anim, dict) and isinstance(anim.get("name"), str) and anim["name"]:
            names.add(anim["name"])
    if not names:
        raise PetManifestError("The model file has no clips.")
    return names


def _reject_external_media(gltf: dict) -> None:
    """A non-empty ``uri`` is a file the viewer would fetch. The bytes have to be in the GLB."""
    for key in ("buffers", "images"):
        entries = gltf.get(key) or []
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or "uri" not in entry:
                continue
            uri = entry["uri"]
            if uri is None or uri == "":
                continue
            raise PetManifestError("The model cannot reference an external buffer or image.")
