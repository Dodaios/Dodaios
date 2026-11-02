"""`fbx-ue/1` calibration: import the calibration assets and check them (art-pipeline 6.1).

`SM_Calib_Axes` and `SK_Calib_Rig` come from `art/verse/kit/calib.py` through
`python scripts/verse/export_unreal.py calib`. This module imports both into
`/Game/Verse/Test/Calib/` without saving and compares them with the
`calibration` block of `unreal/Verse/Art/space_vectors.json`:

* static mesh bounds (units, axes and the mirror of art-pipeline 4.1),
* the chamfer at the +X tip (top and bottom not swapped),
* outward normals at the three tips,
* triangle winding against the engine's own cube (faces not inside out),
* skeleton bone names, first bone, component-space bone positions and the
  root scale (the armature node did not become a scaled extra bone).

The pure comparison functions take plain lists so pytest covers them.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from . import CACHE_ROOT, REPO_ROOT, SPACE_VECTORS

EXPORT_SUMMARY = CACHE_ROOT / "calib" / "calib.export.json"
ENGINE_CUBE = "/Engine/BasicShapes/Cube.Cube"

Vec = Sequence[float]


# --------------------------------------------------------------------------
# Pure checks
# --------------------------------------------------------------------------


def _sub(a: Vec, b: Vec) -> list[float]:
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _cross(a: Vec, b: Vec) -> list[float]:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def check_bounds(lo: Vec, hi: Vec, expected: dict, tol: float) -> list[str]:
    errors = []
    for label, got, want in (("min", lo, expected["min"]), ("max", hi, expected["max"])):
        if any(abs(g - w) > tol for g, w in zip(got, want, strict=True)):
            errors.append(f"bounds {label} {list(got)} != {want}")
    return errors


def check_x_tip(vertices: Sequence[Vec], spec: dict, tol: float) -> list[str]:
    tip = [v for v in vertices if abs(v[0] - spec["x_cm"]) <= tol]
    if not tip:
        return [f"no vertex at x = {spec['x_cm']} cm"]
    top = max(v[2] for v in tip)
    if top > spec["max_z_cm"] + tol:
        return [f"+X tip rises to z = {top:.3f} cm, chamfer expects <= {spec['max_z_cm']}"]
    return []


def check_tip_normals(
    vertices: Sequence[Vec], normals: Sequence[Vec], bounds: dict, specs: Sequence[dict], tol: float
) -> list[str]:
    errors = []
    for spec in specs:
        axis, sign = spec["axis"], spec["sign"]
        edge = bounds["max"][axis] if sign > 0 else bounds["min"][axis]
        picked = [n for v, n in zip(vertices, normals, strict=True) if abs(v[axis] - edge) <= tol]
        if not picked:
            errors.append(f"no vertex at the {spec['tip']} tip")
            continue
        mean = sum(n[axis] for n in picked) / len(picked)
        if mean * sign <= 0:
            errors.append(f"{spec['tip']} tip normals point inward (mean {mean:.3f})")
    return errors


def winding_sign(vertices: Sequence[Vec], triangles: Sequence[int], normals: Sequence[Vec]) -> int:
    """+1 when every triangle's cross(b - a, c - a) agrees with its vertex normals, -1 when
    every one disagrees, 0 when mixed (a mesh that is partly inside out)."""
    signs = set()
    for i in range(0, len(triangles) - 2, 3):
        a, b, c = triangles[i], triangles[i + 1], triangles[i + 2]
        geo = _cross(_sub(vertices[b], vertices[a]), _sub(vertices[c], vertices[a]))
        n = [normals[a][k] + normals[b][k] + normals[c][k] for k in range(3)]
        d = _dot(geo, n)
        if abs(d) > 1e-9:
            signs.add(1 if d > 0 else -1)
    return signs.pop() if len(signs) == 1 else 0


def check_bones(pose: dict, first_bone: str, spec: dict, tol: float) -> list[str]:
    """`pose`: {"names": [...], "locations": {name: [x, y, z]}, "root_scale": [...]}"""
    errors = []
    want = [b["name"] for b in spec["bones"]]
    if sorted(pose["names"]) != sorted(want):
        errors.append(f"bones {pose['names']} != {want}")
    if not pose["names"] or pose["names"][0] != first_bone:
        errors.append(f"first bone is {pose['names'][:1]}, expected {first_bone}")
    for bone in spec["bones"]:
        got = pose["locations"].get(bone["name"])
        if got is None:
            continue
        if any(abs(g - w) > tol for g, w in zip(got, bone["component_location_cm"], strict=True)):
            errors.append(f"{bone['name']} at {got}, expected {bone['component_location_cm']}")
    scale = pose.get("root_scale")
    want_scale = spec["root_scale"]
    if scale is not None and any(abs(s - w) > 1e-3 for s, w in zip(scale, want_scale, strict=True)):
        errors.append(f"root scale {scale} != {spec['root_scale']}")
    return errors


def load_spec(path: Path = SPACE_VECTORS) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["calibration"]


# --------------------------------------------------------------------------
# Editor side
# --------------------------------------------------------------------------


def _mesh_section(mesh):
    import unreal

    section = unreal.ProceduralMeshLibrary.get_section_from_static_mesh(mesh, 0, 0)
    vertices, triangles, normals = section[0], section[1], section[2]
    to_list = lambda v: [float(v.x), float(v.y), float(v.z)]  # noqa: E731
    return [to_list(v) for v in vertices], list(triangles), [to_list(n) for n in normals]


def _static_report(asset, spec: dict, tol: float, reference_sign: int) -> dict:
    box = asset.get_bounding_box()
    lo = [float(box.min.x), float(box.min.y), float(box.min.z)]
    hi = [float(box.max.x), float(box.max.y), float(box.max.z)]
    vertices, triangles, normals = _mesh_section(asset)
    errors = check_bounds(lo, hi, spec["bounds_cm"], tol)
    errors += check_x_tip(vertices, spec["x_tip"], tol)
    errors += check_tip_normals(vertices, normals, spec["bounds_cm"], spec["tip_normals"], tol)
    sign = winding_sign(vertices, triangles, normals)
    if sign != reference_sign:
        errors.append(f"triangle winding {sign} differs from the engine cube ({reference_sign})")
    return {
        "bounds_cm": {"min": lo, "max": hi},
        "triangles": len(triangles) // 3,
        "winding": sign,
        "errors": errors,
    }


def _skeletal_pose(mesh) -> dict:
    import unreal

    skeleton = mesh.get_editor_property("skeleton")
    ext = unreal.AnimPoseExtensions
    pose = ext.get_reference_pose(skeleton)
    names = [str(n) for n in ext.get_bone_names(pose)]
    locations = {}
    root_scale = None
    for name in names:
        transform = ext.get_bone_pose(pose, name, unreal.AnimPoseSpaces.WORLD)
        t = transform.translation
        locations[name] = [float(t.x), float(t.y), float(t.z)]
        if root_scale is None:
            s = transform.scale3d
            root_scale = [float(s.x), float(s.y), float(s.z)]
    return {"names": names, "locations": locations, "root_scale": root_scale}


def run(*, importer: str | None = None) -> dict:
    """Import both calibration assets (not saved) and return the report."""
    import unreal

    from . import import_meshes

    spec = load_spec()
    tol = float(spec["tolerance_cm"])
    summary = json.loads(EXPORT_SUMMARY.read_text(encoding="utf-8"))
    if summary.get("settings_id") != spec["settings_id"]:
        raise RuntimeError(f"export settings {summary.get('settings_id')} != {spec['settings_id']}")
    files = {a["name"]: REPO_ROOT / a["file"] for a in summary["assets"]}
    used = import_meshes.use_importer(importer)

    cube = unreal.load_asset(ENGINE_CUBE)
    reference_sign = winding_sign(*_mesh_section(cube))

    axes_spec = spec["SM_Calib_Axes"]
    options = import_meshes.static_mesh_options(nanite=False, auto_collision=False)
    axes = import_meshes.run_import(files["SM_Calib_Axes"], axes_spec["asset"], options, save=False)
    static = _static_report(axes, axes_spec, tol, reference_sign)

    rig_spec = spec["SK_Calib_Rig"]
    rig = import_meshes.run_import(
        files["SK_Calib_Rig"], rig_spec["asset"], import_meshes.skeletal_mesh_options(), save=False
    )
    pose = _skeletal_pose(rig)
    skeletal = {"pose": pose, "errors": check_bones(pose, rig_spec["first_bone"], rig_spec, tol)}

    ok = not static["errors"] and not skeletal["errors"]
    return {
        "settings_id": spec["settings_id"],
        "importer": used,
        "engine_cube_winding": reference_sign,
        "SM_Calib_Axes": static,
        "SK_Calib_Rig": skeletal,
        "ok": ok,
    }
