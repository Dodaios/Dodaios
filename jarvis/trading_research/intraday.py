"""Intraday research rules V1 (fair value gap + liquidity sweep), V2 (previous-day box), V3
(combined) and components.

STATUS: all variants REJECTED - no variant was profitable after realistic costs in research (gross
edge ~0 R,
costs 0.15-1.2 R per trade). Kept only for reproducibility and future pre-registered hypotheses.

All setups are generated SHORT-side on a series; long setups are the same code on the mirrored
series
(prices negated, highs/lows swapped, taker delta negated). R, costs and funding stay correct because
every
formula uses signed prices (funding paid = -entry * rate for a short in mirrored space = +price *
rate for a long).
"""

from bisect import bisect_left, bisect_right

M5, M15, H1, D1 = 300_000, 900_000, 3_600_000, 86_400_000
IV = {"5m": M5, "15m": M15, "1h": H1}
TMAX = {"5m": 144, "15m": 96, "1h": 72}
RETEST_N = {"5m": 24, "15m": 12, "1h": 6}
BASE, HARSH, MAKER = 0.0012, 0.0017, 0.0004
K = 3


def wilder_atr(h, lo, c, n=14):
    size = len(c)
    tr = [h[0] - lo[0]] + [
        max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(1, size)
    ]
    out, a = [None] * size, None
    for i in range(size):
        if i == n - 1:
            a = sum(tr[:n]) / n
        elif i >= n:
            a = (a * (n - 1) + tr[i]) / n
        out[i] = a
    return out


