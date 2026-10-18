"""Liquidity prototype: provenance tags, deltas, zones, execution check."""

import unittest

from jarvis.trading_research import liquidity as M


def bars_from(rows):
    return [M.Bar(i * 3_600_000, *r) for i, r in enumerate(rows)]


class T(unittest.TestCase):
    def test_delta(self):
        self.assertAlmostEqual(M.taker_delta(M.Bar(0, 1, 1, 1, 1, 10, 7)), 0.4)
        self.assertIsNone(M.taker_delta(M.Bar(0, 1, 1, 1, 1, 0, 0)))
        self.assertIsNone(M.taker_delta(M.Bar(0, 1, 1, 1, 1, 10, None)))

    def test_sweep_and_breakout(self):
        rows = [(100, 101, 99, 100, 1, 0.5)] * 24
        up_sweep = bars_from(rows + [(100, 103, 99.5, 100.5, 1, 0.5)])
        self.assertEqual(M.sweep(up_sweep, 24), -1)
        self.assertEqual(M.breakout(up_sweep, 24), 0)
        brk = bars_from(rows + [(100, 103, 99.5, 102, 1, 0.5)])
        self.assertEqual(M.breakout(brk, 24), 1)
        self.assertEqual(M.sweep(brk, 24), 0)
        both = bars_from(rows + [(100, 103, 97, 100, 1, 0.5)])
        self.assertEqual(M.sweep(both, 24), 0)

    def test_stop_clusters_are_estimated_and_unbroken(self):
        rows = [(100, 100 + (5 if i == 5 else 0), 99, 100, 1, 0.5) for i in range(20)]
        z = M.stop_clusters(bars_from(rows), atr_now=1.0)
        above = [x for x in z if x.kind == "stop_cluster_above"]
        self.assertTrue(above and all(x.provenance == M.ESTIMATED for x in z))
        self.assertEqual(above[0].lo, 105)
        rows[10] = (100, 106, 99, 100, 1, 0.5)  # later bar breaks the swing at 105
        z2 = M.stop_clusters(bars_from(rows), atr_now=1.0)
        self.assertNotIn(105, [x.lo for x in z2 if x.kind == "stop_cluster_above"])

    def test_liquidation_clusters_are_modelled(self):
        z = M.liquidation_clusters([(100.0, 1.0, 2.0)], {10: 1.0})
        self.assertEqual({x.kind for x in z}, {"liq_long", "liq_short"})
        self.assertTrue(all(x.provenance == M.MODELLED for x in z))
        self.assertEqual(M.liquidation_clusters([(100.0, 2.0, 1.0)], {10: 1.0}), [])

    def test_execution_check(self):
        ok = M.execution_check(100.0, 100.01, 0.5, 0.2, stop_dist_frac=0.02)
        self.assertTrue(ok["ok"])
        far = M.execution_check(100.0, 100.5, 0.5, 0.2, stop_dist_frac=0.02)
        self.assertFalse(far["ok"])
        thin = M.execution_check(100.0, 100.0, 0.5, None, stop_dist_frac=0.02)
        self.assertFalse(thin["ok"])
        costly = M.execution_check(100.0, 100.0, 0.5, 0.2, stop_dist_frac=0.004)
        self.assertFalse(costly["ok"])

    def test_context_lists_missing_inputs(self):
        rows = [
            (100 + (i % 7), 102 + (i % 7), 99 + (i % 7), 101 + (i % 7), 10 + i % 3, 5)
            for i in range(300)
        ]
        ctx = M.context("X", bars_from(rows), round_step=10)
        self.assertIn("open interest", ctx.missing)
        self.assertIn("liquidation history (no free source)", ctx.missing)
        self.assertEqual(ctx.flow["oi_change"][1], M.UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
