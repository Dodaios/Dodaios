"""Tests of the WP19 sound builders, loudness meter, reference mix and licence audit."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import audit_licences  # noqa: E402
import build_audio  # noqa: E402
import dsp  # noqa: E402
import loudness  # noqa: E402
import recipes  # noqa: E402
import reference_mix  # noqa: E402

REPO = build_audio.REPO_ROOT
DATA = build_audio.DATA_DIR
UI_SRC = REPO / "unreal" / "Verse" / "Source" / "VerseUI"


@pytest.fixture(scope="module")
def cues() -> dict:
    return build_audio.load_cues()


def test_full_scale_sine_reads_minus_3_lufs():
    t = np.arange(dsp.SR * 3) / dsp.SR
    x = np.sin(2 * np.pi * 997 * t)
    assert loudness.integrated_lufs(x, dsp.SR) == pytest.approx(-3.01, abs=0.1)
    assert loudness.integrated_lufs(0.1 * x, dsp.SR) == pytest.approx(-23.01, abs=0.1)


def test_true_peak_of_half_scale_sine():
    t = np.arange(dsp.SR) / dsp.SR
    assert loudness.true_peak_dbtp(0.5 * np.sin(2 * np.pi * 1000 * t), dsp.SR) == pytest.approx(
        -6.02, abs=0.05
    )


def test_silence_has_no_loudness():
    assert loudness.integrated_lufs(np.zeros(dsp.SR * 2), dsp.SR) == float("-inf")


def test_every_cue_has_a_recipe_and_a_known_noise_tag(cues):
    ids = [c["id"] for c in cues["cues"]]
    assert len(ids) == len(set(ids))
    for c in cues["cues"]:
        assert c["recipe"] in recipes.RECIPES, c["id"]
        assert not c["noise"] or c["noise"] in reference_mix.NOISE_RANGE_M, c["id"]
        assert c["space"] in ("2d", "3d")
        assert c["bus"] in json.loads((DATA / "mix.json").read_text())["bus_gain_db"]
        assert (
            re.fullmatch(r"[a-z0-9_]+", c["id"]) and len(build_audio.asset_name(c["id"], 9)) <= 64
        )


def test_repeated_one_shots_have_variants_so_no_take_repeats(cues):
    """Parity Z-15: a cue that fires again and again needs at least two takes."""
    for c in cues["cues"]:
        if c["group"] in ("Weapons", "Impacts", "Foley") and not c["loop"]:
            assert c["variants"] >= 2, c["id"]


def test_noise_ranges_match_the_audibility_contract():
    """F6: the Python mixer's ranges are the bot.md 3.2 table that DA_Audibility holds."""
    core = (
        REPO / "unreal/Verse/Source/VerseCore/Private/Noise/VerseAudibilityTable.cpp"
    ).read_text()
    rows = dict(re.findall(r"MakeRow\(Noise_(\w+), ([\w.]+)f?,", core))
    def key(tag: str) -> str:
        return tag.removeprefix("Noise.").replace(".", "_")

    by_key = {key(t): r for t, r in reference_mix.NOISE_RANGE_M.items()}
    assert set(by_key) == set(rows), "reference_mix and the Core rows list different tags"
    whole = set(re.findall(r"MakeRow\(Noise_(\w+), [\w.]+, [\d.]+f, true\)", core))
    scaled = set(re.findall(r"MakeRow\(Noise_(\w+), [^)]*, false, true\)", core))
    assert {k for k, r in by_key.items() if r is None} == whole
    assert {key(s) for s in reference_mix.SCALED} == scaled
    for tag, rng in reference_mix.NOISE_RANGE_M.items():
        key = tag.removeprefix("Noise.").replace(".", "_")
        assert key in rows, tag
        value = rows[key]
        if value == "FractureRange":
            assert rng == 40.0
        elif rng is None:
            assert float(value.rstrip("f")) == 0.0  # whole arena
        else:
            assert float(value.rstrip("f")) == rng, tag


def test_distance_law_ends_exactly_at_the_range():
    mix = json.loads((DATA / "mix.json").read_text())["distance"]
    assert reference_mix.distance_gain(0.5, 10.0, mix) == 1.0
    assert reference_mix.distance_gain(10.0, 10.0, mix) == 0.0
    assert reference_mix.distance_gain(9.8, 10.0, mix) > 0.0
    assert reference_mix.distance_gain(100.0, None, mix) > 0.0


