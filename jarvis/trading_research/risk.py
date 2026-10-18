"""Risk model for research simulations and read-only signal observation (pure functions, no account
access).

Rules (research/observation only; never applied to the running paper test or any
live setting):
- margin mode ISOLATED only (the venue's exact label "ISOLATION"); anything else, including unknown,
is blocked;
- planned risk per trade 0.5 % of simulated equity at the stop, INCLUDING entry and exit costs;
- position size never depends on the leverage: leverage only sets the margin and the liquidation
distance;
- open risk over all positions and strategies: regular ceiling 3 % (warning from 2 %), absolute
ceiling 4 %;
  positions in the same direction are summed linearly (crypto majors move together; they are never
  treated as
  independent), positions in opposite directions are never netted against each other;
- the absolute ceiling is measured on CURRENT equity (planned risk grows as a fraction when equity
falls);
- stressed risk (stops overrun by the gap reserve) is reported as a warning above the absolute
ceiling;
- H1 research/observation model: leverage at most 3x.

A stop is not a loss guarantee: `stressed_loss` and the gap reserve model fills beyond the stop, and
`liquidation_distance` uses the venue's maintenance-margin tier for the position size.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

ISOLATED = "ISOLATION"


@dataclass(frozen=True)
class RiskLimits:
    risk_per_trade: float = 0.005
    open_risk_warn: float = 0.02
    open_risk_regular: float = 0.03
    open_risk_absolute: float = 0.04
    # assumed stop overrun as a fraction of price (largest own-venue wick seen in research)
    gap_reserve: float = 0.024
    liq_buffer: float = 3.0  # liquidation must be at least this many stop distances away
    max_leverage: float = 3.0
    research_leverage_levels: tuple[float, ...] = (
        5.0,
        7.0,
        10.0,
        20.0,
    )  # research targets only, never for orders


H1_OBSERVATION = RiskLimits(max_leverage=3.0)


@dataclass(frozen=True)
class MarginTier:
    """One maintenance-margin tier of the venue: applies while the position value is in
    [start_value, end_value).
    """

    start_value: float
    end_value: float
    max_leverage: float
    mmr: float


def tier_for(tiers: list[MarginTier], position_value: float) -> MarginTier:
    for t in tiers:
        if t.start_value <= position_value < t.end_value:
            return t
    raise ValueError("position value is above the highest maintenance-margin tier")


@dataclass(frozen=True)
class Position:
    """An open (simulated) position as the risk model sees it."""

    strategy: str
    symbol: str
    direction: int  # +1 long, -1 short
    entry: float
    stop: float
    qty: float
    equity_at_entry: float

    @property
    def stop_frac(self) -> float:
        return abs(self.entry - self.stop) / self.entry

    def planned_risk(self, equity: float, cost_per_fill: float) -> float:
        loss = self.qty * (abs(self.entry - self.stop) + cost_per_fill * (self.entry + self.stop))
        return loss / equity


def position_qty(
    equity: float, entry: float, stop: float, risk_frac: float, cost_per_fill: float
) -> float:
    """Quantity so that the loss at the stop plus entry and exit costs equals risk_frac * equity. No
    leverage input.
    """
    dist = abs(entry - stop)
    if dist <= 0 or entry <= 0 or equity <= 0:
        raise ValueError(
            "entry, stop and equity must be positive and the stop must differ from the entry"
        )
    return equity * risk_frac / (dist + cost_per_fill * (entry + stop))


def liquidation_distance(leverage: float, mmr: float) -> float:
    """Adverse move (fraction of entry) that liquidates an isolated linear position funded with
    notional / leverage.
    """
    if leverage <= 0:
        raise ValueError("leverage must be positive")
    return max(0.0, 1.0 / leverage - mmr)


def margin_needed(qty: float, price: float, leverage: float) -> float:
    return qty * price / leverage


def stressed_loss(risk_frac: float, stop_frac: float, gap_frac: float) -> float:
    """Equity loss when the fill lands gap_frac beyond the stop (fractions of price)."""
    if stop_frac <= 0:
        raise ValueError("stop distance must be positive")
    return risk_frac * (stop_frac + gap_frac) / stop_frac


@dataclass(frozen=True)
class PortfolioRisk:
    planned_total: float
    long_total: float
    short_total: float
    same_direction_max: float
    stressed_total: float
    correlation_weighted: float | None
    by_strategy: dict[str, float] = field(default_factory=dict)


def portfolio_risk(
    positions: list[Position],
    equity: float,
    cost_per_fill: float,
    gap: float,
    corr: dict[tuple[str, str], float] | None = None,
) -> PortfolioRisk:
    """Aggregate open risk. The gating figures are LINEAR sums (no diversification credit, no
    netting of longs
    against shorts). `correlation_weighted` = sqrt(r' C r) with signed risks is reported for
    information only.
    """
    risks = [(p, p.planned_risk(equity, cost_per_fill)) for p in positions]
    long_t = sum(r for p, r in risks if p.direction > 0)
    short_t = sum(r for p, r in risks if p.direction < 0)
    stressed = sum(stressed_loss(r, p.stop_frac, gap) for p, r in risks)
    by: dict[str, float] = {}
    for p, r in risks:
        by[p.strategy] = by.get(p.strategy, 0.0) + r
    cw = None
    if corr is not None and risks:
        acc = 0.0
        for p, r in risks:
            for q, s in risks:
                rho = (
                    1.0
                    if p.symbol == q.symbol
                    else corr.get((p.symbol, q.symbol), corr.get((q.symbol, p.symbol)))
                )
                if rho is None:
                    raise ValueError(f"missing correlation for {p.symbol}/{q.symbol}")
                acc += p.direction * r * q.direction * s * rho
        cw = math.sqrt(max(acc, 0.0))
    return PortfolioRisk(long_t + short_t, long_t, short_t, max(long_t, short_t), stressed, cw, by)


@dataclass(frozen=True)
class EntryDecision:
    allowed: bool
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    qty: float
    margin: float
    liquidation_distance: float
    planned_risk: float


def absolute_breach(
    limits: RiskLimits, positions: list[Position], equity: float, cost_per_fill: float
) -> bool:
    """True when already-open positions exceed the absolute ceiling on current equity (an alert;
    nothing is closed).
    """
    return (
        portfolio_risk(positions, equity, cost_per_fill, limits.gap_reserve).planned_total
        > limits.open_risk_absolute + 1e-12
    )


def check_entry(
    limits: RiskLimits,
    *,
    margin_mode: str | None,
    leverage: float,
    equity: float,
    entry: float,
    stop: float,
    direction: int,
    cost_per_fill: float,
    open_positions: list[Position],
    tiers: list[MarginTier],
    pause_reason: str | None = None,
) -> EntryDecision:
    """Full pre-entry check for a simulated entry. Never places anything; returns a decision for the
    journal.
    """
    reasons: list[str] = []
    warnings: list[str] = []
    if margin_mode != ISOLATED:
        reasons.append("margin mode is not isolated")
    if leverage > limits.max_leverage:
        reasons.append(f"leverage {leverage:g}x above the allowed {limits.max_leverage:g}x")
    qty = position_qty(equity, entry, stop, limits.risk_per_trade, cost_per_fill)
    value = qty * entry
    try:
        tier = tier_for(tiers, value)
        if leverage > tier.max_leverage:
            reasons.append("leverage above the venue tier maximum")
        liq = liquidation_distance(leverage, tier.mmr)
    except ValueError as e:  # not silent: a tier overflow becomes a blocking reason below
        reasons.append(str(e))
        liq = 0.0
    stop_frac = abs(entry - stop) / entry
    if liq < limits.liq_buffer * stop_frac:
        reasons.append(
            f"liquidation ({liq:.2%}) closer than {limits.liq_buffer:g}x the stop ({stop_frac:.2%})"
        )
    margin = margin_needed(qty, entry, leverage)
    used_margin = sum(p.qty * p.entry for p in open_positions) / leverage
    if margin + used_margin > equity:
        reasons.append("total margin would exceed equity")
    new = Position("new", "new", direction, entry, stop, qty, equity)
    after = portfolio_risk(open_positions + [new], equity, cost_per_fill, limits.gap_reserve)
    if after.planned_total > limits.open_risk_regular + 1e-12:
        reasons.append(
            f"open risk {after.planned_total:.2%} above the regular ceiling "
            f"{limits.open_risk_regular:.0%}"
        )
    elif after.planned_total > limits.open_risk_warn + 1e-12:
        warnings.append(f"open risk {after.planned_total:.2%} above {limits.open_risk_warn:.0%}")
    if after.stressed_total > limits.open_risk_absolute + 1e-12:
        warnings.append(
            f"stressed risk {after.stressed_total:.2%} above {limits.open_risk_absolute:.0%} "
            f"if stops gap by {limits.gap_reserve:.1%}"
        )
    if pause_reason:
        reasons.append(pause_reason)
    return EntryDecision(
        not reasons,
        tuple(reasons),
        tuple(warnings),
        qty,
        margin,
        liq,
        new.planned_risk(equity, cost_per_fill),
    )
