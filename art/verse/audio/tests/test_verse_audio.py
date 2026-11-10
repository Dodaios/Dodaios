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
    assert default("FlybyRadiusM") == mix["flyby"]["radius_m"]
    assert default("BulletSpeedMps") == mix["flyby"]["bullet_speed_mps"]
    assert default("CasingDelayMinS") == mix["casing"]["delay_s"][0]
    assert default("CasingDelayMaxS") == mix["casing"]["delay_s"][1]
    assert default("CasingDropM") == mix["casing"]["drop_m"]


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


# --------------------------------------------------------------------------- bullets, no sci-fi

#: Weapon and bullet cues are real-gun sounds: broadband, no tone and no sweep. The action
#: (fp_mech) and the casing ring like metal on purpose; they are held to the no-sweep rule only.
TONAL_FRACTION_MAX = 0.3
LOCAL_FLATNESS_MIN = 0.6
SWEEP_FRAMES_MAX = 4


def _onset(x: np.ndarray) -> int:
    return int(np.argmax(np.abs(x) > np.max(np.abs(x)) * 0.1))


def local_flatness(x: np.ndarray, length_s: float = 0.05) -> float:
    """Spectral flatness of the first 50 ms after the onset, against the spectrum's own smooth
    envelope (200 Hz to 12 kHz): noise of any colour reads near 1, a standing tone pulls it down."""
    from scipy.ndimage import median_filter

    start = _onset(x)
    seg = x[start : start + dsp.seconds(length_s)]
    n, hop, w = 512, 128, np.hanning(512)
    frames = [seg[i : i + n] * w for i in range(0, max(1, len(seg) - n + 1), hop)]
    p = np.mean([np.abs(np.fft.rfft(f, 4096)) ** 2 for f in frames], axis=0)
    ratio = p / (median_filter(p, size=129, mode="nearest") + 1e-30)
    f = np.fft.rfftfreq(4096, 1 / dsp.SR)
    q = ratio[(f >= 200) & (f <= 12000)] + 1e-30
    return float(np.exp(np.mean(np.log(q))) / np.mean(q))


def dominant_peaks(x: np.ndarray, prom_db: float = 12.0) -> list[float | None]:
    """Per 5 ms hop (10 ms window): the frequency of the strongest peak that stands prom_db above
    the frame's own local spectral median (300 Hz to 12 kHz), or None when there is none."""
    from scipy.ndimage import median_filter

    n, hop = dsp.seconds(0.010), dsp.seconds(0.005)
    w = np.hanning(n)
    f = np.fft.rfftfreq(4096, 1 / dsp.SR)
    band = (f >= 300) & (f <= 12000)
    starts = range(0, len(x) - n + 1, hop)
    rms = np.array([np.sqrt(np.mean(x[i : i + n] ** 2)) for i in starts])
    active = rms >= rms.max() * 10 ** (-40 / 20)
    out: list[float | None] = []
    for j, i in enumerate(starts):
        if not active[j]:
            out.append(None)
            continue
        p = np.abs(np.fft.rfft(x[i : i + n] * w, 4096)) ** 2
        ratio = (p / (median_filter(p, size=61, mode="nearest") + 1e-30))[band]
        k = int(np.argmax(ratio))
        out.append(float(f[band][k]) if 10 * np.log10(ratio[k] + 1e-30) >= prom_db else None)
    return out


def longest_sweep(peaks: list[float | None], max_step: float = 0.2, min_glide: float = 0.15) -> int:
    """Longest run of successive frames whose dominant peak glides one way (steps up to 20 %, at
    least 15 % in all): the track a sine sweep leaves. A held ring or noise leaves none."""
    best, chain, way = 0, [], 0
    for fk in peaks:
        if fk is None:
            chain, way = [], 0
            continue
        if not chain:
            chain = [fk]
            continue
        if fk == chain[-1]:
            continue
        if abs(fk - chain[-1]) <= max_step * chain[-1]:
            step = 1 if fk > chain[-1] else -1
            if way not in (0, step):
                chain = [chain[-1]]
            way = step
            chain.append(fk)
        else:
            chain, way = [fk], 0
        if len(chain) > 1 and abs(chain[-1] - chain[0]) >= min_glide * chain[0]:
            best = max(best, len(chain))
    return best


