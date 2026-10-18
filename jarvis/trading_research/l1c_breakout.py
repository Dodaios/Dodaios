"""L1c: 1h 24-bar breakout confirmed by taker delta > 0.10, volume >= 1.5x 168h median and rising
open interest.

STATUS: hypothesis. Held one test window, NOT confirmed on fresh data (+0.035 R per trade, p =
0.35).
Behaviour matches the frozen research study. Research only.
"""

import statistics

from .bars import H1
from .engine import Setup


def features(s, oi):
    """oi = {ts_ms: open_interest} on the hour grid. doi[i] = OI at bar close / OI at bar open - 1
    (measured).
    """
    n = s.n
    delta = [
        ((2 * tb - v) / v) if v and tb is not None else None
        for v, tb in zip(s.v, s.tb, strict=True)
    ]
    doi = [None] * n
    for i in range(n):
        a, b = oi.get(s.ts[i]), oi.get(s.ts[i] + H1)
        if a and b:
            doi[i] = b / a - 1
    vz = [None] * n
    for i in range(168, n):
        m = statistics.median(s.v[i - 168 : i])
        vz[i] = s.v[i] / m if m > 0 else None
    return {"delta": delta, "doi": doi, "vz": vz}


def setups(s, f, delta_min=0.10, vz_min=1.5):
    out = []
    for i in range(168, s.n - 1):
        if s.atr[i] is None:
            continue
        hh, ll = max(s.h[i - 24 : i]), min(s.l[i - 24 : i])
        d = 1 if s.c[i] > hh else (-1 if s.c[i] < ll else 0)
        if not d:
            continue
        dl, do, vz = f["delta"][i], f["doi"][i], f["vz"][i]
        if not (dl is not None and vz is not None and d * dl > delta_min and vz >= vz_min):
            continue
        if not (do is not None and do > 0):
            continue
        out.append(Setup(i, d, s.c[i] - d * 2 * s.atr[i], exit_rule="chandelier"))
    return out
