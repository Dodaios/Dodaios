"""Stop/target/trailing trade simulator (behaviour of the frozen research study engine).

Fill model: market entry at the next bar open; protective stop first, then target, inside a bar;
close-based exits fill at the next open; funding charged per settlement while open (entry inclusive,
exit exclusive). Sizing: risk fraction of the sleeve equity at the stop, capped by notional
leverage.
"""

from bisect import bisect_right

from .bars import H1


class Setup:
    __slots__ = ("i", "d", "stop", "target", "tmax", "exit_rule", "min_atr", "max_frac")

    def __init__(
        self, i, d, stop, target=None, tmax=None, exit_rule="fixed", min_atr=None, max_frac=None
    ):
        (
            self.i,
            self.d,
            self.stop,
            self.target,
            self.tmax,
            self.exit_rule,
            self.min_atr,
            self.max_frac,
        ) = i, d, stop, target, tmax, exit_rule, min_atr, max_frac


def simulate(
    s, setups, fund, fee, start, end, daily=None, p1h=None, risk=0.005, levcap=10.0, sleeve=5000.0
):
    """Returns (trades, skipped). Each trade: asset, side, entry_ts, exit_ts, why, R, R_gross,
    R_cost, R_fund, pnl, phase, bars.
    """
    fts = [t for t, _ in fund]
    trades, skipped = [], {"gap_through_stop": 0, "target_behind_entry": 0}
    period_bars = [i for i in range(s.n) if start <= s.ts[i] < end]
    if not period_bars:
        return trades, skipped
    first, last = period_bars[0], period_bars[-1]
    eq, free_from = sleeve, first
    for st in sorted(setups, key=lambda x: x.i):
        e = st.i + 1
        if e < free_from or e < first or e > last:
            continue
        entry, d, a = s.o[e], st.d, s.atr[st.i]
        stop = st.stop
        if (d == 1 and stop >= entry) or (d == -1 and stop <= entry):
            skipped["gap_through_stop"] += 1
            continue
        dist = abs(entry - stop)
        if st.min_atr and dist < st.min_atr * a:
            dist = st.min_atr * a
        if st.max_frac and dist > st.max_frac * entry:
            dist = st.max_frac * entry
        stop = entry - d * dist
        target = None
        if st.target:
            kind, val = st.target
            target = entry + d * val if kind == "pole" else val
            if (d == 1 and target <= entry) or (d == -1 and target >= entry):
                if kind == "abs":
                    skipped["target_behind_entry"] += 1
                    continue
        qty = min(eq * risk / (dist + fee * (entry + stop)), levcap * eq / entry)
        fi = bisect_right(fts, s.ts[e] - 1)
        fund_paid, trail, best = 0.0, None, entry
        x = xi = why = None
        for j in range(e, last + 1):
            t0, t1 = s.ts[j], s.ts[j] + s.iv
            o, h, lo, c = s.o[j], s.h[j], s.l[j], s.c[j]
            if (d == 1 and lo <= stop) or (d == -1 and h >= stop):
                x = min(o, stop) if d == 1 else max(o, stop)
                xi = j
                why = "stop"
            elif target is not None and ((d == 1 and h >= target) or (d == -1 and lo <= target)):
                x = max(o, target) if d == 1 else min(o, target)
                xi = j
                why = "target"
            while fi < len(fund) and fund[fi][0] < t1:
                ft, rate = fund[fi]
                if ft >= t0 and not (x is not None and x == o and j > e):
                    k1 = p1h.idx.get(ft) if p1h is not None else None
                    fund_paid += d * (p1h.o[k1] if k1 is not None else o) * rate
                fi += 1
            if x is not None:
                break
            nxt = None
            if st.tmax and j - e + 1 >= st.tmax:
                x, xi, why = c, j, "time"
                break
            if st.exit_rule == "chandelier":
                best = max(best, c) if d == 1 else min(best, c)
                tr = best - d * 3 * s.atr[j]
                trail = tr if trail is None else (max(trail, tr) if d == 1 else min(trail, tr))
                if (d == 1 and c < trail) or (d == -1 and c > trail):
                    nxt = "trail"
            elif st.exit_rule in ("donchian", "donchian_htf"):
                if (d == 1 and c < min(s.l[j - 10 : j])) or (d == -1 and c > max(s.h[j - 10 : j])):
                    nxt = "channel"
                elif st.exit_rule == "donchian_htf" and daily.htf(t1) != d:
                    nxt = "htf"
            elif st.exit_rule == "eod":
                if (t0 // H1) % 24 == 23:
                    x, xi, why = c, j, "eod"
                    break
            if j == last:
                x, xi, why = c, j, "period_end"
                break
            if nxt:
                x, xi, why = s.o[j + 1], j + 1, nxt
                break
        gross = d * (x - entry)
        cost = fee * (entry + x)
        net_unit = gross - cost - fund_paid
        pnl = qty * net_unit
        eq += pnl
        trades.append(
            {
                "asset": s.asset,
                "side": "long" if d == 1 else "short",
                "entry_ts": s.ts[e],
                "exit_ts": s.ts[xi],
                "why": why,
                "R": net_unit / dist,
                "R_gross": gross / dist,
                "R_cost": cost / dist,
                "R_fund": fund_paid / dist,
                "pnl": pnl,
                "stop_frac": dist / entry,
                "notional_frac": qty * entry / (eq - pnl),
                "phase": daily.phase(s.ts[st.i] + s.iv) if daily else None,
                "bars": xi - e + 1,
            }
        )
        free_from = xi + 1
    return trades, skipped


def summary(trades):
    n = len(trades)
    if not n:
        return {"trades": 0}
    rs = [t["R"] for t in trades]
    w = sum(r for r in rs if r > 0)
    loss = -sum(r for r in rs if r <= 0)
    return {
        "trades": n,
        "hit_rate": round(sum(r > 0 for r in rs) / n, 4),
        "pf": round(w / loss, 3) if loss > 0 else None,
        "mean_R": round(sum(rs) / n, 4),
    }
