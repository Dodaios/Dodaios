"""Sound recipes of the Verse (WP19): one function per sound family.

A recipe takes a seeded generator and its parameters from
``unreal/Verse/Data/audio/cues.json`` and returns a mono float buffer at
``dsp.SR``. Recipes named ``cc0`` read a CC0 recording that the ledger
(``art/verse/LICENSES.md``) cites; every other recipe is own work.
Style: Military-Industrial Noir. Heavy, dry, close; black steel and concrete.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import dsp
import numpy as np
from dsp import SR

REPO_ROOT = Path(__file__).resolve().parents[3]
Recipe = Callable[..., np.ndarray]
RECIPES: dict[str, Recipe] = {}


def recipe(name: str) -> Callable[[Recipe], Recipe]:
    def wrap(fn: Recipe) -> Recipe:
        RECIPES[name] = fn
        return fn

    return wrap


# --------------------------------------------------------------------------- helpers


def _burst(r, length_s, lo, hi, decay_s, attack_s=0.0003):
    return dsp.bandpass(dsp.white(r, length_s), lo, hi) * dsp.env_exp(length_s, decay_s, attack_s)


def _clack(r, length_s, base_hz, decay_s=0.03, bright=1.0):
    """A metal-on-metal mechanical transient: noise click plus a few inharmonic modes."""
    ratios = [1.0, 1.59, 2.31, 3.17, 4.43]
    freqs = [base_hz * k * r.uniform(0.97, 1.03) for k in ratios]
    decays = [decay_s * r.uniform(0.6, 1.4) / (1 + 0.3 * i) for i in range(len(freqs))]
    amps = [1.0, 0.7, 0.5 * bright, 0.35 * bright, 0.25 * bright]
    ring = dsp.modes(r, length_s, freqs, decays, amps)
    click = _burst(r, length_s, 1800, 9000, 0.004)
    return dsp.fade(0.6 * ring + 1.2 * click)


def _scrape(r, length_s, lo, hi, grit=0.3):
    base = dsp.bandpass(dsp.white(r, length_s), lo, hi)
    am = dsp.lowpass(np.abs(r.standard_normal(len(base))), 40, 2)
    am = am / (np.max(am) + 1e-9)
    grains = (r.random(len(base)) < 0.002).astype(float) * r.uniform(0.3, 1.0, len(base))
    grains = dsp.highpass(grains, 2500, 2)
    return base * (0.4 + am) + grit * grains


def _cloth(r, length_s, intensity=1.0):
    n = dsp.bandpass(dsp.pink(r, length_s), 500, 6000)
    am = dsp.lowpass(np.abs(r.standard_normal(len(n))), 18, 2)
    am = am / (np.max(am) + 1e-9)
    return intensity * n * am * dsp.env_adsr(length_s, 0.02, 0.05, 0.8, length_s * 0.4)


def _thud(r, length_s, f0, f1, decay_s, drive=2.0):
    body = dsp.sweep(f0, f1, length_s, 5.0) * dsp.env_exp(length_s, decay_s, 0.001)
    return dsp.saturate(body, drive)


def _debris(r, length_s, density, lo, hi, decay_s=0.02, start_s=0.0, spread_s=None):
    """Scattered small impacts: falling chips, shards, grit."""
    out = np.zeros(dsp.seconds(length_s))
    spread = spread_s if spread_s is not None else length_s - start_s
    count = max(1, int(density * spread))
    for _ in range(count):
        when = start_s + spread * (r.random() ** 1.6)
        g = r.uniform(0.15, 1.0) * (1 - (when - start_s) / max(spread, 1e-6)) ** 0.7
        tick = _burst(r, 0.08, lo * r.uniform(0.8, 1.2), hi, decay_s * r.uniform(0.5, 1.5))
        out += g * dsp.pad(tick, length_s, when)
    return out


def _room(r, x, length_s, decay_s=0.9, bright=3000, wet=0.35):
    ir = dsp.room_ir(r, min(decay_s * 1.2, length_s), decay_s, bright)
    return x + wet * dsp.convolve(x, ir, length_s)


def _cc0_file(name: str) -> np.ndarray:
    import soundfile as sf

    data, sr = sf.read(str(REPO_ROOT / name), always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sr != SR:
        from scipy import signal

        data = signal.resample_poly(data, SR, sr)
    return np.asarray(data, dtype=np.float64)


# --------------------------------------------------------------------------- recorded


@recipe("cc0")
def cc0(
    r, file: str, gain: float = 1.0, lowpass_hz: float = 0.0, pitch: float = 1.0, loop=False, **_
):
    x = _cc0_file(file)
    if pitch != 1.0:
        from scipy import signal

        up, down = int(round(1000 / pitch)), 1000
        x = signal.resample_poly(x, up, down)
    if lowpass_hz:
        x = dsp.lowpass(x, lowpass_hz, 2)
    # A loop keeps its own seam (the recording is cut to loop); a fade would click.
    return gain * x if loop else dsp.fade(gain * x, 0.001, 0.02)


@recipe("cc0_layer")
def cc0_layer(r, file: str, synth: str, synth_gain: float = 0.6, length_s: float = 0.6, **kw):
    base = cc0(r, file)
    extra = RECIPES[synth](r, **kw)
    n = max(len(base), len(extra), dsp.seconds(length_s))
    out = np.zeros(n)
    out[: len(base)] += base
    out[: len(extra)] += synth_gain * extra / (np.max(np.abs(extra)) + 1e-9) * np.max(np.abs(base))
    return out


# --------------------------------------------------------------------------- weapons


WEAPONS = {
    # A real gun report, no tonal parts: crack = the supersonic N-wave and its broadband snap
    # (duration ms, gain, top Hz), blast = the muzzle blast pressure pulse (positive phase ms),
    # low = the 60-250 Hz blast body (lo Hz, hi Hz, decay s), mid = the broadband blast energy
    # (lo Hz, hi Hz, decay s), bark = its level against the low body, limit = peak limiting dB,
    # drive = saturation, tail = room decay s,
    # clack = action base Hz, action = how the mechanism cycles.
    "rifle": dict(
        crack=(0.32, 1.0, 15000),
        blast=2.0,
        low=(55, 250, 0.06),
        mid=(300, 6000, 0.03),
        bark=1.5,
        limit=12.0,
        drive=3.5,
        length=0.5,
        tail=1.7,
        clack=1650,
        action="rotary",
    ),
    "marksman": dict(
        crack=(0.40, 1.15, 16000),
        blast=1.8,
        low=(48, 230, 0.075),
        mid=(280, 5500, 0.035),
        bark=1.4,
        limit=12.0,
        drive=3.8,
        length=0.6,
        tail=2.1,
        clack=1450,
        action="rotary",
    ),
    "smg": dict(
        crack=(0.22, 0.45, 9000),
        blast=2.4,
        low=(70, 280, 0.045),
        mid=(320, 3800, 0.022),
        bark=1.4,
        limit=11.0,
        drive=3.2,
        length=0.38,
        tail=1.3,
        clack=2100,
        action="blowback",
    ),
    "pistol": dict(
        crack=(0.20, 0.32, 7000),
        blast=3.0,
        low=(65, 300, 0.045),
        mid=(250, 3200, 0.024),
        bark=1.3,
        limit=10.0,
        drive=3.0,
        length=0.4,
        tail=1.2,
        clack=2300,
        action="slide",
    ),
}


def _unit(x):
    return x / (np.max(np.abs(x)) + 1e-9)


def _crack(r, length_s, dur_ms, top_hz, offset_s=0.0):
    """Supersonic crack: an N-wave plus a sub-ms broadband snap, a few ms long."""
    shock = dsp.n_wave(length_s, dur_ms / 1000 * r.uniform(0.9, 1.1), offset_s=offset_s)
    shock = dsp.lowpass(dsp.highpass(shock, 700, 2), top_hz, 2)
    snap = dsp.highpass(dsp.white(r, length_s), 2000, 2) * dsp.env_exp(length_s, 0.0025, 0.0001)
    snap = dsp.lowpass(dsp.pad(snap, length_s, offset_s), top_hz, 2)
    return _unit(shock) + 0.55 * _unit(snap)


def _blast(r, length_s, w):
    """Muzzle blast: pressure pulse, heavy low body and broadband mid energy, all from noise."""
    pulse = dsp.friedlander(length_s, w["blast"] / 1000 * r.uniform(0.9, 1.1))
    pulse = dsp.lowpass(dsp.highpass(pulse, 45, 2), 5000, 2)
    lo, hi, low_decay = w["low"]
    low = dsp.lowpass(dsp.highpass(dsp.white(r, length_s), lo, 2), hi, 4)
    low = dsp.peak_eq(low, 90, 0.9, 5.0) * dsp.env_exp(length_s, low_decay, 0.0015)
    mlo, mhi, mid_decay = w["mid"]
    mid = dsp.bandpass(dsp.white(r, length_s), mlo, mhi) * dsp.env_exp(length_s, mid_decay, 0.0004)
    return 0.9 * _unit(pulse) + 1.0 * _unit(low) + w["bark"] * _unit(mid)


def _report(r, weapon, length_s=None):
    """The dry gun report (muzzle side): crack, blast, a hint of the action, limited for punch."""
    w = WEAPONS[weapon]
    length = length_s or w["length"]
    dur_ms, crack_gain, top = w["crack"]
    crack = _crack(r, length, dur_ms, top)
    blast = _blast(r, length, w)
    click = _clack(r, length, w["clack"] * 1.3, 0.008, 0.6)
    x = dsp.mix(length, (blast, 1.0), (crack, 0.8 * crack_gain), (click, 0.08, 0.012))
    x = dsp.peak_limit(_unit(x), -w["limit"])
    return dsp.saturate(_unit(x), w["drive"])


@recipe("weapon_mech")
def weapon_mech(r, weapon: str, **_):
    w = WEAPONS[weapon]
    length = 0.22
    first = _clack(r, length, w["clack"], 0.03)
    if w["action"] == "rotary":
        second = _clack(r, length, w["clack"] * 0.82, 0.04, 0.7)
        return dsp.mix(length, (first, 1.0), (second, 0.65, 0.048 + r.uniform(-0.004, 0.004)))
    if w["action"] == "blowback":
        carrier = _clack(r, length, w["clack"] * 0.9, 0.02, 0.9)
        return dsp.mix(length, (first, 1.0), (carrier, 0.6, 0.026 + r.uniform(-0.003, 0.003)))
    slide = _clack(r, length, w["clack"] * 1.15, 0.025, 1.2)
    return dsp.mix(length, (first, 1.0), (slide, 0.5, 0.032))


@recipe("weapon_body")
def weapon_body(r, weapon: str, **_):
    return dsp.fade(_report(r, weapon), 0.0001, 0.05)


@recipe("weapon_tail")
def weapon_tail(r, weapon: str, decay_s: float = 0.0, bright: float = 2600.0, **_):
    w = WEAPONS[weapon]
    decay = decay_s or w["tail"]
    length = decay * 1.3
    exc = weapon_body(r, weapon)
    ir = dsp.room_ir(r, length, decay, bright, early=(0.011, 0.019, 0.031, 0.047, 0.071))
    wet = dsp.convolve(exc, ir, length)
    wet[: dsp.seconds(0.012)] *= np.linspace(0, 1, dsp.seconds(0.012))  # no direct sound
    slap = dsp.lowpass(dsp.pad(exc, length, 0.085 + r.uniform(0, 0.02)), 1800, 2)
    return dsp.fade(wet + 0.25 * slap, 0.005, 0.2)


@recipe("weapon_tp_near")
def weapon_tp_near(r, weapon: str, **_):
    length = 0.9
    body = weapon_body(r, weapon)
    mech = weapon_mech(r, weapon)
    x = dsp.mix(length, (body, 1.0), (mech, 0.25))
    x = dsp.lowpass(x, 10000, 2)
    return dsp.fade(_room(r, x, length, 0.7, 2500, 0.3), 0.0003, 0.1)


@recipe("weapon_tp_far")
def weapon_tp_far(r, weapon: str, **_):
    """A distant shot: the crack thins to a faint high snap, the blast is a dull low boom."""
    w = WEAPONS[weapon]
    length = w["tail"] * 1.9
    dur_ms, crack_gain, _top = w["crack"]
    thin = dsp.highpass(_crack(r, length, dur_ms * 0.6, 9000), 2500, 2)
    boom = dsp.lowpass(_blast(r, length, w), 700, 4)
    boom = dsp.saturate(_unit(boom), 1.6)
    # The air took the top off the blast and smeared its onset; the thin snap is all that is left
    # of the crack.
    body = dsp.mix(length, (thin, 0.1 * crack_gain), (boom, 1.0, 0.004 + r.uniform(0.0, 0.004)))
    ir = dsp.room_ir(r, length, w["tail"] * 1.5, 700, early=(0.03, 0.055, 0.09, 0.14))
    x = 0.6 * body + 1.0 * dsp.convolve(dsp.lowpass(body, 900, 2), ir, length)
    return dsp.fade(x, 0.003, 0.3)


# --------------------------------------------------------------------------- bullets


@recipe("bullet_flyby")
def bullet_flyby(r, **_):
    """A bullet passing close: the sharp supersonic snap, then a short airy zip that falls away."""
    length = 0.32
    at = 0.01
    snap = _crack(r, length, 0.18 * r.uniform(0.85, 1.15), 16000, offset_s=at)
    echo = dsp.lowpass(dsp.pad(snap, length, 0.014 + r.uniform(0.0, 0.012)), 5000, 2)
    zip_len = 0.22
    zip_ = dsp.glide_bandpass(
        dsp.white(r, zip_len), 5200 * r.uniform(0.9, 1.1), 1500 * r.uniform(0.9, 1.1), 1.4, 2.5
    )
    zip_ = _unit(zip_ * dsp.env_exp(zip_len, 0.05, 0.002))
    hush = _unit(dsp.lowpass(dsp.white(r, zip_len), 900, 2) * dsp.env_exp(zip_len, 0.035, 0.003))
    x = dsp.mix(
        length, (snap, 1.0), (echo, 0.22), (zip_, 0.45, at + 0.002), (hush, 0.18, at + 0.004)
    )
    return dsp.fade(x, 0.0002, 0.03)


@recipe("casing")
def casing(r, size: str = "rifle", **_):
    """A spent brass casing on concrete: bright inharmonic pings, bouncing smaller and faster."""
    rifle = size == "rifle"
    length = 0.6
    base = (3300 if rifle else 4600) * r.uniform(0.94, 1.06)
    ratios = [1.0, 1.47, 2.09] if rifle else [1.0, 1.38, 1.93]
    decay = 0.05 if rifle else 0.035
    bounces = 3 + int(r.integers(0, 2))
    when, gap, gain = 0.0, r.uniform(0.09, 0.12), 1.0
    parts = []
    for _ in range(bounces):
        freqs = [min(base * k * r.uniform(0.985, 1.015), 9000) for k in ratios]
        decays = [decay * r.uniform(0.6, 1.2) / (1 + 0.5 * i) for i in range(3)]
        ring = dsp.modes(r, 0.2, freqs, decays, [1.0, 0.6, 0.35], 0.004)
        tick = _burst(r, 0.2, 3000, 12000, 0.0012, 0.0001)
        parts.append((0.6 * ring + 0.5 * tick, gain, when))
        when += gap
        gap = max(0.04, gap * r.uniform(0.5, 0.65))
        gain *= r.uniform(0.45, 0.65)
    roll = _debris(r, 0.25, 30, 4000, 11000, 0.003)
    parts.append((roll, 0.12 * gain, when))
    return dsp.fade(dsp.mix(length, *parts), 0.0002, 0.05)


MATERIALS = {
    "sheet_metal": dict(
        modes=[620, 1180, 1940, 2870, 4100], decay=0.09, noise=(1500, 9000), thud=0.3
    ),
    "container_wall": dict(
        modes=[210, 395, 640, 980, 1330], decay=0.22, noise=(400, 4000), thud=0.7
    ),
    "glass": dict(modes=[2600, 4150, 5600, 7300, 8900], decay=0.05, noise=(3000, 14000), thud=0.0),
    "cladding_panel": dict(modes=[420, 910, 1500], decay=0.03, noise=(300, 2600), thud=0.5),
    "catwalk_grating": dict(
        modes=[980, 1640, 2410, 3300], decay=0.05, noise=(1200, 7000), thud=0.2
    ),
    "ceiling_panel": dict(modes=[300, 700], decay=0.02, noise=(200, 2200), thud=0.3),
    "concrete": dict(modes=[180, 430], decay=0.015, noise=(500, 6000), thud=0.9),
    "armor_steel": dict(modes=[1120, 2290, 3610, 5070], decay=0.45, noise=(4000, 15000), thud=0.2),
}


@recipe("impact")
def impact(r, material: str, **_):
    m = MATERIALS[material]
    length = 0.7 if material in ("armor_steel", "container_wall", "glass") else 0.45
    ring = dsp.modes(
        r,
        length,
        m["modes"],
        [m["decay"] * r.uniform(0.7, 1.3) for _ in m["modes"]],
        [1.0 / (1 + 0.4 * i) for i in range(len(m["modes"]))],
        0.03,
    )
    crack = _burst(r, length, *m["noise"], 0.012)
    thud = _thud(r, length, 160, 60, 0.05, 2.0)
    parts = [(ring, 0.6), (crack, 1.0), (thud, m["thud"])]
    if material == "glass":
        parts.append((_debris(r, length, 60, 3500, 14000, 0.015, 0.02, 0.45), 0.6))
    if material == "catwalk_grating":
        parts.append((_debris(r, length, 30, 900, 5000, 0.03, 0.01, 0.2), 0.5))
    if material in ("concrete", "ceiling_panel", "cladding_panel"):
        parts.append((_debris(r, length, 40, 600, 6000, 0.01, 0.03, 0.35), 0.35))
    if material == "armor_steel":
        sizzle = dsp.highpass(dsp.white(r, length), 6000, 2) * dsp.env_exp(length, 0.12)
        parts.append((sizzle, 0.25))
    x = dsp.mix(length, *parts)
    return dsp.fade(_room(r, x, length, 0.35, 4000, 0.18))


@recipe("impact_flesh")
def impact_flesh(r, **_):
    length = 0.35
    wet = dsp.lowpass(dsp.white(r, length), 900, 2) * dsp.env_exp(length, 0.035)
    thump = _thud(r, length, 120, 55, 0.06, 2.5)
    squelch = dsp.bandpass(dsp.white(r, length), 400, 1800) * dsp.env_exp(length, 0.08, 0.004)
    return dsp.fade(1.0 * wet + 0.9 * thump + 0.3 * squelch)


@recipe("penetration_exit")
def penetration_exit(r, **_):
    length = 0.5
    t = dsp.t_axis(length)
    tear = dsp.bandpass(dsp.white(r, length), 600, 4000)
    tear *= np.clip(t / 0.01, 0, 1) * np.exp(-t / 0.06)
    spray = _debris(r, length, 80, 1200, 9000, 0.01, 0.005, 0.3)
    return dsp.fade(0.9 * tear + 0.6 * spray + 0.4 * _thud(r, length, 140, 70, 0.03))


# --------------------------------------------------------------------------- foley


SURFACES = {
    "metal": dict(modes=[480, 1010, 1650], decay=0.03, noise=(700, 6000), grit=0.1),
    "grating": dict(modes=[900, 1580, 2450], decay=0.04, noise=(1000, 7000), grit=0.2),
    "concrete": dict(modes=[160], decay=0.01, noise=(400, 5000), grit=0.4),
    "rubble": dict(modes=[220], decay=0.01, noise=(500, 8000), grit=1.0),
}


@recipe("footstep")
def footstep(r, surface: str, **_):
    s = SURFACES[surface]
    length = 0.35
    heel = _thud(r, length, 110, 60, 0.025, 1.5)
    tap = _burst(r, length, *s["noise"], 0.01)
    ring = dsp.modes(r, length, s["modes"], [s["decay"]] * len(s["modes"]), None, 0.04)
    toe_at = 0.045 + r.uniform(-0.01, 0.015)
    toe = _burst(r, length, s["noise"][0] * 1.3, s["noise"][1], 0.008)
    parts = [
        (heel, 0.8),
        (tap, 0.7),
        (ring, 0.35),
        (toe, 0.45, toe_at),
        (_scrape(r, 0.08, 1500, 7000, 0.0) * dsp.env_exp(0.08, 0.02), 0.15, toe_at),
    ]
    if s["grit"]:
        parts.append(
            (_debris(r, length, 120 * s["grit"], 2000, 10000, 0.004, 0.0, 0.12), s["grit"] * 0.5)
        )
    if surface == "grating":
        parts.append((_debris(r, length, 25, 1100, 4000, 0.03, 0.01, 0.12), 0.35))
    return dsp.fade(dsp.mix(length, *parts))


@recipe("slide")
def slide(r, **_):
    length = 0.85
    x = _scrape(r, length, 300, 4500, 0.6) * dsp.env_adsr(length, 0.03, 0.1, 0.8, 0.35)
    gear = _debris(r, length, 12, 1500, 5000, 0.02, 0.05, 0.6)
    return dsp.fade(0.9 * x + 0.5 * _cloth(r, length) + 0.3 * gear)


@recipe("land")
def land(r, **_):
    length = 0.5
    thud = _thud(r, length, 95, 45, 0.07, 2.5)
    boots = dsp.mix(length, (footstep(r, "metal"), 0.8), (footstep(r, "metal"), 0.6, 0.018))
    gear = _debris(r, length, 30, 1200, 6000, 0.025, 0.01, 0.2)
    return dsp.fade(1.0 * thud + 0.6 * boots + 0.4 * gear + 0.4 * _cloth(r, length))


@recipe("mantle")
def mantle(r, **_):
    length = 0.8
    grab = _clack(r, 0.3, 900, 0.03, 0.5)
    scuff = _scrape(r, 0.4, 600, 4000, 0.3) * dsp.env_adsr(0.4, 0.02, 0.1, 0.7, 0.2)
    step = footstep(r, "metal")
    return dsp.fade(
        dsp.mix(
            length, (grab, 0.7), (_cloth(r, 0.6), 0.6, 0.05), (scuff, 0.5, 0.15), (step, 0.7, 0.5)
        )
    )


@recipe("lean")
def lean(r, **_):
    length = 0.3
    click = _clack(r, length, 2600, 0.01, 0.6) * 0.15
    return dsp.fade(_cloth(r, length, 1.0) + click)


@recipe("prone")
def prone(r, down: bool = True, **_):
    length = 0.9
    body = _thud(r, length, 85, 40, 0.09, 2.0)
    gear = _debris(r, length, 25, 1000, 5000, 0.03, 0.05, 0.4)
    when = 0.25 if down else 0.0
    return dsp.fade(
        dsp.mix(
            length,
            (_cloth(r, 0.8, 1.2), 0.8),
            (body, 0.8 if down else 0.3, when),
            (gear, 0.4, when),
        )
    )


# --------------------------------------------------------------------------- reloads, equip, melee


def _mag_out(r, length):
    rel = _clack(r, length, 2100, 0.012, 0.8)
    slide_ = _scrape(r, 0.18, 1200, 6000, 0.0) * dsp.env_adsr(0.18, 0.01, 0.05, 0.6, 0.1)
    return dsp.mix(length, (rel, 0.7), (slide_, 0.45, 0.05))


def _mag_in(r, length, heavy=1.0):
    seat = _clack(r, length, 1300, 0.025, 0.9)
    thump = _thud(r, length, 200, 90, 0.02, 2.0)
    return dsp.mix(length, (seat, 0.9), (thump, 0.5 * heavy))


@recipe("reload")
def reload(r, weapon: str, empty: bool, **_):
    rifle = weapon in ("rifle", "marksman", "smg")
    length = (2.6 if empty else 1.9) if rifle else (1.9 if empty else 1.4)
    parts = [(_cloth(r, 0.5, 0.6), 0.4, 0.0), (_mag_out(r, 0.4), 1.0, 0.12)]
    seat_at = 0.95 if rifle else 0.7
    parts += [
        (_cloth(r, 0.4, 0.5), 0.3, seat_at - 0.35),
        (_mag_in(r, 0.4, 1.0 if rifle else 0.6), 1.0, seat_at),
        (_clack(r, 0.2, 1500, 0.01, 0.5), 0.35, seat_at + 0.09),
    ]
    if empty:
        pull_at = seat_at + 0.55
        if rifle:
            parts += [
                (_clack(r, 0.25, 1900, 0.02, 1.0), 0.8, pull_at),
                (_scrape(r, 0.12, 900, 5000, 0.0) * dsp.env_exp(0.12, 0.04), 0.4, pull_at + 0.01),
                (_clack(r, 0.3, 1450, 0.04, 1.0), 1.0, pull_at + 0.16),
            ]
        else:
            parts += [(_clack(r, 0.3, 2400, 0.03, 1.0), 1.0, pull_at - 0.1)]
    return dsp.fade(dsp.mix(length, *parts), 0.001, 0.05)


@recipe("equip")
def equip(r, weapon: str, **_):
    length = 0.7
    if weapon == "knife":
        ring = dsp.modes(r, 0.6, [3100, 5200, 7400], [0.18, 0.12, 0.08], [0.6, 0.4, 0.3])
        draw = _scrape(r, 0.25, 2500, 11000, 0.0) * dsp.env_adsr(0.25, 0.02, 0.05, 0.8, 0.15)
        return dsp.fade(dsp.mix(length, (draw, 0.8), (ring, 0.25, 0.2)))
    clink = _debris(r, length, 8, 2500, 8000, 0.02, 0.05, 0.25)
    check = _clack(r, 0.3, 1700 if weapon in ("rifle", "marksman") else 2200, 0.02, 0.8)
    return dsp.fade(dsp.mix(length, (_cloth(r, 0.5, 1.0), 0.7), (clink, 0.3), (check, 0.8, 0.38)))


@recipe("knife_swing")
def knife_swing(r, **_):
    length = 0.35
    t = dsp.t_axis(length)
    bell = np.exp(-(((t - 0.12) / 0.045) ** 2))
    return dsp.fade(_scrape(r, length, 900, 7000, 0.0) * bell + 0.3 * _cloth(r, length) * bell)


@recipe("knife_hit")
def knife_hit(r, **_):
    length = 0.4
    stab = impact_flesh(r)
    crunch = _debris(r, length, 60, 600, 3000, 0.008, 0.01, 0.08)
    return dsp.fade(dsp.mix(length, (knife_swing(r), 0.4), (stab, 1.0, 0.1), (crunch, 0.4, 0.11)))


@recipe("finisher")
def finisher(r, phase: str, **_):
    if phase == "takedown":
        length = 0.9
        slam = _thud(r, length, 90, 38, 0.12, 3.0)
        gear = _debris(r, length, 40, 900, 6000, 0.03, 0.02, 0.4)
        return dsp.fade(
            dsp.mix(length, (_cloth(r, 0.6, 1.4), 0.7), (slam, 1.0, 0.25), (gear, 0.4, 0.26))
        )
    if phase == "struggle":
        length = 1.2
        scuffs = sum(
            dsp.pad(
                _scrape(r, 0.2, 400, 3000, 0.2) * dsp.env_exp(0.2, 0.06), length, r.uniform(0, 1.0)
            )
            for _ in range(5)
        )
        return dsp.fade(0.8 * _cloth(r, length, 1.3) + 0.5 * scuffs)
    length = 0.9
    stab = knife_hit(r)
    slump = _thud(r, length, 80, 40, 0.1, 2.0)
    return dsp.fade(
        dsp.mix(length, (stab, 1.0), (slump, 0.6, 0.45), (_cloth(r, 0.5, 0.8), 0.4, 0.42))
    )


# ------------------------------------------------------------- destruction, drones, gadgets


@recipe("destruction")
def destruction(r, piece: str, **_):
    length = 2.2
    if piece == "glass_pane":
        crack = _burst(r, length, 3000, 15000, 0.02)
        shards = _debris(r, length, 220, 3000, 15000, 0.02, 0.02, 1.2)
        rings = dsp.modes(r, length, [2900, 4400, 6100, 8100], [0.2, 0.15, 0.1, 0.08])
        return dsp.fade(dsp.mix(length, (crack, 1.0), (shards, 0.9), (rings, 0.2)), 0.0005, 0.3)
    spec = {
        "wall_panel": ([380, 720, 1150, 1720], 0.35, (500, 6000), 0.8),
        "cladding_wall": ([300, 640, 1020], 0.12, (300, 3500), 0.9),
        "container_wall": ([150, 290, 470, 760], 0.6, (250, 3000), 1.0),
        "catwalk_segment": ([700, 1250, 1900, 2700], 0.4, (800, 6000), 0.7),
        "ceiling_panel": ([260, 520], 0.05, (200, 3000), 0.5),
    }[piece]
    freqs, decay, band, weight = spec
    boom = _thud(r, length, 120, 35, 0.25 * weight, 3.5)
    tear = _scrape(r, 0.6, *band, 0.5) * dsp.env_exp(0.6, 0.2, 0.003)
    ring = dsp.modes(r, length, freqs, [decay * r.uniform(0.7, 1.3) for _ in freqs])
    chunks = _debris(r, length, 45, band[0], band[1], 0.04, 0.08, 1.6)
    parts = [(boom, 1.0 * weight), (tear, 0.8), (ring, 0.35), (chunks, 0.7)]
    if piece == "catwalk_segment":
        screech = dsp.sweep(900, 520, 0.9, 1.0) * dsp.env_adsr(0.9, 0.1, 0.2, 0.6, 0.3)
        parts.append((dsp.saturate(screech, 3.0) * 0.6, 0.3, 0.05))
    if piece == "ceiling_panel":
        parts.append((_debris(r, length, 200, 800, 6000, 0.006, 0.1, 1.8), 0.5))
    x = dsp.mix(length, *parts)
    return dsp.fade(_room(r, x, length, 1.4, 2200, 0.3), 0.0005, 0.3)


@recipe("debris_settle")
def debris_settle(r, kind: str, **_):
    length = 1.6
    lo, hi, d = {
        "metal": (900, 7000, 0.05),
        "glass": (3000, 15000, 0.025),
        "dust": (500, 6000, 0.01),
    }[kind]
    x = _debris(r, length, 30, lo, hi, d, 0.0, 1.4)
    if kind == "dust":
        x += 0.3 * dsp.lowpass(dsp.pink(r, length), 2500, 2) * dsp.env_exp(length, 0.6, 0.05)
    return dsp.fade(x, 0.002, 0.2)


@recipe("drone_flight")
def drone_flight(r, **_):
    length = 4.0
    t = dsp.t_axis(length)
    f = 172 * (1 + 0.01 * np.sin(2 * np.pi * 0.7 * t))
    phase = 2 * np.pi * np.cumsum(f) / SR
    rotor = sum(np.sin(k * phase) / k for k in range(1, 9))
    chop = 0.6 + 0.4 * np.sin(2 * np.pi * 31 * t) ** 2
    air = dsp.bandpass(dsp.white(r, length), 400, 3500)
    x = 0.5 * rotor * chop + 0.35 * air + 0.2 * np.sin(2 * np.pi * 60 * t)
    return dsp.loopable(x, 0.4)


@recipe("drone_weld")
def drone_weld(r, **_):
    length = 4.0
    t = dsp.t_axis(length)
    arc = dsp.highpass(dsp.white(r, length), 2500, 2)
    gate = dsp.lowpass((r.random(len(t)) < 0.03).astype(float), 300, 1)
    gate = gate / (np.max(gate) + 1e-9)
    hum = np.sin(2 * np.pi * 100 * t) + 0.4 * np.sin(2 * np.pi * 200 * t)
    pops = _debris(r, length, 6, 1500, 9000, 0.02, 0.0, length)
    return dsp.loopable(0.6 * arc * (0.3 + gate) + 0.15 * hum + 0.4 * pops, 0.4)


@recipe("bulwark")
def bulwark(r, event: str, **_):
    if event == "hum":
        length = 4.0
        t = dsp.t_axis(length)
        hum = (
            np.sin(2 * np.pi * 58 * t)
            + 0.5 * np.sin(2 * np.pi * 116 * t)
            + 0.2 * np.sin(2 * np.pi * 174 * t)
        )
        shimmer = dsp.bandpass(dsp.white(r, length), 2000, 6000) * (
            0.5 + 0.5 * np.sin(2 * np.pi * 0.5 * t)
        )
        return dsp.loopable(0.6 * hum + 0.08 * shimmer, 0.5)
    if event == "deploy":
        length = 1.1
        rise = dsp.saturate(
            dsp.sweep(80, 420, 0.6, -2.0) * dsp.env_adsr(0.6, 0.05, 0.2, 0.7, 0.3), 2.0
        )
        clamp = _clack(r, 0.4, 700, 0.06, 0.6)
        return dsp.fade(
            dsp.mix(
                length, (clamp, 0.9), (rise, 0.6, 0.1), (_thud(r, 0.5, 140, 50, 0.08), 0.8, 0.05)
            )
        )
    length = 1.4  # destroyed
    fall = dsp.saturate(dsp.sweep(420, 50, 0.9, 2.0) * dsp.env_exp(0.9, 0.35), 2.0)
    crack = destruction(r, "cladding_wall")
    return dsp.fade(dsp.mix(length, (fall, 0.7), (crack, 0.6)))


@recipe("breach")
def breach(r, event: str, **_):
    if event == "plant":
        length = 0.8
        clamp = _clack(r, 0.4, 600, 0.05, 0.4)
        beep = np.sin(2 * np.pi * 2200 * dsp.t_axis(0.09)) * dsp.env_adsr(
            0.09, 0.005, 0.02, 0.8, 0.03
        )
        return dsp.fade(dsp.mix(length, (clamp, 1.0), (beep, 0.25, 0.35), (beep, 0.25, 0.55)))
    length = 3.5
    blast = dsp.lowpass(dsp.white(r, length), 6000, 2) * dsp.env_exp(length, 0.12, 0.001)
    sub = _thud(r, length, 70, 22, 0.4, 4.0)
    debris = _debris(r, length, 60, 600, 7000, 0.04, 0.15, 2.5)
    x = dsp.mix(length, (blast, 1.0), (sub, 1.2), (debris, 0.5))
    return dsp.fade(_room(r, x, length, 2.5, 1600, 0.5), 0.0005, 0.4)


# --------------------------------------------------------------------------- ambience, UI


@recipe("crew_bed")
def crew_bed(r, **_):
    length = 12.0
    room = dsp.lowpass(dsp.pink(r, length), 1200, 2) * 0.25
    keys = _debris(r, length, 4, 2500, 9000, 0.004, 0.0, length) * 0.5
    creaks = (
        sum(
            dsp.pad(
                _scrape(r, 0.5, 300, 1500, 0.0) * dsp.env_adsr(0.5, 0.1, 0.1, 0.5, 0.3),
                length,
                r.uniform(0, length - 0.6),
            )
            for _ in range(4)
        )
        * 0.2
    )
    clatter = (
        sum(
            dsp.pad(
                _clack(r, 0.3, r.uniform(600, 1400), 0.05, 0.5), length, r.uniform(0, length - 0.4)
            )
            for _ in range(3)
        )
        * 0.08
    )
    return dsp.loopable(room + keys + creaks + clatter, 0.8)


@recipe("ui_tone")
def ui_tone(r, notes: list, step_s: float = 0.06, decay_s: float = 0.08, **_):
    length = step_s * len(notes) + decay_s * 4
    out = dsp.mix(
        length,
        *[
            (
                dsp.modes(
                    r,
                    decay_s * 4,
                    [f, 2 * f, 3.01 * f],
                    [decay_s, decay_s * 0.5, decay_s * 0.3],
                    [1, 0.25, 0.1],
                    0.0,
                ),
                1.0,
                i * step_s,
            )
            for i, f in enumerate(notes)
        ],
    )
    return dsp.fade(out, 0.002, 0.02)


@recipe("ui_tick")
def ui_tick(r, hz: float = 3200.0, **_):
    length = 0.05
    return dsp.fade(
        _burst(r, length, hz * 0.7, hz * 1.6, 0.004)
        + 0.3 * np.sin(2 * np.pi * hz * dsp.t_axis(length)) * dsp.env_exp(length, 0.006)
    )


@recipe("bell")
def bell(r, **_):
    length = 2.5
    f = 660.0
    ratios = [0.5, 1.0, 1.183, 1.506, 2.0, 2.514, 2.662, 3.011]
    x = dsp.modes(
        r,
        length,
        [f * k for k in ratios],
        [1.2, 0.9, 0.7, 0.6, 0.5, 0.4, 0.35, 0.3],
        [0.4, 1.0, 0.5, 0.4, 0.35, 0.2, 0.15, 0.1],
        0.0,
    )
    return dsp.fade(x, 0.001, 0.3)


def build(recipe_name: str, seed: int, params: dict) -> np.ndarray:
    if recipe_name not in RECIPES:
        raise KeyError(f"unknown recipe {recipe_name!r}")
    return RECIPES[recipe_name](dsp.rng(seed), **params)
