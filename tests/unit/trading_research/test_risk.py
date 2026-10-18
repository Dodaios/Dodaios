"""Risk model: sizing, isolated-only, leverage ceilings, venue tiers, correlated open risk."""

import pytest

from jarvis.trading_research import risk as R

TIERS = [R.MarginTier(0, 100_000, 200, 0.003), R.MarginTier(100_000, 400_000, 150, 0.004)]
COST = 0.0012


def entry(**kw):
    args = dict(
        margin_mode=R.ISOLATED,
        leverage=3.0,
        equity=10_000.0,
        entry=100.0,
        stop=97.0,
        direction=1,
        cost_per_fill=COST,
        open_positions=[],
        tiers=TIERS,
    )
    args.update(kw)
    return R.check_entry(R.H1_OBSERVATION, **args)


def pos(direction, stop=97.0, symbol="BTCUSDT", equity=10_000.0):
    qty = R.position_qty(equity, 100.0, stop, 0.005, COST)
    return R.Position("s", symbol, direction, 100.0, stop, qty, equity)


def test_planned_loss_at_stop_includes_costs():
    q = R.position_qty(10_000, 100.0, 98.0, 0.005, COST)
    assert q * 2.0 + q * COST * (100.0 + 98.0) == pytest.approx(50.0)


def test_size_does_not_depend_on_leverage():
    low = R.check_entry(
        R.RiskLimits(max_leverage=20),
        margin_mode=R.ISOLATED,
        leverage=3,
        equity=10_000,
        entry=100,
        stop=99,
        direction=1,
        cost_per_fill=COST,
        open_positions=[],
        tiers=TIERS,
    )
    high = R.check_entry(
        R.RiskLimits(max_leverage=20),
        margin_mode=R.ISOLATED,
        leverage=20,
        equity=10_000,
        entry=100,
        stop=99,
        direction=1,
        cost_per_fill=COST,
        open_positions=[],
        tiers=TIERS,
    )
    assert low.qty == high.qty
    assert low.planned_risk == pytest.approx(0.005)
    assert high.margin < low.margin


@pytest.mark.parametrize("mode", ["CROSS", "cross", "isolation", None, ""])
def test_only_exact_isolated_label_passes(mode):
    d = entry(margin_mode=mode)
    assert not d.allowed
    assert "margin mode is not isolated" in d.reasons


def test_h1_observation_caps_leverage_at_3x():
    assert entry(leverage=3.0).allowed
    d = entry(leverage=5.0)
    assert not d.allowed and any("above the allowed 3x" in r for r in d.reasons)


def test_liquidation_uses_tier_mmr_and_buffer():
    assert R.liquidation_distance(3, 0.003) == pytest.approx(1 / 3 - 0.003)
    # 12 % stop at 3x: liquidation 33 % < 3 x 12 % -> blocked
    d = entry(stop=88.0)
    assert any("liquidation" in r for r in d.reasons)


def test_tier_lookup_and_overflow():
    assert R.tier_for(TIERS, 150_000).mmr == 0.004
    with pytest.raises(ValueError):
        R.tier_for(TIERS, 500_000)


def test_same_direction_positions_are_summed_not_diversified():
    five_longs = [
        pos(1, symbol=s) for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
    ]
    d = entry(
        open_positions=five_longs
    )  # 6 x 0.5 % = 3.0 % -> at the regular ceiling, allowed with a warning
    assert d.allowed and d.warnings
    d = entry(open_positions=five_longs + [pos(1, symbol="HBARUSDT")])  # 3.5 %
    assert not d.allowed and any("regular ceiling" in r for r in d.reasons)


def test_opposite_directions_are_not_netted():
    mixed = [
        pos(1),
        pos(-1, stop=103.0),
        pos(1, symbol="ETHUSDT"),
        pos(-1, stop=103.0, symbol="ETHUSDT"),
        pos(1, symbol="SOLUSDT"),
    ]
    pr = R.portfolio_risk(mixed, 10_000, COST, 0.0)
    assert pr.planned_total == pytest.approx(0.025)
    assert pr.long_total == pytest.approx(0.015) and pr.short_total == pytest.approx(0.010)
    assert not entry(
        open_positions=mixed + [pos(-1, stop=103.0, symbol="XRPUSDT")], direction=-1, stop=103.0
    ).allowed


def test_correlation_weighted_figure_is_informational_and_needs_all_pairs():
    ps = [pos(1, symbol="BTCUSDT"), pos(1, symbol="ETHUSDT")]
    pr = R.portfolio_risk(ps, 10_000, COST, 0.0, corr={("BTCUSDT", "ETHUSDT"): 0.82})
    assert pr.correlation_weighted == pytest.approx(0.005 * (2 + 2 * 0.82) ** 0.5)
    assert pr.planned_total == pytest.approx(0.01)  # gate figure stays linear
    with pytest.raises(ValueError):
        R.portfolio_risk(ps, 10_000, COST, 0.0, corr={})


def test_absolute_ceiling_on_current_equity():
    ps = [pos(1, symbol=s) for s in ("A", "B", "C", "D", "E", "F")]  # 3 % at 10 000
    assert not R.absolute_breach(R.H1_OBSERVATION, ps, 10_000, COST)
    assert R.absolute_breach(
        R.H1_OBSERVATION, ps, 7_000, COST
    )  # same positions after a drawdown: 4.3 %


def test_stressed_gap_is_reported_as_warning():
    tight = [pos(1, stop=99.5, symbol=s) for s in ("A", "B", "C")]
    d = entry(open_positions=tight, stop=99.5)
    assert d.allowed and any("stressed risk" in w for w in d.warnings)
    assert R.stressed_loss(0.005, 0.03, 0.024) == pytest.approx(0.009)


def test_margin_above_equity_is_blocked():
    lim = R.RiskLimits(max_leverage=20, open_risk_regular=1.0, open_risk_warn=1.0)
    many = [
        R.Position(
            "s", f"X{i}", 1, 100.0, 99.8, R.position_qty(10_000, 100, 99.8, 0.005, COST), 10_000
        )
        for i in range(8)
    ]
    d = R.check_entry(
        lim,
        margin_mode=R.ISOLATED,
        leverage=2,
        equity=10_000,
        entry=100,
        stop=99.8,
        direction=1,
        cost_per_fill=COST,
        open_positions=many,
        tiers=[R.MarginTier(0, 1e12, 200, 0.003)],
    )
    assert any("margin would exceed equity" in r for r in d.reasons)


def test_pause_reason_blocks():
    d = entry(pause_reason="loss-streak pause active")
    assert not d.allowed and "loss-streak pause active" in d.reasons
