"""Strategy rules on synthetic bars: signal direction, confirmation lag, simulator conventions,
status labels.
"""

import math

from jarvis.trading_research import (
    STATUS,
    h1_trend,
    k8_trend,
    l1c_breakout,
)
from jarvis.trading_research import (
    bars as B,
)
from jarvis.trading_research import (
    engine as E,
)
from jarvis.trading_research import (
    intraday as V,
)

H4 = B.H4


def series(prices, iv=H4, t0=1_700_000_000_000 // H4 * H4, spread=0.002):
    rows = []
    for i, p in enumerate(prices):
        o = prices[i - 1] if i else p
        rows.append(
            (t0 + i * iv, o, max(o, p) * (1 + spread), min(o, p) * (1 - spread), p, 100.0, 60.0)
        )
    return rows


def test_every_strategy_has_a_research_status_and_none_is_confirmed():
    for k in ("H1", "K8", "L1c", "LIQUIDITY", "V1", "V2", "V3"):
        assert k in STATUS
        assert "confirmed for real money" not in STATUS[k]
    for k in ("V1", "V2", "V3"):
        assert STATUS[k].startswith("rejected")


def test_pivot_is_known_only_three_bars_later():
    h = [1, 2, 3, 9, 3, 2, 1, 1, 1]
    lows = [x - 0.5 for x in h]
    ph, _ = B.pivots(h, lows)
    assert ph == [3]
    known = B.known_index(ph, len(h))
    assert known[5] == -1 and known[6] == 0


def test_h1_goes_long_in_a_steady_uptrend_and_short_in_a_downtrend():
    up = [100 * math.exp(0.002 * i + 0.01 * math.sin(i)) for i in range(400)]
    rows = series(up)
    d = {
        "ts": [r[0] for r in rows],
        "open": [r[1] for r in rows],
        "close": [r[4] for r in rows],
        "fund": [],
    }
    r = h1_trend.sleeve(
        d, 252, 42, 0.20, 2.0, h1_trend.BASE_COST, False, d["ts"][300], d["ts"][-1] + 1, 5000.0
    )
    assert r["trades"] and r["trades"][0]["side"] == "long"
    down = [100 * math.exp(-0.002 * i + 0.01 * math.sin(i)) for i in range(400)]
    rows = series(down)
    d = {
        "ts": [r[0] for r in rows],
        "open": [r[1] for r in rows],
        "close": [r[4] for r in rows],
        "fund": [],
    }
    r = h1_trend.sleeve(
        d, 252, 42, 0.20, 2.0, h1_trend.BASE_COST, False, d["ts"][300], d["ts"][-1] + 1, 5000.0
    )
    assert r["trades"][0]["side"] == "short"


def test_engine_stop_first_when_stop_and_target_share_a_bar():
    rows = series([100.0] * 30)
    rows.append((rows[-1][0] + H4, 100.0, 110.0, 90.0, 100.0, 100.0, 50.0))  # wide bar touches both
    s = B.Bars("X", H4, rows)
    st = E.Setup(29, 1, 95.0, target=("pole", 5.0), exit_rule="fixed")
    trades, _ = E.simulate(s, [st], [], 0.0012, rows[0][0], rows[-1][0] + 1)
    assert trades[0]["why"] == "stop"


def test_k8_and_l1c_produce_setups_only_with_their_filters():
    up = [100 * (1.003**i) for i in range(400)]
    rows = series(up)
    s = B.Bars("X", H4, rows)
    daily = B.Daily([r[0] for r in rows[::6]], [r[4] for r in rows[::6]])
    assert all(x.d == 1 for x in k8_trend.setups(s, daily))
    s1 = B.Bars("X", B.H1, series(up, iv=B.H1))
    oi_flat = {t: 1000.0 for t in s1.ts + [s1.ts[-1] + B.H1]}
    f = l1c_breakout.features(s1, oi_flat)
    assert l1c_breakout.setups(s1, f) == []  # OI never rises -> no L1c setup


def test_intraday_box_false_break_short_and_mirrored_long():
    iv = V.H1
    d0 = 1_700_006_400_000 // V.D1 * V.D1
    rows = []
    for i in range(24):  # previous day: range 100..110
        p = 100 + 10 * (i % 2)
        rows.append((d0 + i * iv, p, 110.0, 100.0, p, 10.0, 5.0))
    day = [(105, 109, 104, 108), (108, 112, 107, 108.5), (108.5, 109, 103, 104)] + [
        (104, 105, 103, 104)
    ] * 21
    for i, (o, h, lo, c) in enumerate(day):
        rows.append((d0 + V.D1 + i * iv, o, h, lo, c, 10.0, 5.0))
    s = V.Series("X", "1h", rows, ([], []), ([], []), mirror=False)
    cands = V.build(s, "V2B", "T1")
    assert (
        cands and cands[0]["known"] == 25
    )  # the bar that wicked above PDH 110 and closed back inside
    trades, _ = V.simulate(s, cands, V.TMAX["1h"])
    assert (
        trades and trades[0]["side"] == "short" and trades[0]["why"] == "target"
    )  # MID 105 reached
    m = V.Series("X", "1h", rows, ([], []), ([], []), mirror=True)
    assert m.box[V.D1 // V.D1 + d0 // V.D1] == (-100.0, -110.0)  # mirrored PDH/PDL = -PDL/-PDH
