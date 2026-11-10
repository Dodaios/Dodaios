"""Small deterministic DSP toolkit for the Verse sound builders (WP19).

Every generated sound is own work: it is computed from seeded noise and
oscillators here, never sampled from a recording. All functions take and
return float64 numpy arrays at ``SR`` Hz, mono unless noted.
"""

from __future__ import annotations

import numpy as np
from scipy import signal

SR = 48_000


def rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def seconds(n: float) -> int:
    return max(1, int(round(n * SR)))


def t_axis(length_s: float) -> np.ndarray:
    return np.arange(seconds(length_s)) / SR


def white(r: np.random.Generator, length_s: float) -> np.ndarray:
    return r.standard_normal(seconds(length_s))


def brown(r: np.random.Generator, length_s: float) -> np.ndarray:
    x = np.cumsum(r.standard_normal(seconds(length_s)))
    x = signal.lfilter([1.0, -1.0], [1.0, -0.995], x)  # leaky: no DC drift
    return x / (np.max(np.abs(x)) + 1e-12)


def pink(r: np.random.Generator, length_s: float) -> np.ndarray:
    # Paul Kellet's economy pink filter.
    b = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
    a = [1.0, -2.494956002, 2.017265875, -0.522189400]
    x = signal.lfilter(b, a, white(r, length_s))
    return x / (np.max(np.abs(x)) + 1e-12)


def _sos(kind: str, freq, order: int = 4) -> np.ndarray:
    nyq = SR / 2
    if isinstance(freq, (tuple, list)):
        wn = [min(max(f / nyq, 1e-4), 0.999) for f in freq]
    else:
        wn = min(max(freq / nyq, 1e-4), 0.999)
    return signal.butter(order, wn, btype=kind, output="sos")


def lowpass(x: np.ndarray, hz: float, order: int = 4) -> np.ndarray:
    return signal.sosfilt(_sos("lowpass", hz, order), x)


def highpass(x: np.ndarray, hz: float, order: int = 4) -> np.ndarray:
    return signal.sosfilt(_sos("highpass", hz, order), x)


def bandpass(x: np.ndarray, lo: float, hi: float, order: int = 2) -> np.ndarray:
    return signal.sosfilt(_sos("bandpass", (lo, hi), order), x)


def peak_eq(x: np.ndarray, hz: float, q: float, gain_db: float) -> np.ndarray:
    a_lin = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * hz / SR
    alpha = np.sin(w0) / (2 * q)
    b = [1 + alpha * a_lin, -2 * np.cos(w0), 1 - alpha * a_lin]
    a = [1 + alpha / a_lin, -2 * np.cos(w0), 1 - alpha / a_lin]
    return signal.lfilter(b, a, x)


def env_exp(length_s: float, decay_s: float, attack_s: float = 0.0005) -> np.ndarray:
    t = t_axis(length_s)
    att = np.clip(t / max(attack_s, 1e-6), 0, 1)
    return att * np.exp(-t / max(decay_s, 1e-6))


def env_adsr(length_s: float, a: float, d: float, s: float, r: float) -> np.ndarray:
    n = seconds(length_s)
    t = np.arange(n) / SR
    out = np.full(n, s)
    out[t < a] = t[t < a] / max(a, 1e-6)
    dm = (t >= a) & (t < a + d)
    out[dm] = 1 - (1 - s) * (t[dm] - a) / max(d, 1e-6)
    rel_start = length_s - r
    rm = t >= rel_start
    out[rm] = s * np.clip(1 - (t[rm] - rel_start) / max(r, 1e-6), 0, 1)
    return out


def sweep(f0: float, f1: float, length_s: float, curve: float = 4.0) -> np.ndarray:
    """Sine whose frequency glides exponentially from f0 to f1."""
    t = t_axis(length_s)
    k = np.exp(-curve * t / length_s)
    freq = f1 + (f0 - f1) * k
    phase = 2 * np.pi * np.cumsum(freq) / SR
    return np.sin(phase)


def modes(
    r: np.random.Generator, length_s: float, freqs, decays, amps=None, detune: float = 0.01
) -> np.ndarray:
    """Sum of decaying sine partials: metal rings, shells, glass."""
    t = t_axis(length_s)
    out = np.zeros_like(t)
    amps = amps if amps is not None else [1.0] * len(freqs)
    for f, d, a in zip(freqs, decays, amps, strict=True):
        f2 = f * (1 + r.uniform(-detune, detune))
        out += a * np.sin(2 * np.pi * f2 * t + r.uniform(0, 2 * np.pi)) * np.exp(-t / d)
    return out


def n_wave(
    length_s: float, dur_s: float, rise_s: float = 0.00004, offset_s: float = 0.0
) -> np.ndarray:
    """Supersonic shock pressure: a near-instant rise to +1, a linear fall to -1, a fast return."""
    t = t_axis(length_s) - offset_s
    out = np.zeros_like(t)
    body = (t >= 0) & (t < dur_s)
    out[body] = 1.0 - 2.0 * t[body] / dur_s
    rise = (t >= -rise_s) & (t < 0)
    out[rise] = 1.0 + t[rise] / rise_s
    back = (t >= dur_s) & (t < dur_s + rise_s)
    out[back] = -1.0 + (t[back] - dur_s) / rise_s
    return out


