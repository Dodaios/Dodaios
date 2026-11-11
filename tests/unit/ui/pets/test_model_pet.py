"""A model pet is a pet.json plus a GLB. The cube cat is the built-in one."""

from __future__ import annotations

import json
import struct

import pytest

from dodaios.ui.pets.glb import animation_names
from dodaios.ui.pets.loader import builtin_root, read_manifest
from dodaios.ui.pets.manifest import PetManifestError, parse_manifest
from dodaios.ui.pets.states import MODEL_PET_FORMAT, PET_STATES
from dodaios.ui.pets.store import PetStore


def _glb(document: dict) -> bytes:
    payload = json.dumps(document).encode()
    payload += b" " * ((4 - len(payload) % 4) % 4)
    chunk = struct.pack("<II", len(payload), 0x4E4F534A) + payload
    return b"glTF" + struct.pack("<II", 2, 12 + len(chunk)) + chunk


def _embedded_model(**replace: object) -> bytes:
    document: dict = {
        "meshes": [{"primitives": [{}]}],
        "animations": [{"name": "idle"}],
        "buffers": [{}],
        "images": [{"bufferView": 0}],
    }
    document.update(replace)
    return _glb(document)


def test_embedded_buffers_and_images_load() -> None:
    assert animation_names(_embedded_model()) == {"idle"}
    empty = _embedded_model(buffers=[{"uri": ""}], images=[{"uri": "", "bufferView": 0}])
    assert animation_names(empty) == {"idle"}


def test_an_external_buffer_or_image_uri_is_refused() -> None:
    remote = _embedded_model(buffers=[{"uri": "https://evil.example/buf.bin"}])
    relative = _embedded_model(images=[{"uri": "cat.png"}])
    with pytest.raises(PetManifestError, match="external"):
        animation_names(remote)
    with pytest.raises(PetManifestError, match="external"):
        animation_names(relative)


def test_cube_cat_pack_names_every_clip() -> None:
    folder = builtin_root() / "cube-cat"
    manifest = read_manifest(folder, builtin=True)
    assert manifest.kind == "model"
    assert manifest.model == "model.glb"
    assert manifest.options.height == 0.7
    assert manifest.options.aim == 0.62
    names = animation_names((folder / "model.glb").read_bytes())
    assert {manifest.clip_for(state) for state in PET_STATES} <= names
    assert manifest.to_json()["format"] == MODEL_PET_FORMAT


def test_options_can_be_omitted() -> None:
    manifest = parse_manifest(
        {
            "format": MODEL_PET_FORMAT,
            "id": "cube-cat",
            "name": "Dog",
            "description": "A dog.",
            "model": "model.glb",
            "animations": {"idle": "idle"},
        },
        builtin=True,
    )
    assert manifest.options.eye == (1.05, 0.55, 1.9)
    assert manifest.clip_for("talking") == "idle"


def test_a_bad_clip_name_is_refused() -> None:
    with pytest.raises(PetManifestError, match="clip"):
        parse_manifest(
            {
                "format": MODEL_PET_FORMAT,
                "id": "cube-cat",
                "name": "Dog",
                "description": "A dog.",
                "animations": {"idle": "../run"},
            },
            builtin=True,
        )


def test_upload_stores_the_pack(tmp_path) -> None:
    glb = (builtin_root() / "cube-cat" / "model.glb").read_bytes()
    body = {
        "format": MODEL_PET_FORMAT,
        "name": "Cube Dog",
        "description": "A blocky dog.",
        "animations": {"idle": "idle", "searching": "run"},
        "options": {"height": 0.5},
    }
    manifest = PetStore(tmp_path).add_model(
        glb=glb, manifest_json=json.dumps(body), name="Cube Dog", description="A blocky dog."
    )
    stored = read_manifest(tmp_path / manifest.id, builtin=False)
    assert stored.model == "model.glb"
    assert stored.clip_for("searching") == "run"
    assert stored.options.height == 0.5
    assert (tmp_path / manifest.id / "model.glb").read_bytes() == glb
