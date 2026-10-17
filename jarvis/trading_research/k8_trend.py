"""K8: 4h Donchian-20 breakout with the daily trend filter (S1 variant trend_4h_htf), as signal
setups.

Entry: close above the prior 20-bar high (below the 20-bar low) while the daily filter agrees.
Stop 2 ATR, exit on a close beyond the 10-bar channel or when the daily filter turns (engine exit
"donchian_htf").
STATUS: held its test, but takes the same direction as H1 93-98 % of the time (not independent).
Research only: not connected to any job, bot or order path.
"""

from .engine import Setup


def setups(s, daily):
    out = []
    for i in range(60, s.n - 1):
        if s.atr[i] is None:
            continue
        d = 1 if s.c[i] > max(s.h[i - 20 : i]) else (-1 if s.c[i] < min(s.l[i - 20 : i]) else 0)
        if not d or daily.htf(s.ts[i] + s.iv) != d:
            continue
        out.append(Setup(i, d, s.c[i] - d * 2 * s.atr[i], exit_rule="donchian_htf"))
    return out