def tonal_metrics(x: np.ndarray) -> tuple[float, float, int]:
    """(local flatness of the first 50 ms, fraction of frames with a standing peak, sweep run)."""
    peaks = dominant_peaks(x)
    tonal = sum(1 for p in peaks if p is not None) / max(1, len(peaks))
    return local_flatness(x), tonal, longest_sweep(peaks)


def test_the_tone_detector_catches_a_sweep_and_passes_noise():
    sweep = dsp.sweep(2600, 340, 0.45, 6.0) * dsp.env_exp(0.45, 0.07)
    _, tonal, run = tonal_metrics(sweep)
    assert run >= 20 and tonal > 0.5
    noise = dsp.bandpass(dsp.white(dsp.rng(3), 0.45), 300, 4000) * dsp.env_exp(0.45, 0.05)
    flat, tonal, run = tonal_metrics(noise)
    assert run <= SWEEP_FRAMES_MAX and tonal < TONAL_FRACTION_MAX and flat > LOCAL_FLATNESS_MIN


def _bullet_cues(cues):
    return [
        c
        for c in cues["cues"]
        if c["recipe"].startswith("weapon_") or c["recipe"] in ("bullet_flyby", "casing")
    ]


def test_weapon_and_flyby_cues_have_no_tonal_sweep(cues):
    """Bullets, not energy bolts: no tone and no sweep in any shot, tail or flyby; the metal rings
    of the action and the casing may ring but never glide."""
    checked = 0
    for c in _bullet_cues(cues):
        for v in range(int(c["variants"])):
            flat, tonal, run = tonal_metrics(build_audio.render_variant(c, v))
            checked += 1
            assert run <= SWEEP_FRAMES_MAX, (c["id"], v, run)
            if c["recipe"] in ("weapon_mech", "casing"):
                continue
            assert flat >= LOCAL_FLATNESS_MIN, (c["id"], v, flat)
            assert tonal <= TONAL_FRACTION_MAX, (c["id"], v, tonal)
    assert checked > 0


def test_bullet_recipes_use_no_oscillator_sweep():
    import inspect

    for name in ("weapon_mech", "weapon_body", "weapon_tail", "weapon_tp_near", "weapon_tp_far"):
        assert "sweep(" not in inspect.getsource(recipes.RECIPES[name]), name
    for helper in (recipes._report, recipes._blast, recipes._crack, recipes.bullet_flyby):
        assert "sweep(" not in inspect.getsource(helper), helper.__name__


def test_every_weapon_has_a_complete_sound_profile(cues):
    """weapon_ids maps every weapon of Data/weapons to a profile that has all of its cues."""
    weapons = {p.stem for p in (REPO / "unreal/Verse/Data/weapons").glob("*.json")} - {"gadgets"}
    assert set(cues["weapon_ids"]) == weapons
    assert set(cues["weapon_ids"].values()) <= set(cues["weapon_profiles"])
    ids = {c["id"] for c in cues["cues"]}
    layers = ("fp_mech", "fp_body", "tail", "tp_near", "tp_far", "tp_tail")
    for profile in cues["weapon_profiles"]:
        assert profile in recipes.WEAPONS
        need = [f"wpn_{profile}_{layer}" for layer in layers]
        need += [f"rld_{profile}_tactical", f"rld_{profile}_empty", f"eqp_{profile}"]
        need += [f"casing_{profile}"]
        assert not [n for n in need if n not in ids], profile
    assert "bullet_flyby" in ids and "bolt_flyby" not in ids


def test_casing_is_a_quiet_nearby_foley_cue(cues):
    casings = [c for c in cues["cues"] if c["recipe"] == "casing"]
    assert casings
    for c in casings:
        assert c["bus"] == "Foley" and c["space"] == "3d" and not c["noise"]
        assert 0 < c["range_m"] <= 10 and c["priority"] <= 3 and c["variants"] >= 3
        x = build_audio.render_variant(c, 0)
        spectrum = np.abs(np.fft.rfft(x)) ** 2
        f = np.fft.rfftfreq(len(x), 1 / dsp.SR)
        bright = spectrum[(f >= 3000) & (f <= 12000)].sum()
        assert bright > 0.8 * spectrum.sum(), c["id"]
