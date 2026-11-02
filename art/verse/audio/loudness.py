"""ITU-R BS.1770-4 loudness: integrated LUFS (gated) and true peak (dBTP).

Used by the reference duel capture check (WP19 acceptance A19.4): integrated
-16 LUFS within 1 LU, true peak at most -1 dBTP.
"""

from __future__ import annotations

import numpy as np
from scipy import signal


def _k_weighting(sr: int) -> list[tuple[np.ndarray, np.ndarray]]:
    # Pre-filter (high shelf) and RLB high-pass, coefficients derived for any rate
    # (BS.1770-4 annex 1; bilinear forms as in libebur128).
    f0, g, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = np.tan(np.pi * f0 / sr)
    vh = 10 ** (g / 20)
    vb = vh**0.4996667741545416
    a0 = 1 + k / q + k * k
    b1 = [(vh + vb * k / q + k * k) / a0, 2 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0]
    a1 = [1.0, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]
    f0, q = 38.13547087602444, 0.5003270373238773
    k = np.tan(np.pi * f0 / sr)
    a0 = 1 + k / q + k * k
    b2 = [1.0, -2.0, 1.0]
    a2 = [1.0, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]
    return [(np.array(b1), np.array(a1)), (np.array(b2), np.array(a2))]


def _as_channels(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    return x[None, :] if x.ndim == 1 else x.T if x.shape[0] > x.shape[1] else x


def integrated_lufs(x: np.ndarray, sr: int) -> float:
    """Gated integrated loudness of a mono or stereo buffer (channels weighted 1.0)."""
    ch = _as_channels(x)
    for b, a in _k_weighting(sr):
        ch = signal.lfilter(b, a, ch, axis=1)
    block, hop = int(0.4 * sr), int(0.1 * sr)
    if ch.shape[1] < block:
        return float("-inf")
    starts = range(0, ch.shape[1] - block + 1, hop)
    z = np.array([np.mean(ch[:, s : s + block] ** 2, axis=1).sum() for s in starts])
    with np.errstate(divide="ignore"):
        lk = -0.691 + 10 * np.log10(z)
    abs_gate = z[lk > -70.0]
    if abs_gate.size == 0:
        return float("-inf")
    rel = -0.691 + 10 * np.log10(np.mean(abs_gate)) - 10.0
    gated = z[(lk > -70.0) & (lk > rel)]
    return float(-0.691 + 10 * np.log10(np.mean(gated)))


def true_peak_dbtp(x: np.ndarray, sr: int) -> float:
    """True peak via 4x oversampling (BS.1770-4 annex 2)."""
    ch = _as_channels(x)
    up = signal.resample_poly(ch, 4, 1, axis=1)
    peak = float(np.max(np.abs(up)))
    return float("-inf") if peak <= 0 else 20 * np.log10(peak)