def friedlander(length_s: float, dur_s: float, decay: float = 1.6) -> np.ndarray:
    """Blast-wave pressure: instant peak, positive phase of dur_s, then a decaying negative one."""
    t = t_axis(length_s) / dur_s
    return (1.0 - t) * np.exp(-decay * t)


def peak_limit(
    x: np.ndarray, ceiling_db: float, lookahead_s: float = 0.0015, release_s: float = 0.025
) -> np.ndarray:
    """Look-ahead peak limiter: shaves the crack and blast peaks, leaves the decay's shape alone."""
    from scipy.ndimage import maximum_filter1d

    ceiling = 10 ** (ceiling_db / 20)
    look = max(1, seconds(lookahead_s))
    ahead = maximum_filter1d(np.abs(x), size=2 * look + 1, mode="constant")
    want = np.minimum(1.0, ceiling / np.maximum(ahead, 1e-12))
    rel = np.exp(-1.0 / max(1.0, release_s * SR))
    gain = np.empty_like(want)
    g = 1.0
    for i, w in enumerate(want):
        g = w if w < g else w + rel * (g - w)
        gain[i] = g
    return x * gain


def glide_bandpass(x: np.ndarray, f0: float, f1: float, q: float, curve: float = 3.0) -> np.ndarray:
    """Band-pass whose centre glides exponentially from f0 to f1 (TPT state variable filter)."""
    n = len(x)
    k = np.exp(-curve * np.arange(n) / max(1, n))
    fc = f1 + (f0 - f1) * k
    g = np.tan(np.pi * np.clip(fc, 20.0, SR * 0.45) / SR)
    damp = 1.0 / q
    out = np.empty(n)
    s1 = s2 = 0.0
    for i in range(n):
        gi = g[i]
        hp = (x[i] - (damp + gi) * s1 - s2) / (1.0 + damp * gi + gi * gi)
        bp = gi * hp + s1
        s1 = gi * hp + bp
        lp = gi * bp + s2
        s2 = gi * bp + lp
        out[i] = bp * damp
    return out


def saturate(x: np.ndarray, drive: float) -> np.ndarray:
    return np.tanh(drive * x) / np.tanh(drive)


def pad(x: np.ndarray, length_s: float, offset_s: float = 0.0) -> np.ndarray:
    n = seconds(length_s)
    out = np.zeros(n)
    o = seconds(offset_s) if offset_s > 0 else 0
    m = min(len(x), n - o)
    if m > 0:
        out[o : o + m] = x[:m]
    return out


def mix(length_s: float, *parts) -> np.ndarray:
    """Mix (signal, gain, offset_s) tuples into one buffer."""
    out = np.zeros(seconds(length_s))
    for part in parts:
        x, g = part[0], part[1]
        off = part[2] if len(part) > 2 else 0.0
        out += g * pad(x, length_s, off)
    return out


def room_ir(
    r: np.random.Generator,
    length_s: float,
    decay_s: float,
    bright_hz: float,
    early=(0.007, 0.013, 0.021, 0.034),
) -> np.ndarray:
    """Synthetic room impulse response: a few early reflections plus a dark noise tail."""
    t = t_axis(length_s)
    tail = r.standard_normal(len(t)) * np.exp(-t * 6.91 / decay_s)  # -60 dB at decay_s
    tail = lowpass(tail, bright_hz, 2)
    ir = 0.35 * tail
    for i, e in enumerate(early):
        idx = seconds(e)
        if idx < len(ir):
            ir[idx] += 0.6 * (0.75**i) * (1 if r.random() > 0.5 else -1)
    ir[0] = 1.0
    return ir / np.sqrt(np.sum(ir**2))


def convolve(x: np.ndarray, ir: np.ndarray, length_s: float) -> np.ndarray:
    y = signal.fftconvolve(x, ir)[: seconds(length_s)]
    return pad(y, length_s)


def fade(x: np.ndarray, in_s: float = 0.0005, out_s: float = 0.01) -> np.ndarray:
    y = x.copy()
    ni, no = seconds(in_s), seconds(out_s)
    y[:ni] *= np.linspace(0, 1, ni)
    y[-no:] *= np.linspace(1, 0, no)
    return y


def loopable(x: np.ndarray, xfade_s: float = 0.5) -> np.ndarray:
    """Crossfade the end into the start so the buffer loops without a click."""
    n = seconds(xfade_s)
    head, body, tail = x[:n], x[n:-n] if len(x) > 2 * n else x, x[-n:]
    w = np.linspace(0, 1, n)
    seam = tail * (1 - w) + head * w
    return np.concatenate([body, seam]) if len(x) > 2 * n else x


def normalize_peak(x: np.ndarray, peak_db: float) -> np.ndarray:
    p = np.max(np.abs(x))
    if p <= 0:
        return x
    return x * (10 ** (peak_db / 20) / p)


def to_pcm16(x: np.ndarray) -> np.ndarray:
    return (np.clip(x, -1.0, 1.0) * 32767.0).astype(np.int16)
