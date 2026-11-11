"""The space view and the rank look in Unreal follow the three.js Verse (stream S7).

* `kit/props/space/space_textures.py` draws the same 9000 stars as `starField` in
  `engine/realtime/spaceView.ts` (golden values from the TypeScript, seed 7);
* `M_Verse_Space` carries the constants of `spaceShader.ts`, and its tonemap inverse is a
  monotonic table;
* the space instances and the decks' star cards draw the space view;
* `VerseRankLook.cpp` carries the rank ladder of `progression/ranks.ts` and the tier colours of
  `characters/build.py` and `TIER_STYLE`.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SPACE = REPO / "art/verse/kit/props/space"
FRONT = REPO / "dodaios/ui/web/frontend/src/components/society"
RANK_CPP = REPO / "unreal/Verse/Source/VerseCore/Private/Ranks/VerseRankLook.cpp"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: starField(9000, 7) of spaceView.ts: index -> (position at radius 50, colour, size).
STARS_TS = {
    0: ([9.9506, -48.82952, 4.08205], [3.13796, 2.57312, 1.88277], 2.93471),
    1: ([-20.62445, 12.16248, -43.89426], [0.32245, 0.22571, 0.16122], 1.16497),
    2: ([36.58495, 32.76285, 9.38814], [0.06024, 0.06024, 0.06024], 1.00015),
    4500: ([21.14493, 41.18917, -18.87709], [0.47355, 0.50906, 0.59194], 1.33436),
    8999: ([38.55021, -20.82909, 24.08382], [0.06004, 0.05704, 0.04923], 1.00003),
}


def test_star_field_matches_the_typescript_generator():
    textures = _load("verse_space_textures_s7", SPACE / "space_textures.py")
    dirs, colours, sizes = textures.star_field()
    assert len(dirs) == 9000
    for i, (position, colour, size) in STARS_TS.items():
        assert [round(v * 50, 4) for v in dirs[i]] == pytest.approx(position, abs=2e-4)
        assert list(colours[i]) == pytest.approx(colour, abs=2e-5)
        assert sizes[i] == pytest.approx(size, abs=2e-5)


def _masters():
    sys.path.insert(0, str(REPO / "art/verse"))
    from weapons.editor import masters

    return masters


def test_space_master_carries_the_three_js_shader_constants():
    ts = (FRONT / "verse/engine/realtime/spaceShader.ts").read_text(encoding="utf-8")
    code = _masters().SPACE_HELPERS + _masters().SPACE_MAIN
    constants = ("1.0018", "1.0165", "0.00145", "0.00025", "36.9, 86.0, 210.9", "133.8", "1.11")
    for constant in constants:
        assert constant in ts, constant
        assert constant in code, constant
    assert "MIE_G = 0.76" in ts and "g = 0.76" in code
    assert "UE_INVERSE" not in _masters().SPACE_HELPERS


def test_tonemap_inverse_is_monotonic():
    doc = json.loads((SPACE / "tonemap_inverse.json").read_text(encoding="utf-8"))
    for channel in "rgb":
        table = doc["log2_scene"][channel]
        assert len(table) == 33
        assert all(b >= a for a, b in zip(table, table[1:], strict=False)), channel


def test_space_instances_and_star_cards_draw_the_space_view():
    folder = REPO / "unreal/Verse/Art/Materials"
    for name in ("MI_Space_Earth", "MI_Space_Stars", "MI_Starfield", "MI_Ops_Starfield"):
        doc = json.loads((folder / f"{name}.mi.json").read_text(encoding="utf-8"))
        assert doc["parent"].endswith("M_Verse_Space"), name
        assert doc["textures"]["DayMap"].endswith("T_Space_EarthDay_BC"), name
    stars = json.loads((folder / "MI_Space_Stars.mi.json").read_text(encoding="utf-8"))
    assert stars["scalars"]["Planet"] == 0.0


def test_space_texture_records_cite_their_ledger_rows():
    ledger = (REPO / "art/verse/LICENSES.md").read_text(encoding="utf-8")
    records = REPO / "unreal/Verse/Art/Import/Kit/Space"
    earth = ("EarthDay_BC", "EarthNight_E", "EarthClouds_M", "EarthRelief_M")
    for name in (f"T_Space_{n}" for n in earth):
        doc = json.loads((records / f"{name}.import.json").read_text(encoding="utf-8"))
        assert doc["license"]["kind"] == "ledger", name
        for digest in doc["license"]["ledger_sha256"]:
            assert digest in ledger, name
    stars = json.loads((records / "T_Space_Stars_E.import.json").read_text(encoding="utf-8"))
    assert stars["license"]["kind"] == "own"


def _block(text: str, name: str) -> str:
    return text.split(f"// {name}-BEGIN")[1].split(f"// {name}-END")[0]


def test_cpp_rank_ladder_matches_ranks_ts():
    ts = (FRONT / "progression/ranks.ts").read_text(encoding="utf-8")
    want = re.findall(r'\{ id: "(\w+)", level: (\d+), tier: "(\w+)", plate: "([01|]+)" \}', ts)
    cpp = _block(RANK_CPP.read_text(encoding="utf-8"), "RANKS")
    got = re.findall(r'\{ TEXT\("(\w+)"\), (\d+), TEXT\("(\w+)"\), TEXT\("([01|]+)"\) \}', cpp)
    assert want and got == want


def test_cpp_tier_colours_match_build_py_and_tier_style():
    build = (REPO / "art/verse/characters/build.py").read_text(encoding="utf-8")
    ts = (FRONT / "progression/ranks.ts").read_text(encoding="utf-8")
    tiles = dict(re.findall(r'(\w+): \{ tile: "(#[0-9a-f]{6})"', ts))
    cpp = _block(RANK_CPP.read_text(encoding="utf-8"), "TIERS")
    rows = re.findall(r"\{ " + ", ".join([r'TEXT\("([#\w]+)"\)'] * 6) + r" \}", cpp)
    assert [r[0] for r in rows] == ["deck", "line", "command", "flag"]
    for tier, uniform, trousers, trim, cap, tile in rows:
        section = build.split(f'"{tier}": {{')[1].split("}")[0]
        assert f'"M_Uniform": "{uniform}"' in section, tier
        assert f'"M_Trousers": "{trousers}"' in section, tier
        assert f'"M_Trim": "{trim}"' in section, tier
        assert f'"M_Cap": "{cap}"' in section, tier
        assert tiles[tier] == tile, tier
