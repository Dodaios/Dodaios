"""Trading research library: isolated strategy rules, simulators and risk checks.

Research and simulation only. Nothing in this package places, changes or cancels orders, holds
credentials,
opens network connections or is imported by any job, bot or app surface. Data loaders open sqlite
files read-only.

Every strategy carries its research status; none of them is confirmed for real money.
"""

STATUS = {
    "H1": (
        "research candidate: 4h time-series momentum, BTC/ETH only; held walk-forward and a "
        "one-time test; not statistically established after multiple testing; "
        "does not generalise to other coins"
    ),
    "K8": (
        "held its test but takes the same direction as H1 93-98 % of the time; "
        "not an independent strategy"
    ),
    "L1c": "hypothesis: held one test window, not confirmed on fresh data",
    "LIQUIDITY": (
        "prototype: provenance-tagged context and execution check; no proven standalone edge"
    ),
    "V1": "rejected: fair value gap + liquidity sweep, negative after costs in every variant",
    "V2": (
        "rejected: previous-day box (breakout-retest, false break, mid filter), "
        "negative after costs"
    ),
    "V3": (
        "rejected: combined box sweep + structure + gap; better than its parts "
        "but negative after costs"
    ),
}

__all__ = ["STATUS"]
