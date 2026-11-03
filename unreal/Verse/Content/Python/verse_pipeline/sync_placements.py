"""`import_art.py placements`: make a deck level match its placement JSON (art-pipeline 4.3).

1. An actor belongs to a placement by its tags `verse.zone:<zone>` and
   `verse.pid:<id>`; its label is `<zone>.<id>`.
2. Existing actors are updated in place, so their One File Per Actor files
   keep their names.
3. A placement that is gone deletes its actor; a new one creates an actor.
4. Only actors tagged with the zone are touched, and only their external
   actor packages are saved; the `.umap` is never saved.
5. Actors tagged `verse.manual` are ignored.

`plan()` is pure and tested with pytest; `run()` applies it in the editor.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from verse_pipeline import PLACEMENTS

ZONE_TAG = "verse.zone:"
PID_TAG = "verse.pid:"
MANUAL_TAG = "verse.manual"


def zone_files(deck: str, zone: str | None) -> list[Path]:
    folder = PLACEMENTS / deck
    if zone:
        path = folder / f"{zone}.placement.json"
        if not path.is_file():
            raise FileNotFoundError(f"no placement file {path}")
        return [path]
    return sorted(folder.glob("*.placement.json"))


def actor_tags(zone: str, pid: str) -> list[str]:
    return [f"{ZONE_TAG}{zone}", f"{PID_TAG}{pid}"]


def plan(doc: dict, actors: Iterable[dict]) -> dict:
    """Decide creates, updates and deletes for one zone. Pure.

    `actors`: [{"key": any, "tags": [...]}] of every actor in the level.
    Returns {"create": [placement], "update": [(key, placement)], "delete": [key],
    "duplicates": [key]}.
    """
    zone = doc["zone"]
    wanted = {p["id"]: p for p in doc["placements"]}
    seen: dict[str, object] = {}
    result: dict = {"create": [], "update": [], "delete": [], "duplicates": []}
    for actor in actors:
        tags = list(actor["tags"])
        if MANUAL_TAG in tags or f"{ZONE_TAG}{zone}" not in tags:
            continue
        pids = [t[len(PID_TAG) :] for t in tags if t.startswith(PID_TAG)]
        pid = pids[0] if len(pids) == 1 else None
        if pid is None or pid not in wanted:
            result["delete"].append(actor["key"])
        elif pid in seen:
            result["duplicates"].append(actor["key"])
            result["delete"].append(actor["key"])
        else:
            seen[pid] = actor["key"]
            result["update"].append((actor["key"], wanted[pid]))
    result["create"] = [p for pid, p in sorted(wanted.items()) if pid not in seen]
    return result


# --------------------------------------------------------------------------
# Editor side
# --------------------------------------------------------------------------


def _apply(actor, placement: dict, zone: str) -> None:
    import unreal

    x, y, z, w = placement["rotation"]
    transform = unreal.Transform(
        location=unreal.Vector(*placement["location"]),
        rotation=unreal.Quat(x, y, z, w).rotator(),
        scale=unreal.Vector(*placement["scale"]),
    )
    actor.set_actor_transform(transform, False, False)
    actor.set_actor_label(f"{zone}.{placement['id']}")
    keep = [t for t in actor.tags if not str(t).startswith(("verse.zone:", "verse.pid:"))]
    actor.tags = keep + [unreal.Name(t) for t in actor_tags(zone, placement["id"])]
    component = actor.static_mesh_component
    component.set_static_mesh(unreal.load_asset(placement["asset"]))
    mobility = unreal.ComponentMobility
    movable = placement["mobility"] == "movable"
    component.set_mobility(mobility.MOVABLE if movable else mobility.STATIC)
    component.set_collision_profile_name(placement["collision"])
    component.set_can_ever_affect_navigation(placement["nav"] != "none")
    for slot, mi in (placement.get("material_overrides") or {}).items():
        index = component.get_material_index(slot)
        if index >= 0:
            component.set_material(index, unreal.load_asset(mi))


def run(deck: str, zone: str | None, *, dry_run: bool = False) -> dict:
    import unreal

    actors_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    level_sub = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    report: dict = {"zones": {}, "errors": []}
    for path in zone_files(deck, zone):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not level_sub.load_level(doc["level"]):
            report["errors"].append(f"cannot load {doc['level']}")
            continue
        level_actors = {a.get_path_name(): a for a in actors_sub.get_all_level_actors()}
        steps = plan(
            doc, [{"key": k, "tags": [str(t) for t in a.tags]} for k, a in level_actors.items()]
        )
        summary = {k: len(v) for k, v in steps.items()}
        report["zones"][doc["zone"]] = summary
        if dry_run:
            continue
        touched = []
        for key, placement in steps["update"]:
            _apply(level_actors[key], placement, doc["zone"])
            touched.append(level_actors[key])
        for placement in steps["create"]:
            actor = actors_sub.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector())
            _apply(actor, placement, doc["zone"])
            touched.append(actor)
        packages = [a.get_package() for a in touched]
        for key in steps["delete"]:
            packages.append(level_actors[key].get_package())
            actors_sub.destroy_actor(level_actors[key])
        if packages:
            unreal.EditorLoadingAndSavingUtils.save_packages(packages, False)
    report["ok"] = not report["errors"]
    return report
