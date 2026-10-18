"""H1: 4h time-series momentum (L=252, vol target 20 %, max 2x) - the strongest candidate so far
(Phase C).

sleeve() is copied verbatim from the frozen H1 study (plan sha 154ec150...), so the frozen results
reproduce exactly (optional parity test, see tests/unit/trading_research/test_parity_optional.py).
portfolio() combines equal sleeves like the study.
STATUS: research candidate (BTC/ETH only). Not confirmed for real money; does not generalise to
other coins in
research. Research only: not connected to any job, bot or order path. H1 has no regular stop; the
risk module
adds the catastrophe stop as a separate, testable rule.
"""

import math
from datetime import UTC, datetime

H4 = 240 * 60_000
ANN = math.sqrt(6 * 365)
BASE_COST = {"fee_per_fill": 0.0006, "half_spread_per_fill": 0.0001, "slippage_per_fill": 0.0005}
HARSH_COST = {"fee_per_fill": 0.0006, "half_spread_per_fill": 0.0001, "slippage_per_fill": 0.001}
FROZEN = {"L": 252, "V": 42, "tv": 0.20, "maxlev": 2.0}


def iso(t):
    return datetime.fromtimestamp(t / 1000, UTC).strftime("%Y-%m-%d %H:%M")


def sleeve(d, L, V, tv, maxlev, cost, with_funding, start, end, equity0):
    ts, op, cl = d["ts"], d["open"], d["close"]
    idx = {t: i for i, t in enumerate(ts)}
    per_fill = cost["fee_per_fill"] + cost["half_spread_per_fill"] + cost["slippage_per_fill"]
    lr = [0.0] + [math.log(cl[i] / cl[i - 1]) for i in range(1, len(cl))]
    period = [i for i, t in enumerate(ts) if start <= t < end]
    first, last = period[0], period[-1]
    cash, pos = equity0, None  # pos: dict(dir, qty, entry_px, entry_ts, entry_eq, cost, funding)
    trades, curve = [], []
    fund = [(t, r) for t, r in d["fund"] if start <= t < end]
    fi = 0
    costs_paid = funding_paid = 0.0

    def close_pos(px, t):
        nonlocal cash, pos, costs_paid
        c = abs(pos["qty"]) * px * per_fill
        pnl = pos["dir"] * pos["qty"] * (px - pos["entry_px"])
        cash += pnl - c
        costs_paid += c
        net = pnl - c - pos["cost"] + pos["funding"]
        trades.append(
            {
                "side": "long" if pos["dir"] > 0 else "short",
                "entry": iso(pos["entry_ts"]),
                "exit": iso(t),
                "net": net,
                "net_pct": net / pos["entry_eq"],
                "funding": pos["funding"],
            }
        )
        pos = None

    for i in range(first, last + 1):
        t = ts[i]
        # funding events up to (not including) this bar's open are settled before trading at the
        # open
        while fi < len(fund) and fund[fi][0] < t:
            # events strictly before the bar open were handled in the previous bar's loop below
            fi += 1
        # 1) execute the decision taken at the previous close, at this bar's open
        if i - 1 >= L and i - 1 >= V:
            m = cl[i - 1] / cl[i - 1 - L] - 1
            want = 1 if m > 0 else (-1 if m < 0 else 0)
        else:
            want = 0
        if i == first and i - 1 < 0:
            want = 0
        cur = pos["dir"] if pos else 0
        if want != cur:
            if pos:
                close_pos(op[i], t)
            if want != 0 and cash > 0:
                rets = lr[i - V : i]
                mu = sum(rets) / V
                sigma = math.sqrt(sum((x - mu) ** 2 for x in rets) / (V - 1)) * ANN
                notional = cash * min(tv / sigma, maxlev) if sigma > 0 else 0.0
                qty = notional / op[i]
                c = notional * per_fill
                cash -= c
                costs_paid += c
                pos = {
                    "dir": want,
                    "qty": qty,
                    "entry_px": op[i],
                    "entry_ts": t,
                    "entry_eq": cash + c,
                    "cost": c,
                    "funding": 0.0,
                }
        # 2) funding events inside this bar [t, t + 4h): position held from its entry (inclusive)
        while fi < len(fund) and fund[fi][0] < t + H4:
            ft, rate = fund[fi]
            if pos and with_funding and pos["entry_ts"] <= ft:
                px = op[idx[ft]] if ft in idx else cl[i]
                pay = pos["dir"] * pos["qty"] * px * rate
                cash -= pay
                pos["funding"] -= pay
                funding_paid += pay
            fi += 1
        # 3) mark to market at the close; force-close at the period's last bar
        if i == last and pos:
            close_pos(cl[i], t + H4)
        eq = cash + (pos["dir"] * pos["qty"] * (cl[i] - pos["entry_px"]) if pos else 0.0)
        curve.append((t + H4, eq))
    return {
        "trades": trades,
        "curve": curve,
        "costs_paid": costs_paid,
        "funding_paid": funding_paid,
    }


def max_dd(curve):
    peak, dd = -1e18, 0.0
    for _, e in curve:
        peak = max(peak, e)
        dd = max(dd, 1 - e / peak)
    return round(100 * dd, 2)


def portfolio(datas, start, end, cost=BASE_COST, with_funding=True, eq0=5000.0, **prm):
    """datas = {asset: {"ts","open","close","fund"}}; equal sleeves of eq0. Returns trades, combined
    curve, stats.
    """
    p = {**FROZEN, **prm}
    curves, trades = [], []
    for a, d in datas.items():
        r = sleeve(d, p["L"], p["V"], p["tv"], p["maxlev"], cost, with_funding, start, end, eq0)
        for t in r["trades"]:
            t["asset"] = a
        trades += r["trades"]
        curves.append(r["curve"])
    n = min(len(c) for c in curves)
    port = [(curves[0][k][0], sum(c[k][1] for c in curves)) for k in range(n)]
    w = sum(t["net"] for t in trades if t["net"] > 0)
    loss = -sum(t["net"] for t in trades if t["net"] <= 0)
    eq_start = eq0 * len(datas)
    return {
        "trades": trades,
        "curve": port,
        "n": len(trades),
        "pf": w / loss if loss > 0 else None,
        "return_pct": 100 * (port[-1][1] / eq_start - 1),
        "max_dd_pct": max_dd(port),
    }
