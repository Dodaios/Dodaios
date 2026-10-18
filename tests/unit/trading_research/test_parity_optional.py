"""Exact parity with the frozen research studies. Needs the private study data copies, so it runs
only when
JARVIS_TRADING_RESEARCH_DATA points at the research data folder; CI and fresh clones skip it."""

import os
from datetime import datetime

import pytest

from jarvis.trading_research import bars as B
from jarvis.trading_research import engine as E
from jarvis.trading_research import h1_trend, k8_trend, l1c_breakout

ROOT = os.environ.get("JARVIS_TRADING_RESEARCH_DATA")
pytestmark = pytest.mark.skipif(
    not ROOT, reason="private study data not configured (JARVIS_TRADING_RESEARCH_DATA)"
)


def ms(s):
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)


TEST = (ms("2025-01-01T00:00Z"), ms("2026-10-09T00:00Z"))


def test_h1_frozen_test_result():
    db = B.ro(os.path.join(ROOT, "studies", "h1", "h1_data.sqlite"))
    datas = {}
    for a in ("BTCUSDT", "ETHUSDT"):
        src = f"binance:perp:{a}"
        rows = db.execute(
            "select ts, open, close from bars where source=? order by ts", (src,)
        ).fetchall()
        fund = db.execute(
            "select ts, rate from funding where source=? order by ts", (src,)
        ).fetchall()
        datas[a] = {
            "ts": [r[0] for r in rows],
            "open": [r[1] for r in rows],
            "close": [r[2] for r in rows],
            "fund": [(round(t / 60_000) * 60_000, r) for t, r in fund],
        }
    r = h1_trend.portfolio(datas, *TEST)
    assert r["n"] == 177
    assert round(r["return_pct"], 2) == 48.26
    assert round(r["pf"], 3) == 1.783


def test_k8_frozen_test_result():
    db = B.ro(os.path.join(ROOT, "teil_b", "studien", "s1", "s1_data.sqlite"))
    trs = []
    for a in ("BTCUSDT", "ETHUSDT"):
        s4, s1h, daily = B.load_bars(db, a, B.H4), B.load_bars(db, a, B.H1), B.load_daily(db, a)
        t, _ = E.simulate(
            s4,
            k8_trend.setups(s4, daily),
            B.load_funding(db, a),
            0.0012,
            *TEST,
            daily=daily,
            p1h=s1h,
        )
        trs += t
    st = E.summary(trs)
    assert (st["trades"], st["mean_R"]) == (125, 0.2588)


def test_l1c_frozen_test_result():
    db = B.ro(os.path.join(ROOT, "teil_b", "studien", "s3", "s3_data.sqlite"))
    trs = []
    for a in ("BTCUSDT", "ETHUSDT"):
        s = B.load_bars(db, a, B.H1)
        oi = dict(db.execute("select ts, oi from oi where symbol=?", (a,)).fetchall())
        daily = B.load_daily(db, a)
        t, _ = E.simulate(
            s,
            l1c_breakout.setups(s, l1c_breakout.features(s, oi)),
            B.load_funding(db, a),
            0.0012,
            *TEST,
            daily=daily,
            p1h=s,
        )
        trs += t
    st = E.summary(trs)
    assert (st["trades"], st["mean_R"]) == (318, 0.2018)