def test_cpp_mix_defaults_match_mix_json():
    """The C++ defaults of FVerseAudioMixSettings equal the committed data (no silent drift)."""
    mix = json.loads((DATA / "mix.json").read_text())
    occ = json.loads((DATA / "occlusion.json").read_text())
    cpp = (UI_SRC / "Private/Audio/VerseAudioCueSet.cpp").read_text()
    header = (UI_SRC / "Public/Audio/VerseAudioTypes.h").read_text()
    header = header[header.index("struct VERSEUI_API FVerseAudioMixSettings") :]

    def floats(name: str) -> list[float]:
        body = re.search(name + r" = \{([^}]*)\}", cpp).group(1)
        return [float(v.strip().rstrip("f")) for v in body.split(",")]

    order = ["Weapons", "Impacts", "Foley", "Destruction", "Gadgets", "Ambience", "UI"]
    assert floats("BusGainDb") == [mix["bus_gain_db"][b] for b in order]
    assert floats("OcclusionLossDb") == [m["transmission_db"] for m in occ["materials"]]
    assert floats("OcclusionLowpassHz") == [m["lowpass_hz"] for m in occ["materials"]]

    def default(name: str) -> float:
        return float(re.search(rf"\b{name} = (-?[\d.]+)f?;", header).group(1))

    assert default("MasterGainDb") == mix["master_gain_db"]
    assert default("MaxVoices") == mix["max_voices"] == 64
    assert default("ReferenceM") == mix["distance"]["reference_m"]
    assert default("Rolloff") == mix["distance"]["rolloff"]
    assert default("LimiterThresholdDb") == mix["limiter"]["threshold_db"]


def test_build_is_deterministic(tmp_path, cues):
    cue = next(c for c in cues["cues"] if c["id"] == "wpn_rifle_fp_body")
    a = build_audio.render_variant(cue, 0)
    b = build_audio.render_variant(cue, 0)
    c = build_audio.render_variant(cue, 1)
    assert np.array_equal(a, b)
    assert not np.array_equal(a[: len(c)], c[: len(a)])
    peak = 20 * np.log10(np.max(np.abs(a)))
    assert peak == pytest.approx(cue["peak_db"], abs=0.01)


def test_every_recipe_renders_finite_audio(cues):
    for c in cues["cues"]:
        x = build_audio.render_variant(c, 0)
        assert np.isfinite(x).all(), c["id"]
        assert 0.03 < len(x) / dsp.SR < 15.0, c["id"]
        assert np.sqrt(np.mean(x**2)) > 10 ** (-60 / 20), c["id"]


def test_reference_duel_meets_the_loudness_gate():
    """A19.4: integrated -16 LUFS within 1 LU, true peak at most -1 dBTP."""
    report = reference_mix.run(check=False)
    assert report["pass"], report
    assert abs(report["integrated_lufs"] + 16.0) <= 1.0
    assert report["true_peak_dbtp"] <= -1.0


def test_licence_audit_passes_on_the_repo(cues):
    assert (
        audit_licences.audit(cues, audit_licences.ledger_rows(), audit_licences.CONTENT, False)
        == []
    )


def test_licence_audit_catches_orphans_and_missing_rows(tmp_path, cues):
    content = tmp_path / "Audio" / "Weapons"
    content.mkdir(parents=True)
    (content / "SW_not_a_cue_01.uasset").write_bytes(b"x")
    rows = [r for r in audit_licences.ledger_rows() if "step_1.ogg" not in r["file"]]
    problems = audit_licences.audit(cues, rows, tmp_path / "Audio", True)
    text = "\n".join(problems)
    assert "SW_not_a_cue_01" in text
    assert "no ledger row" in text and "step_1.ogg" in text
    assert "has no imported asset" in text


def test_licence_audit_rejects_an_unknown_licence(cues):
    doc = json.loads(json.dumps(cues))
    doc["cues"][0]["licence"] = "unknown"
    problems = audit_licences.audit(doc, audit_licences.ledger_rows(), Path("/nonexistent"), False)
    assert any("neither 'own'" in p for p in problems)
