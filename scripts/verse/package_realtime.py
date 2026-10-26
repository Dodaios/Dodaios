"""Realtime package step (outside Blender): raw realtime export -> runtime files.

Turns `lib.realtime.export_realtime()` output (lightmap pages, reflection
panoramas, geometry chunks, realtime.json) into

    public/verse/decks/<id>/realtime/scene.glb       meshopt-compressed glTF, one node per chunk
    public/verse/decks/<id>/realtime/lm_<page>.webp  lightmap pages, RGBM ("rgbm2") in RGBA WebP
    public/verse/decks/<id>/realtime/probe_<room>.webp  reflection panoramas, same encoding

and the manifest's `realtime` block (schema verse.deck/1, optional). The
folder is replaced atomically and the deck's plate content stays untouched.
Format: docs/verse/realtime.md.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
REALTIME_DIR = "realtime"
VERSION = 1
ENCODING = "rgbm2"
LM_QUALITY = 90
PROBE_QUALITY = 94
MESHOPT_SCRIPT = Path(__file__).with_name("meshopt_pack.mjs")

# glTF constants
BYTE, UNSIGNED_SHORT, SHORT, UNSIGNED_INT = 5120, 5123, 5122, 5125
ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963


def _load_lightmap():
    path = REPO_ROOT / "art" / "verse" / "lib" / "lightmap.py"
    spec = importlib.util.spec_from_file_location("verse_lightmap", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


lightmap = _load_lightmap()


# ---------------------------------------------------------------- images


def write_rgbm_webp(radiance: np.ndarray, path: Path, span: float, quality: int) -> None:
    """Encode linear HDR RGB as "rgbm2" in an RGBA WebP: lossy colour, lossless alpha."""
    rgba = lightmap.rgbm_encode(radiance, span)
    Image.fromarray(rgba, mode="RGBA").save(
        path, format="WEBP", quality=quality, alpha_quality=100, method=6, exact=True
    )


# ---------------------------------------------------------------- geometry


def _quantise(chunk: dict, arrays) -> dict:
    """Quantised vertex streams of one chunk (KHR_mesh_quantization layout).

    Positions: int16 with one uniform scale and an offset (the node's
    transform), so world normals stay correct; normals: int8 normalised;
    lightmap UV: uint16 normalised, glTF orientation (v down).
    """
    index = chunk["index"]
    pos = np.asarray(arrays[f"{index}_pos"], dtype=np.float64)
    nrm = np.asarray(arrays[f"{index}_nrm"], dtype=np.float64)
    uv = np.asarray(arrays[f"{index}_uv"], dtype=np.float64)
    idx = np.asarray(arrays[f"{index}_idx"], dtype=np.uint32)
    low, high = pos.min(axis=0), pos.max(axis=0)
    scale = max(float((high - low).max()), 1e-4) / 65534.0
    offset = low + 32767.0 * scale
    q = np.clip(np.round((pos - offset) / scale), -32767, 32767).astype(np.int16)
    positions = np.zeros((len(pos), 4), dtype=np.int16)
    positions[:, :3] = q
    normals = np.zeros((len(nrm), 4), dtype=np.int8)
    normals[:, :3] = np.clip(np.round(nrm * 127.0), -127, 127).astype(np.int8)
    uvs = np.stack([uv[:, 0], 1.0 - uv[:, 1]], axis=1)
    uvs = np.clip(np.round(uvs * 65535.0), 0, 65535).astype(np.uint16)
    return {
        "positions": positions,
        "normals": normals,
        "uvs": uvs,
        "indices": idx,
        "translation": [float(v) for v in offset],
        "scale": scale,
        "qmin": [int(v) for v in q.min(axis=0)],
        "qmax": [int(v) for v in q.max(axis=0)],
    }


def _meshopt(quantised: list[dict], work: Path) -> tuple[dict, bytes]:
    """Run the Node meshopt encoder over every chunk; returns (layout, encoded bytes)."""
    blob = bytearray()
    primitives = []

    def add(data: np.ndarray) -> int:
        at = len(blob)
        blob.extend(np.ascontiguousarray(data).tobytes())
        blob.extend(b"\0" * ((4 - len(blob) % 4) % 4))
        return at

    for q in quantised:
        primitives.append(
            {
                "vertexCount": len(q["positions"]),
                "indexCount": len(q["indices"]),
                "indexOffset": add(q["indices"]),
                "streams": [
                    {"offset": add(q["positions"]), "stride": 8},
                    {"offset": add(q["normals"]), "stride": 4},
                    {"offset": add(q["uvs"]), "stride": 4},
                ],
            }
        )
    (work / "in.json").write_text(json.dumps({"primitives": primitives}), encoding="utf-8")
    (work / "in.bin").write_bytes(bytes(blob))
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is required for the realtime package step (meshopt encoder)")
    subprocess.run(
        [
            node,
            str(MESHOPT_SCRIPT),
            str(work / "in.json"),
            str(work / "in.bin"),
            str(work / "out.json"),
            str(work / "out.bin"),
        ],
        check=True,
    )
    layout = json.loads((work / "out.json").read_text(encoding="utf-8"))
    return layout, (work / "out.bin").read_bytes()


def write_glb(chunks: list[dict], arrays, path: Path, work: Path) -> dict:
    """Write the chunks as one meshopt-compressed GLB; returns its stats."""
    quantised = [_quantise(chunk, arrays) for chunk in chunks]
    layout, encoded = _meshopt(quantised, work)
    materials = sorted({chunk["material"] for chunk in chunks})
    gltf: dict = {
        "asset": {"version": "2.0", "generator": "Dodaios Verse realtime export"},
        "extensionsUsed": ["EXT_meshopt_compression", "KHR_mesh_quantization"],
        "extensionsRequired": ["EXT_meshopt_compression", "KHR_mesh_quantization"],
        "scene": 0,
        "scenes": [{"nodes": list(range(len(chunks)))}],
        "nodes": [],
        "meshes": [],
        "materials": [{"name": name} for name in materials],
        "accessors": [],
        "bufferViews": [],
    }
    fallback = 0

    def view(stream: dict, count: int, stride: int, mode: str, target: int) -> int:
        nonlocal fallback
        length = count * stride
        entry = {
            "buffer": 1,
            "byteOffset": fallback,
            "byteLength": length,
            "target": target,
            "extensions": {
                "EXT_meshopt_compression": {
                    "buffer": 0,
                    "byteOffset": stream["offset"],
                    "byteLength": stream["length"],
                    "byteStride": stride,
                    "count": count,
                    "mode": mode,
                }
            },
        }
        if mode == "ATTRIBUTES":
            entry["byteStride"] = stride
        fallback += (length + 3) // 4 * 4
        gltf["bufferViews"].append(entry)
        return len(gltf["bufferViews"]) - 1

    def accessor(**fields) -> int:
        gltf["accessors"].append(fields)
        return len(gltf["accessors"]) - 1

    vertices = triangles = 0
    for chunk, q, prim in zip(chunks, quantised, layout["primitives"], strict=True):
        count = prim["vertexCount"]
        pos_s, nrm_s, uv_s = prim["streams"]
        position = accessor(
            bufferView=view(pos_s, count, 8, "ATTRIBUTES", ARRAY_BUFFER),
            componentType=SHORT,
            count=count,
            type="VEC3",
            min=q["qmin"],
            max=q["qmax"],
        )
        normal = accessor(
            bufferView=view(nrm_s, count, 4, "ATTRIBUTES", ARRAY_BUFFER),
            componentType=BYTE,
            normalized=True,
            count=count,
            type="VEC3",
        )
        texcoord = accessor(
            bufferView=view(uv_s, count, 4, "ATTRIBUTES", ARRAY_BUFFER),
            componentType=UNSIGNED_SHORT,
            normalized=True,
            count=count,
            type="VEC2",
        )
        size = prim["indexSize"]
        indices = accessor(
            bufferView=view(
                prim["index"], prim["indexCount"], size, "TRIANGLES", ELEMENT_ARRAY_BUFFER
            ),
            componentType=UNSIGNED_SHORT if size == 2 else UNSIGNED_INT,
            count=prim["indexCount"],
            type="SCALAR",
        )
        gltf["meshes"].append(
            {
                "name": f"RT_{chunk['index']}",
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": position,
                            "NORMAL": normal,
                            "TEXCOORD_0": texcoord,
                        },
                        "indices": indices,
                        "material": materials.index(chunk["material"]),
                    }
                ],
            }
        )
        gltf["nodes"].append(
            {
                "name": f"RT_{chunk['index']}",
                "mesh": len(gltf["meshes"]) - 1,
                "translation": q["translation"],
                "scale": [q["scale"]] * 3,
                "extras": {
                    "material": chunk["material"],
                    "room": chunk["room"],
                    "page": chunk["page"],
                },
            }
        )
        vertices += count
        triangles += prim["indexCount"] // 3
    gltf["buffers"] = [
        {"byteLength": len(encoded)},
        {"byteLength": fallback, "extensions": {"EXT_meshopt_compression": {"fallback": True}}},
    ]
    _write_glb_file(path, gltf, encoded)
    return {"vertices": vertices, "triangles": triangles, "chunks": len(chunks)}


def _write_glb_file(path: Path, gltf: dict, binary: bytes) -> None:
    text = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    text += b" " * ((4 - len(text) % 4) % 4)
    binary = binary + b"\0" * ((4 - len(binary) % 4) % 4)
    total = 12 + 8 + len(text) + 8 + len(binary)
    with path.open("wb") as handle:
        handle.write(struct.pack("<4sII", b"glTF", 2, total))
        handle.write(struct.pack("<I4s", len(text), b"JSON"))
        handle.write(text)
        handle.write(struct.pack("<I4s", len(binary), b"BIN\0"))
        handle.write(binary)


# ---------------------------------------------------------------- package


def _bytes(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())


def package_realtime(raw_dir: Path, deck_dir: Path, extra_stats: dict | None = None) -> dict:
    """Write `<deck_dir>/realtime/` from the raw export and add the manifest block.

    The deck must already be cooked (its manifest exists). Everything is
    written to `realtime.staging` first and swapped in at the end.
    """
    started = time.monotonic()
    manifest_path = deck_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"{manifest_path} missing: cook the deck's plate first")
    raw = json.loads((raw_dir / "realtime.json").read_text(encoding="utf-8"))
    staging = deck_dir / f"{REALTIME_DIR}.staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        block = _write_realtime(raw_dir, staging, raw)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    target = deck_dir / REALTIME_DIR
    if target.exists():
        shutil.rmtree(target)
    staging.rename(target)
    block["bytes"] = _bytes(target)
    block["stats"].update(extra_stats or {})
    block["stats"]["package_s"] = round(time.monotonic() - started, 2)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["realtime"] = block
    for _ in range(3):  # the byte count includes the manifest that states it
        manifest_path.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
        manifest["stats"]["bytes"] = _bytes(deck_dir)
    manifest_path.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return block


def _write_realtime(raw_dir: Path, out_dir: Path, raw: dict) -> dict:
    peak = max(page["max"] for page in raw["pages"])
    span = lightmap.rgbm_range(peak)
    pages = []
    for index, page in enumerate(raw["pages"]):
        radiance = np.load(raw_dir / page["file"]).astype(np.float32)
        name = f"lm_{index}.webp"
        write_rgbm_webp(radiance, out_dir / name, span, LM_QUALITY)
        pages.append(
            {
                "url": f"{REALTIME_DIR}/{name}",
                "size": int(radiance.shape[0]),
                "density": page["density"],
            }
        )
    probes = []
    for probe in raw["probes"]:
        radiance = np.load(raw_dir / probe["file"]).astype(np.float32)
        probe_span = lightmap.rgbm_range(float(radiance.max()))
        name = f"probe_{probe['room']}.webp"
        write_rgbm_webp(radiance, out_dir / name, probe_span, PROBE_QUALITY)
        probes.append(
            {
                "room": probe["room"],
                "url": f"{REALTIME_DIR}/{name}",
                "w": int(radiance.shape[1]),
                "h": int(radiance.shape[0]),
                "range": probe_span,
                "position": probe["position"],
                "box_min": probe["box_min"],
                "box_max": probe["box_max"],
            }
        )
    with (
        tempfile.TemporaryDirectory(prefix="verse-meshopt-") as work,
        np.load(raw_dir / "geometry.npz") as arrays,
    ):
        scene = write_glb(raw["chunks"], arrays, out_dir / "scene.glb", Path(work))
    return {
        "version": VERSION,
        "quality": raw["quality"],
        "scene": {"url": f"{REALTIME_DIR}/scene.glb", **scene},
        "lightmaps": {"encoding": ENCODING, "range": span, "pages": pages},
        "probes": probes,
        "materials": raw["materials"],
        "bytes": 0,
        "stats": dict(raw["stats"]),
    }
