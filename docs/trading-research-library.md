# Trading research library

`jarvis/trading_research/` holds research rules, simulators and risk checks for systematic crypto
strategies. It exists so that research results are reproducible and reviewable in code.

**It is not a trading component.** Nothing in the package places, changes or cancels orders, holds
credentials, opens network connections, or is imported by any job, bot or app surface. Static tests
in `tests/unit/trading_research/test_isolation.py` enforce this.

## Modules

| Module | Content |
|---|---|
| `bars.py` | bar series, ATR/EMA, swing pivots with a 3-bar confirmation lag, daily trend context, read-only sqlite loaders |
| `engine.py` | stop/target/trailing simulator: next-open fills, stop checked before target inside a bar, funding per settlement |
| `h1_trend.py` | H1: 4h time-series momentum (lookback 252 bars, volatility target 20 %, at most 2x notional) |
| `k8_trend.py` | K8: 4h 20-bar channel breakout with a daily trend filter |
| `l1c_breakout.py` | L1c: 1h breakout confirmed by taker flow, volume and rising open interest |
| `liquidity.py` | provenance-tagged liquidity context (observed / derived / estimated / modelled / unavailable) and an execution check |
| `intraday.py` | intraday rules V1 (fair value gap + liquidity sweep), V2 (previous-day range), V3 (combined) |
| `risk.py` | position sizing, isolated-margin check, liquidation distance per maintenance-margin tier, open-risk aggregation |
| `loss_streak.py` | loss-streak pause rule with restart-safe state |

## Research status

`jarvis.trading_research.STATUS` records the status of every strategy. None of them is confirmed for
real money.

- **H1:** research candidate for BTC/ETH only. It does not generalise to other coins in research.
- **K8:** not independent of H1.
- **L1c:** an unconfirmed hypothesis.
- **V1, V2 and V3:** rejected. They were negative after realistic costs in every tested variant.

## Risk model

- **Isolated margin only.** The exact isolated label is required; anything else, including unknown, is blocked.
- **Planned risk per trade:** 0.5 % of simulated equity at the stop, including entry and exit costs.
  The position size never depends on the leverage; leverage only sets margin and liquidation distance.
- **Open risk:** summed linearly over all positions and strategies. Positions in the same direction are
  never treated as independent, and longs are never netted against shorts.
  - Above 2 % open risk a warning is raised.
  - New entries are refused above 3 %.
  - The absolute ceiling is 4 %, measured on current equity.
- **Gaps:** a stop is not a loss guarantee. A gap reserve models fills beyond the stop and is reported
  as stressed risk.
- **Liquidation buffer:** liquidation must lie at least three stop distances away, using the venue's
  maintenance-margin tier for the position value.
- **H1 observation model:** at most 3x leverage. 5x, 7x, 10x and 20x are research targets only.
- **Loss streak:** three consecutive closed trades with a negative result after fees and funding start
  a 24-hour pause.
  - New entries are blocked during the pause. Existing positions are never touched.
  - After the pause, a risk re-check must be recorded before entries are allowed again.
  - A notification is queued for a later, separately approved delivery channel.

## Tests

```bash
pytest tests/unit/trading_research
```

`test_parity_optional.py` reproduces the frozen study results exactly. It needs the private study data
copies and runs only when `JARVIS_TRADING_RESEARCH_DATA` points at them; otherwise it is skipped.
