"""Bar series and indicators shared by the research library (pure functions, no I/O except the
loaders).

Behaviour matches the frozen research study engine (Series, Daily, atr, ema, pivots, known_index,
rolling_prev_mean). Loaders open sqlite files read-only.
"""

import sqlite3
from bisect import bisect_right

H1, H4, D1 = 3_600_000, 14_400_000, 86_400_000


def atr(h, lo, c, n=14):
    """Simple rolling mean of true range over n bars (value at i uses bars i-n+1..i)."""
    size = len(c)
    tr = [h[0] - lo[0]] + [
        max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(1, size)
    ]
    out, acc = [None] * size, 0.0
    for i in range(size):
        acc += tr[i]
        if i >= n:
            acc -= tr[i - n]
            out[i] = acc / n
    return out


def wilder_atr(h, lo, c, n=14):
    """Wilder ATR (used by the intraday research rules)."""
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


def ema(x, n):
    k, out, e = 2 / (n + 1), [None] * len(x), None
    for i, v in enumerate(x):
        e = v if e is None else e + k * (v - e)
        out[i] = e if i >= n - 1 else None
    return out


def rolling_prev_mean(x, n):
    out, acc = [None] * len(x), 0.0
    for i in range(len(x)):
        if i >= n:
            out[i] = acc / n  # mean of x[i-n .. i-1]
        acc += x[i]
        if i >= n:
            acc -= x[i - n]
    return out


def pivots(h, lo, k=3):
    ph, pl = [], []
    for j in range(k, len(h) - k):
        if h[j] > max(h[j - k : j]) and h[j] >= max(h[j + 1 : j + k + 1]):
            ph.append(j)
        if lo[j] < min(lo[j - k : j]) and lo[j] <= min(lo[j + 1 : j + k + 1]):
            pl.append(j)
    return ph, pl


def known_index(piv, n, k=3):
    """known[i] = position in piv of the last pivot confirmed at or before bar i (pivot j usable
    from bar j+k), or -1.
    """
    out, m = [-1] * n, -1
    for i in range(n):
        while m + 1 < len(piv) and piv[m + 1] + k <= i:
            m += 1
        out[i] = m
    return out


class Bars:
    """OHLCV bars with S1 indicators. rows = [(ts, open, high, low, close, volume, taker_buy), ...]
    sorted by ts.
    """

    def __init__(self, asset, iv, rows, wilder=False):
        self.asset, self.iv = asset, iv
        self.ts, self.o, self.h, self.l, self.c, self.v, self.tb = (
            list(x) for x in zip(*rows, strict=True)
        )
        self.n = len(self.ts)
        self.idx = {t: i for i, t in enumerate(self.ts)}
        self.atr = (wilder_atr if wilder else atr)(self.h, self.l, self.c)
        self.ph, self.pl = pivots(self.h, self.l)
        self.ph_known = known_index(self.ph, self.n)
        self.pl_known = known_index(self.pl, self.n)


class Daily:
    """Daily trend context: htf() = K8 daily filter, phase() = 200-day regime (S1 definitions)."""

    def __init__(self, ts, close):
        self.ts, self.c = list(ts), list(close)
        n = len(self.c)
        self.ema50 = ema(self.c, 50)
        self.sma200, acc = [None] * n, 0.0
        for i in range(n):
            acc += self.c[i]
            if i >= 200:
                acc -= self.c[i - 200]
            if i >= 199:
                self.sma200[i] = acc / 200

    def last_closed(self, t_close):
        return bisect_right(self.ts, t_close - D1) - 1

    def htf(self, t_close):
        d = self.last_closed(t_close)
        if d < 55 or self.ema50[d] is None or self.ema50[d - 5] is None:
            return 0
        if self.c[d] > self.ema50[d] and self.ema50[d] > self.ema50[d - 5]:
            return 1
        if self.c[d] < self.ema50[d] and self.ema50[d] < self.ema50[d - 5]:
            return -1
        return 0

    def phase(self, t_close):
        d = self.last_closed(t_close)
        if d < 220 or self.sma200[d] is None or self.sma200[d - 20] is None:
            return "unknown"
        if self.c[d] > self.sma200[d] and self.sma200[d] > self.sma200[d - 20]:
            return "up"
        if self.c[d] < self.sma200[d] and self.sma200[d] < self.sma200[d - 20]:
            return "down"
        return "mixed"


def ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def load_bars(db, asset, iv, wilder=False, venue="perp"):
    rows = db.execute(
        "select ts, open, high, low, close, volume, taker_buy from bars"
        " where source=? and interval_ms=? order by ts",
        (f"binance:{venue}:{asset}", iv),
    ).fetchall()
    return Bars(asset, iv, rows, wilder)


def load_daily(db, asset):
    rows = db.execute(
        "select ts, close from bars where source=? and interval_ms=? order by ts",
        (f"binance:perp:{asset}", D1),
    ).fetchall()
    return Daily([r[0] for r in rows], [r[1] for r in rows])


def load_funding(db, asset):
    return [
        (round(t / 60_000) * 60_000, r)
        for t, r in db.execute(
            "select ts, rate from funding where source=? order by ts", (f"binance:perp:{asset}",)
        )
    ]
