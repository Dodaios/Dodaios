"""Liquidity intelligence - research prototype (pure functions, no I/O, no venue access, not wired
anywhere).

Every output carries a provenance tag so a later signal can never present an estimate as a
measurement:
  observed   - exchange raw data (trades, order-book band aggregates, OI, funding as published)
  derived    - deterministic transform of observed data (taker delta, OI change, volume profile from
  bars)
  estimated  - heuristic location without direct data (stop clusters beyond swings / round numbers)
  modelled   - depends on assumed parameters (liquidation clusters from OI x assumed leverage mix)
  unavailable- needed but not obtainable from free sources (reported, never filled with substitutes)
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

OBSERVED, DERIVED, ESTIMATED, MODELLED, UNAVAILABLE = (
    "observed",
    "derived",
    "estimated",
    "modelled",
    "unavailable",
)


@dataclass(frozen=True)
class Bar:
    ts: int
    o: float
    h: float
    lo: float
    c: float
    v: float
    tb: float | None = None  # taker-buy base volume (Binance klines field)


@dataclass(frozen=True)
class Zone:
    # stop_cluster_above / stop_cluster_below / round_number / defended / poc / hvn / lvn / liq_long
    # / liq_short / sweep
    kind: str
    lo: float
    hi: float
    strength: float  # kind-specific, documented per function
    provenance: str
    note: str = ""


@dataclass
class LiquidityContext:
    symbol: str
    ts: int
    price: float
    zones: list[Zone] = field(default_factory=list)
    flow: dict = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ basic features
def atr(bars: list[Bar], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(bars)
    trs = []
    for i, b in enumerate(bars):
        tr = (
            b.h - b.lo
            if i == 0
            else max(b.h - b.lo, abs(b.h - bars[i - 1].c), abs(b.lo - bars[i - 1].c))
        )
        trs.append(tr)
        if i >= n:
            out[i] = sum(trs[i - n + 1 : i + 1]) / n
    return out


def taker_delta(b: Bar) -> float | None:
    """(aggressive buy - aggressive sell) / volume in [-1, 1]; derived from the kline taker-buy
    field.
    """
    if b.tb is None or b.v <= 0:
        return None
    return (2 * b.tb - b.v) / b.v


def volume_z(bars: list[Bar], i: int, look: int = 168) -> float | None:
    if i < look:
        return None
    m = statistics.median(x.v for x in bars[i - look : i])
    return bars[i].v / m if m > 0 else None


# ------------------------------------------------------------------ Q2 stop clusters (estimated)
def swing_points(bars: list[Bar], k: int = 3) -> tuple[list[int], list[int]]:
    """Pivot highs/lows confirmed k bars later (index of the pivot bar); only pivots with i+k < len
    are returned.
    """
    ph, pl = [], []
    for i in range(k, len(bars) - k):
        win = bars[i - k : i + k + 1]
        if bars[i].h == max(x.h for x in win) and bars[i].h > max(
            x.h for x in win if x is not bars[i]
        ):
            ph.append(i)
        if bars[i].lo == min(x.lo for x in win) and bars[i].lo < min(
            x.lo for x in win if x is not bars[i]
        ):
            pl.append(i)
    return ph, pl


def stop_clusters(bars: list[Bar], atr_now: float, k: int = 3, keep: int = 5) -> list[Zone]:
    """Likely stop locations just beyond the most recent unbroken swing highs/lows (estimated, never
    observed).
    strength = number of swings within 0.25 ATR of each other (equal highs/lows attract more stops).
    """
    ph, pl = swing_points(bars, k)
    last = bars[-1]
    zones = []
    for idx, side in ((ph, 1), (pl, -1)):
        lvls = []
        for i in reversed(idx):
            p = bars[i].h if side == 1 else bars[i].lo
            later = bars[i + 1 :]
            broken = any(x.h > p for x in later) if side == 1 else any(x.lo < p for x in later)
            if not broken:
                lvls.append(p)
            if len(lvls) >= keep:
                break
        for p in lvls:
            n = sum(1 for q in lvls if abs(q - p) <= 0.25 * atr_now)
            lo, hi = (p, p + 0.25 * atr_now) if side == 1 else (p - 0.25 * atr_now, p)
            zones.append(
                Zone(
                    "stop_cluster_above" if side == 1 else "stop_cluster_below",
                    lo,
                    hi,
                    float(n),
                    ESTIMATED,
                    "beyond an unbroken swing; location inferred, order sizes unknown",
                )
            )
    _ = last
    return zones


def round_levels(price: float, step: float, n: int = 2) -> list[Zone]:
    """Round numbers near price; stops/limits cluster there empirically (OSL2005), sizes unknown ->
    estimated.
    """
    base = math.floor(price / step) * step
    return [
        Zone("round_number", base + j * step, base + j * step, 1.0, ESTIMATED, f"step {step:g}")
        for j in range(-n + 1, n + 1)
    ]


# ------------------------------------------------------------------ Q4 defended zones (derived)
def defended_zones(
    bars: list[Bar], atr_now: float, min_touches: int = 3, tol_atr: float = 0.25
) -> list[Zone]:
    """Price bands where >= min_touches bars wicked in and closed back out (rejections). strength =
    touches.
    """
    out = []
    for side in (1, -1):
        ext = [(b.h if side == 1 else b.lo, i) for i, b in enumerate(bars)]
        used = set()
        for p, i in sorted(ext, key=lambda x: -x[0] * side):
            if i in used:
                continue
            band = [(q, j) for q, j in ext if abs(q - p) <= tol_atr * atr_now]
            rej = [
                j
                for q, j in band
                if (
                    bars[j].c < q - 0.3 * (bars[j].h - bars[j].lo)
                    if side == 1
                    else bars[j].c > q + 0.3 * (bars[j].h - bars[j].lo)
                )
            ]
            if len(rej) >= min_touches:
                lo, hi = min(q for q, _ in band), max(q for q, _ in band)
                out.append(
                    Zone(
                        "defended",
                        lo,
                        hi,
                        float(len(rej)),
                        DERIVED,
                        "resistance" if side == 1 else "support",
                    )
                )
                used.update(j for _, j in band)
    return out


# ------------------------------------------------------------------ volume profile (derived;
# approximation from bars)
def volume_profile(bars: list[Bar], bins: int = 50) -> list[Zone]:
    """Spreads each bar's volume evenly over its range (approximation; exact profile needs
    aggTrades).
    """
    lo, hi = min(b.lo for b in bars), max(b.h for b in bars)
    if hi <= lo:
        return []
    w = (hi - lo) / bins
    hist = [0.0] * bins
    for b in bars:
        a, z = int((b.lo - lo) / w), min(bins - 1, int((b.h - lo) / w))
        for k in range(a, z + 1):
            hist[k] += b.v / (z - a + 1)
    poc = max(range(bins), key=lambda k: hist[k])
    med = statistics.median(hist)
    zones = [
        Zone("poc", lo + poc * w, lo + (poc + 1) * w, hist[poc], DERIVED, "bar-range approximation")
    ]
    for k in range(bins):
        if k != poc and hist[k] >= 1.5 * med:
            zones.append(
                Zone(
                    "hvn", lo + k * w, lo + (k + 1) * w, hist[k], DERIVED, "bar-range approximation"
                )
            )
        elif hist[k] <= 0.5 * med:
            zones.append(
                Zone(
                    "lvn", lo + k * w, lo + (k + 1) * w, hist[k], DERIVED, "bar-range approximation"
                )
            )
    return zones


# ------------------------------------------------------------------ Q5/Q6 absorption + sweeps
# (derived)
def absorption(bars: list[Bar], i: int, atr_i: float) -> dict | None:
    """High volume, small range, strong one-sided aggression: aggressors met passive size (proxy, no
    book data).
    """
    vz, d = volume_z(bars, i), taker_delta(bars[i])
    if vz is None or d is None:
        return None
    b = bars[i]
    hit = vz >= 2.0 and (b.h - b.lo) <= 0.6 * atr_i and abs(d) >= 0.10
    return {
        "absorption": hit,
        "side_absorbed": ("buyers" if d > 0 else "sellers") if hit else None,
        "vz": vz,
        "delta": d,
        "provenance": DERIVED,
    }


def sweep(bars: list[Bar], i: int, w: int = 24) -> int:
    """+1: swept lows and closed back above (long idea); -1: swept highs and closed back below; 0:
    none.
    """
    if i < w:
        return 0
    hh, ll = max(b.h for b in bars[i - w : i]), min(b.lo for b in bars[i - w : i])
    b = bars[i]
    up, dn = b.h > hh and b.c < hh, b.lo < ll and b.c > ll
    return 0 if up == dn else (-1 if up else 1)


def breakout(bars: list[Bar], i: int, w: int = 24) -> int:
    if i < w:
        return 0
    hh, ll = max(b.h for b in bars[i - w : i]), min(b.lo for b in bars[i - w : i])
    return 1 if bars[i].c > hh else (-1 if bars[i].c < ll else 0)


# ------------------------------------------------------------------ Q8 OI / funding / flow state
def flow_state(
    bars: list[Bar],
    i: int,
    oi_open: float | None,
    oi_close: float | None,
    funding: float | None,
    depth_bid_1pct: float | None = None,
    depth_ask_1pct: float | None = None,
) -> dict:
    """Plain readings with provenance; the OI/price quadrant is labelled as interpretation."""
    b = bars[i]
    doi = (oi_close / oi_open - 1) if oi_open and oi_close else None
    ret = b.c / b.o - 1
    quad = None
    if doi is not None:
        quad = {
            (True, True): "price up, OI up (new longs dominate - interpretation)",
            (True, False): "price up, OI down (short covering - interpretation)",
            (False, True): "price down, OI up (new shorts dominate - interpretation)",
            (False, False): "price down, OI down (long liquidation/closing - interpretation)",
        }[(ret >= 0, doi >= 0)]
    return {
        "delta": (taker_delta(b), DERIVED),
        "volume_z": (volume_z(bars, i), DERIVED),
        "oi_change": (doi, OBSERVED if doi is not None else UNAVAILABLE),
        "oi_quadrant": quad,
        "funding": (funding, OBSERVED if funding is not None else UNAVAILABLE),
        "depth_ratio_1pct": (
            (depth_bid_1pct / depth_ask_1pct) if depth_bid_1pct and depth_ask_1pct else None,
            OBSERVED if depth_bid_1pct and depth_ask_1pct else UNAVAILABLE,
        ),
    }


# ------------------------------------------------------------------ Q3 liquidation clusters
# (modelled)
def liquidation_clusters(
    price_oi: list[tuple[float, float, float]],
    mix: dict[int, float],
    mmr: float = 0.005,
    long_share: float = 0.5,
) -> list[Zone]:
    """price_oi: (close, oi_before, oi_after) per bar. Adds OI increases at assumed leverage;
    removes nothing.
    MODELLED: the leverage mix and side split are assumptions; S3b tests whether such levels attract
    price.
    """
    acc: dict[tuple[int, float], float] = {}
    for c, a, b in price_oi:
        if a and b and b > a:
            n = (b - a) * c
            for lev, w in mix.items():
                for side, share in ((1, long_share), (-1, 1 - long_share)):
                    p = round(c * ((1 - 1 / lev + mmr) if side == 1 else (1 + 1 / lev - mmr)), -1)
                    acc[(side, p)] = acc.get((side, p), 0.0) + n * share * w
    return [
        Zone("liq_long" if s == 1 else "liq_short", p, p, v, MODELLED, "assumed leverage mix")
        for (s, p), v in acc.items()
    ]


# ------------------------------------------------------------------ execution check on the trading
# venue
def execution_check(
    signal_price: float,
    venue_mid: float,
    venue_spread_bps: float,
    venue_cost_bps_at_size: float | None,
    stop_dist_frac: float,
    fee_frac: float = 0.0006,
    max_dev_bps: float = 10.0,
    max_spread_bps: float = 5.0,
    max_cost_r: float = 0.20,
) -> dict:
    """A Binance signal is never forwarded blindly: the executing venue must be close in price,
    tight and deep enough.
    Costs are expressed in R (round trip fees + modelled slippage both ways) against the planned
    stop distance.
    """
    reasons = []
    dev = abs(venue_mid / signal_price - 1) * 1e4
    if dev > max_dev_bps:
        reasons.append(f"venue price deviates {dev:.1f} bp from the analysis venue")
    if venue_spread_bps > max_spread_bps:
        reasons.append(f"venue spread {venue_spread_bps:.2f} bp")
    if venue_cost_bps_at_size is None:
        reasons.append("venue book too thin for the order size")
        cost_r = None
    else:
        cost_r = (
            2 * fee_frac + 2 * venue_cost_bps_at_size / 1e4 + venue_spread_bps / 1e4
        ) / stop_dist_frac
        if cost_r > max_cost_r:
            reasons.append(f"cost {cost_r:.2f} R above {max_cost_r} R")
    return {"ok": not reasons, "reasons": reasons, "price_dev_bps": dev, "cost_r": cost_r}


def context(
    symbol: str,
    bars: list[Bar],
    round_step: float,
    oi_pair=(None, None),
    funding=None,
    depth=(None, None),
    look: int = 500,
) -> LiquidityContext:
    """Assemble the context for the last closed bar; missing inputs are listed, never imputed."""
    a = atr(bars)[-1]
    win = bars[-look:]
    ctx = LiquidityContext(symbol, bars[-1].ts, bars[-1].c)
    ctx.zones += (
        stop_clusters(win, a)
        + round_levels(bars[-1].c, round_step)
        + defended_zones(win[-200:], a)
        + volume_profile(win)
    )
    i = len(bars) - 1
    ctx.flow = flow_state(bars, i, oi_pair[0], oi_pair[1], funding, depth[0], depth[1])
    ctx.flow["absorption"] = absorption(bars, i, a)
    ctx.flow["sweep"] = sweep(bars, i)
    ctx.flow["breakout"] = breakout(bars, i)
    for name, val in (
        ("open interest", oi_pair[1]),
        ("funding", funding),
        ("order-book depth", depth[0]),
    ):
        if val is None:
            ctx.missing.append(name)
    ctx.missing += [
        "liquidation history (no free source)",
        "L2/L3 order-book history (no free source)",
        "exact footprint (needs aggTrades per trade)",
    ]
    return ctx
