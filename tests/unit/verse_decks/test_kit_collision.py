"""WP12: authored kit collision (stairs, open doors, hollow reactor pieces) and stand-in names."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "art" / "verse"))

from kit import collision, material_names  # noqa: E402

KIT = ROOT / "unreal" / "Verse" / "Art" / "Import" / "Kit"


def _box_top(prim) -> float:
    return prim[2][2]


@pytest.mark.parametrize("width, rise", [(1.2, 0.6), (2.4, 1.4)])
def test_stairs_are_a_ramp_and_one_box_per_tread(width, rise):
    prims = collision.stairs(width, rise)
    steps = round(rise / collision.RISER_M)
    boxes = [p for p in prims if p[0] == "box"]
    ramps = [p for p in prims if p[0] == "convex"]
    assert len(boxes) == steps - 1 and len(ramps) == 1
    assert len(prims) <= 16
    # Treads climb toward the walkway (x = 0, z = 0); none reaches the walkway height.
    tops = [_box_top(b) for b in boxes]
    assert tops == sorted(tops, reverse=True)
    assert max(tops) == pytest.approx(-collision.RISER_M)
    for box in boxes:
        assert box[1][2] == pytest.approx(-rise)  # every step stands on the bottom floor
    # The ramp runs from the walkway edge down to the bottom floor through every tread front.
    xs = [p[0] for p in ramps[0][1]]
    zs = [p[2] for p in ramps[0][1]]
    assert min(xs) == pytest.approx(0.0) and max(zs) == pytest.approx(0.0)
    assert min(zs) < -rise


def test_an_open_door_keeps_its_opening_free():
    prims = collision.open_door((-2.46, -0.15, 0.0), (2.46, 0.45, 4.5))
    assert len(prims) == 3
    left, right, lintel = prims
    assert left[2][0] == pytest.approx(-collision.DOOR_OPENING_W / 2)
    assert right[1][0] == pytest.approx(collision.DOOR_OPENING_W / 2)
    assert lintel[1][2] == pytest.approx(collision.DOOR_OPENING_H)
    cut = collision.open_door((-2.46, -0.15, 0.0), (2.46, 0.45, 1.1))
    assert len(cut) == 2  # a cut door has no lintel under 1.1 m


def test_recipes_by_name():
    assert collision.recipe("SM_Stairs_240_H140", (0, 0, 0), (1, 1, 1))
    assert collision.recipe("SM_BlastDoor_240_Cut", (-2, 0, 0), (2, 1, 1))
    assert collision.recipe("SM_BlastDoor_240_Closed", (-2, 0, 0), (2, 1, 1)) is None
    assert collision.recipe("SM_Reactor_Haze", (0, 0, 0), (1, 1, 1)) == []
    assert collision.recipe("SM_Wall_240", (0, 0, 0), (1, 1, 1)) is None


def test_records_follow_the_recipes():
    for path in sorted(KIT.glob("*/*.import.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        name = record["name"]
        if name in collision.NO_COLLISION:
            assert record["collision"] == {
                "profile": "Verse_NoCollision",
                "source": "none",
                "primitives": 0,
            }, name
        elif name.startswith("SM_Stairs_") or name in ("SM_BlastDoor_240", "SM_BlastDoor_240_Cut"):
            assert record["collision"]["source"] == "authored", name
            assert record["collision"]["primitives"] >= 2, name


@pytest.mark.parametrize(
    "blender, unreal",
    [
        ("M_TMP_PropsInd_ContainerGrey", "M_PropsInd_ContainerGrey"),
        ("TMP_M_Fabric_Linen", "M_Fabric_Linen"),
        ("M_Wall_Charcoal", "M_Wall_Charcoal"),
    ],
)
def test_stand_in_materials_get_verse_names(blender, unreal):
    assert material_names.unreal_name(blender) == unreal
    assert material_names.is_stand_in(blender) == (blender != unreal)


def test_no_record_keeps_a_stand_in_or_default_slot():
    for folder in ("Kit", "Decks"):
        for path in sorted((KIT.parent / folder).rglob("*.import.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            for slot in record.get("mesh", {}).get("material_slots", []):
                assert not material_names.is_stand_in(slot["slot"]), (path.name, slot)
                assert "TMP" not in slot["mi"] and "MI_Default" not in slot["mi"], (path.name, slot)