class Series:
    def __init__(self, asset, tf, rows, oi, funding, mirror):
        self.asset, self.tf, self.iv, self.mirror = asset, tf, IV[tf], mirror
        ts, o, h, lo, c, v, tb = (list(x) for x in zip(*rows, strict=True))
        self.ts, self.v = ts, v
        if mirror:
            self.o, self.h, self.l, self.c = (
                [-x for x in o],
                [-x for x in lo],
                [-x for x in h],
                [-x for x in c],
            )
        else:
            self.o, self.h, self.l, self.c = o, h, lo, c
        sgn = -1 if mirror else 1
        # short-space delta: positive = flow in the setup's direction (sells for a short)
        self.flow_sell = [
            (-(2 * b - x) / x) * sgn if x > 0 else 0.0 for x, b in zip(v, tb, strict=True)
        ]
        self.vol, self.tbuy = v, tb
        self.n = len(ts)
        self.atr = wilder_atr(self.h, self.l, self.c)
        self.ph, self.pl = [], []
        for j in range(K, self.n - K):
            if self.h[j] > max(self.h[j - K : j]) and self.h[j] >= max(self.h[j + 1 : j + K + 1]):
                self.ph.append(j)
            if self.l[j] < min(self.l[j - K : j]) and self.l[j] <= min(self.l[j + 1 : j + K + 1]):
                self.pl.append(j)
        self.pl_known = self._known(self.pl)
        self.ph_known = self._known(self.ph)
        self.oi_ts, self.oi_v = oi
        self.f_ts, self.f_r = funding
        # day structure
        self.day = [t // D1 for t in ts]
        per_day = D1 // self.iv
        first, cnt = {}, {}
        for i, d in enumerate(self.day):
            first.setdefault(d, i)
            cnt[d] = cnt.get(d, 0) + 1
        self.day_first = first
        self.box = {}
        for d in first:
            p = d - 1
            if p in first and cnt[p] == per_day:
                a, b = first[p], first[p] + per_day
                self.box[d] = (
                    max(self.h[a:b]),
                    min(self.l[a:b]),
                )  # (PDH, PDL) in this series' space

    def _known(self, piv):
        out, m = [-1] * self.n, -1
        for i in range(self.n):
            while m + 1 < len(piv) and piv[m + 1] + K <= i:
                m += 1
            out[i] = m
        return out

    def oi_at(self, t):
        k = bisect_right(self.oi_ts, t) - 1
        return self.oi_v[k] if k >= 0 else None

    def last_swing_low(self, i):
        m = self.pl_known[i]
        return (self.pl[m], self.l[self.pl[m]]) if m >= 0 else (None, None)

    def last_swing_high(self, i):
        m = self.ph_known[i]
        return (self.ph[m], self.h[self.ph[m]]) if m >= 0 else (None, None)


def load(db, asset, tf, mirror):
    rows = db.execute(
        "select ts, open, high, low, close, volume, taker_buy from bars"
        " where symbol=? and interval_ms=? order by ts",
        (asset, IV[tf]),
    ).fetchall()
    oi = db.execute("select ts, oi from oi where symbol=? order by ts", (asset,)).fetchall()
    fu = db.execute("select ts, rate from funding where symbol=? order by ts", (asset,)).fetchall()
    return Series(
        asset,
        tf,
        rows,
        ([r[0] for r in oi], [r[1] for r in oi]),
        ([round(r[0] / 60_000) * 60_000 for r in fu], [r[1] for r in fu]),
        mirror,
    )


# -----------------------------------------------------------------------------------------------
# trade simulation (short in series space)
def run_trade(s, f, entry, stop, target, limit_fill, day_end, tmax):
    """Returns dict or None (gap through stop). f = fill bar; entry = fill price (series space)."""
    if stop <= entry:
        return None
    d0 = s.day[f]
    x = xi = why = None
    exit_at_open = False
    k = f
    while k < s.n:
        o, h, lo, c = s.o[k], s.h[k], s.l[k], s.c[k]
        if h >= stop:
            x, xi, why = (stop if (k == f and limit_fill) else max(o, stop)), k, "stop"
            break
        if target is not None and not (k == f and limit_fill) and lo <= target:
            x, xi, why = min(o, target), k, "target"
            break
        if k - f + 1 >= tmax:
            x, xi, why = c, k, "time"
            break
        if k + 1 < s.n and day_end and s.day[k + 1] != d0:
            x, xi, why, exit_at_open = s.o[k + 1], k + 1, "day_end", True
            break
        if k + 1 >= s.n:
            x, xi, why = c, k, "data_end"
            break
        k += 1
    t_in = s.ts[f]
    t_out = s.ts[xi]
    lo = bisect_right(s.f_ts, t_in) if limit_fill else bisect_left(s.f_ts, t_in)
    hi = bisect_left(s.f_ts, t_out) if exit_at_open else bisect_right(s.f_ts, t_out)
    fund_paid = sum(-entry * s.f_r[q] for q in range(lo, hi))
    dist = stop - entry
    gross = entry - x
    cost = BASE * (abs(entry) + abs(x))
    R = (gross - cost - fund_paid) / dist
    return {
        "asset": s.asset,
        "side": "long" if s.mirror else "short",
        "fill_ts": t_in,
        "exit_ts": t_out,
        "why": why,
        "R": R,
        "R_gross": gross / dist,
        "R_cost": cost / dist,
        "R_fund": fund_paid / dist,
        "R_harsh": R - (HARSH - BASE) * (abs(entry) + abs(x)) / dist,
        "R_maker": R + ((BASE - MAKER) * abs(entry) / dist if limit_fill else 0.0),
        "risk_atr": dist / s.atr[f] if s.atr[f] else None,
        "risk_frac": dist / abs(entry),
        "bars": xi - f + 1,
        "limit": limit_fill,
        "_f": f,
        "_entry": entry,
        "_stop": stop,
        "_target": target,
        "_day_end": day_end,
    }


def mirror_trade(s, t):
    """Random-direction benchmark: same fill bar and price, opposite side, same stop distance and
    target distance.
    """
    dist = t["_stop"] - t["_entry"]
    e = t["_entry"]
    # the opposite side in series space is a long: simulate it as a short on the negated prices
    neg = getattr(s, "_neg", None)
    if neg is None:
        neg = s._neg = _Neg(s)
    tgt = None if t["_target"] is None else -(e + (e - t["_target"]))
    r = run_trade(neg, t["_f"], -e, -e + dist, tgt, t["limit"], t["_day_end"], TMAX[s.tf])
    return r


class _Neg:
    """view of a Series with negated prices (long side of the same series) for the benchmark."""

    def __init__(self, s):
        self.asset, self.tf, self.iv, self.mirror = s.asset, s.tf, s.iv, not s.mirror
        self.o, self.h, self.l, self.c = (
            [-x for x in s.o],
            [-x for x in s.l],
            [-x for x in s.h],
            [-x for x in s.c],
        )
        self.ts, self.day, self.n, self.atr, self.f_ts, self.f_r = (
            s.ts,
            s.day,
            s.n,
            s.atr,
            s.f_ts,
            s.f_r,
        )


# -----------------------------------------------------------------------------------------------
# setup builders (short side)
def sweep_events_swing(s):
    """V1 pools: most recent confirmed swing high within 96 bars, not traded through. Yields (s_bar,
    level).
    """
    active = []  # (p, level)
    nxt = 0
    for i in range(s.n):
        while nxt < len(s.ph) and s.ph[nxt] + K <= i:
            p = s.ph[nxt]
            active.append((p, s.h[p]))
            nxt += 1
        active = [(p, lv) for p, lv in active if p >= i - 96]
        if active:
            p, lv = active[-1]
            if s.h[i] > lv:
                yield i, lv
        active = [(p, lv) for p, lv in active if lv >= s.h[i]]


def sweep_events_box(s):
    """V2B/V3: first bar of the day whose high exceeds PDH. Yields (s_bar, PDH)."""
    for d, i0 in s.day_first.items():
        if d not in s.box:
            continue
        pdh, _ = s.box[d]
        i = i0
        while i < s.n and s.day[i] == d:
            if s.h[i] > pdh:
                yield i, pdh
                break
            i += 1


def return_bar(s, sb, level):
    for r in range(sb, min(sb + 4, s.n)):
        if s.c[r] < level:
            return r
    return None


def structure_shift(s, sb, r, X):
    _, RL = s.last_swing_low(sb)
    if RL is None:
        return None
    for k in range(r, min(r + 25, s.n)):
        if s.c[k] > X:
            return None
        if s.c[k] < RL:
            return k
    return None


def find_fvg(s, sb, m):
    for j in range(m, max(sb, 2) - 1, -1):
        if s.l[j - 2] > s.h[j] and s.atr[j] and s.l[j - 2] - s.h[j] >= 0.10 * s.atr[j]:
            return j
    return None


def flow_oi_ok(s, sb, r, m):
    vol = sum(s.vol[r : m + 1])
    if vol <= 0:
        return False
    flow = sum(s.flow_sell[q] * s.vol[q] for q in range(r, m + 1)) / vol
    a, b = s.oi_at(s.ts[sb - 1]), s.oi_at(s.ts[m])
    return flow >= 0.05 and a is not None and b is not None and b < a


def risk_ok(s, i, dist):
    a = s.atr[i]
    return a is not None and 0.25 * a <= dist <= 6 * a


def limit_entry(s, m, edge, X, target_fn, stop, day_end):
    """sell limit at edge valid for bars m+1..m+24; returns (fill_bar, price, target) or
    (cancel_bar, None, None).
    """
    for k in range(m + 1, min(m + 25, s.n)):
        if day_end and s.day[k] != s.day[m]:
            return k, None, None
        if s.h[k] >= edge:
            price = max(s.o[k], edge)
            return k, price, target_fn(price)
        if s.c[k] > X:
            return k, None, None
        tgt = target_fn(edge)
        if tgt is not None and s.l[k] <= tgt:
            return k, None, None
    return min(m + 24, s.n - 1), None, None


def build(s, rule, tgt_kind):
    """Returns list of candidate dicts with keys: known (bar index when the order/entry is decided)
    and a closure to simulate.
    """
    out = []
    tf = s.tf
    if rule in ("V1", "V1FO", "V3", "V3FO", "V3_NOFVG"):
        events = sweep_events_swing(s) if rule.startswith("V1") else sweep_events_box(s)
        for sb, level in events:
            r = return_bar(s, sb, level)
            if r is None:
                continue
            X = max(s.h[sb : r + 1])
            m = structure_shift(s, sb, r, X)
            if m is None:
                continue
            if rule.startswith("V3") and s.day[m] != s.day[sb]:
                continue
            if rule in ("V1FO", "V3FO") and not flow_oi_ok(s, sb, r, m):
                continue
            stop = X + 0.10 * s.atr[m]
            day_end = rule.startswith("V3")
            if rule.startswith("V3"):
                pdh, pdl = s.box[s.day[sb]]
                mid = (pdh + pdl) / 2
            if rule == "V3_NOFVG":
                out.append(
                    {
                        "known": m,
                        "kind": "market",
                        "stop": stop,
                        "target": ("abs_min", mid, 0.5),
                        "day_end": True,
                    }
                )
                continue
            j = find_fvg(s, sb, m)
            if j is None:
                continue
            edge = s.h[j]
            if rule.startswith("V1"):
                lo96 = min(s.l[max(0, sb - 96) : sb]) if sb > 0 else None
                tk = {"T2R": ("R", 2), "T3R": ("R", 3), "TLIQ": ("abs_min", lo96, 1.0)}[tgt_kind]
            else:
                tk = {"T1": ("abs_min", mid, 0.5), "T2": ("R", 2)}[tgt_kind]
            out.append(
                {
                    "known": m,
                    "kind": "limit",
                    "edge": edge,
                    "X": X,
                    "stop": stop,
                    "target": tk,
                    "day_end": day_end,
                }
            )
    elif rule == "FVG_ONLY":
        for j in range(2, s.n - 1):
            if s.l[j - 2] > s.h[j] and s.atr[j] and s.l[j - 2] - s.h[j] >= 0.10 * s.atr[j]:
                stop = s.h[j - 2] + 0.10 * s.atr[j]
                out.append(
                    {
                        "known": j,
                        "kind": "limit",
                        "edge": s.h[j],
                        "X": stop,
                        "stop": stop,
                        "target": ("R", 2),
                        "day_end": False,
                    }
                )
    elif rule in ("V2A", "V2B", "V2C"):
        for d, i0 in s.day_first.items():
            if d not in s.box:
                continue
            pdh, pdl = s.box[d]
            mid = (pdh + pdl) / 2
            idx = []
            i = i0
            while i < s.n and s.day[i] == d:
                idx.append(i)
                i += 1
            # V2A short = breakdown below PDL + retest (mirror of the long rule)
            if rule == "V2A":
                b = next((q for q in idx if s.c[q] < pdl), None)
                if b is None:
                    continue
                t = None
                for q in range(b + 1, min(b + 1 + RETEST_N[tf], idx[-1] + 1)):
                    if s.h[q] >= pdl - 0.10 * s.atr[q] and s.c[q] < pdl:
                        t = q
                        break
                    if s.c[q] > pdl:
                        break
                if t is None:
                    continue
                stop = s.h[t] + 0.10 * s.atr[t]
                tk = {"T1": ("R", 2), "T2": ("abs_min", pdl - (pdh - pdl), 1.0), "T3": None}[
                    tgt_kind
                ]
                out.append(
                    {"known": t, "kind": "market", "stop": stop, "target": tk, "day_end": True}
                )
            elif rule == "V2B":
                sb = next((q for q in idx if s.h[q] > pdh), None)
                if sb is None:
                    continue
                r = None
                for q in range(sb, min(sb + 4, idx[-1] + 1)):
                    if s.c[q] < pdh:
                        r = q
                        break
                if r is None:
                    continue
                stop = max(s.h[sb : r + 1]) + 0.10 * s.atr[r]
                tk = {"T1": ("abs_min", mid, 0.5), "T2": ("abs_min", pdl, 0.5), "T3": ("R", 2)}[
                    tgt_kind
                ]
                out.append(
                    {"known": r, "kind": "market", "stop": stop, "target": tk, "day_end": True}
                )
            # V2C short: close < MID, close > PDL, first close below the most recent confirmed swing
            # low
            else:
                for q in idx:
                    if q < 1:
                        continue
                    p, lv = s.last_swing_low(q)
                    if lv is None:
                        continue
                    if s.c[q] < mid and s.c[q] > pdl and s.c[q] < lv <= s.c[q - 1]:
                        _, sh = s.last_swing_high(q)
                        if sh is None:
                            break
                        stop = sh + 0.10 * s.atr[q]
                        tk = {"T1": ("abs_min", pdl, 1.0), "T2": ("R", 2), "T3": None}[tgt_kind]
                        out.append(
                            {
                                "known": q,
                                "kind": "market",
                                "stop": stop,
                                "target": tk,
                                "day_end": True,
                            }
                        )
                        break
    return sorted(out, key=lambda x: x["known"])


def target_from(tk, entry, stop):
    if tk is None:
        return None
    dist = stop - entry
    if tk[0] == "R":
        return entry - tk[1] * dist
    lvl, min_r = tk[1], tk[2]
    if lvl is None or entry - lvl < min_r * dist:
        return "skip"
    return lvl


def simulate(s, cands, tmax):
    trades, free_from, skipped = [], 0, {"risk": 0, "target": 0, "gap": 0, "no_fill": 0, "busy": 0}
    for cd in cands:
        m = cd["known"]
        if m < free_from or m + 1 >= s.n:
            skipped["busy"] += 1
            continue
        if cd["kind"] == "market":
            f = m + 1
            if cd["day_end"] and s.day[f] != s.day[m]:
                continue
            entry, stop = s.o[f], cd["stop"]
            dist = stop - entry
            if dist <= 0:
                skipped["gap"] += 1
                continue
            if not risk_ok(s, m, dist):
                skipped["risk"] += 1
                continue
            tgt = target_from(cd["target"], entry, stop)
            if tgt == "skip":
                skipped["target"] += 1
                continue
            t = run_trade(s, f, entry, stop, tgt, False, cd["day_end"], tmax)
        else:
            edge, stop = cd["edge"], cd["stop"]
            if not risk_ok(s, m, stop - edge):
                skipped["risk"] += 1
                continue
            if target_from(cd["target"], edge, stop) == "skip":
                skipped["target"] += 1
                continue
            k, price, tgt = limit_entry(
                s,
                m,
                edge,
                cd["X"],
                lambda p, cd=cd, stop=stop: (
                    None if (v := target_from(cd["target"], p, stop)) == "skip" else v
                ),
                stop,
                cd["day_end"],
            )
            if price is None:
                skipped["no_fill"] += 1
                free_from = k + 1
                continue
            if price >= stop or target_from(cd["target"], price, stop) == "skip":
                skipped["gap"] += 1
                free_from = k + 1
                continue
            t = run_trade(s, k, price, stop, tgt, True, cd["day_end"], tmax)
        if t is None:
            skipped["gap"] += 1
            continue
        t["known_ts"] = s.ts[m]
        trades.append(t)
        free_from = _idx(s, t["exit_ts"]) + 1
    return trades, skipped


def _idx(s, ts):
    return bisect_left(s.ts, ts)
