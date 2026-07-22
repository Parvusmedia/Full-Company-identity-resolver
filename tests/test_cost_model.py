"""Tests for enrichment COGS / client pricing model."""

from __future__ import annotations

import unittest

from my_actor.cost_model import (
    APIFY_STORE_REVENUE_SHARE,
    SCENARIOS,
    UNIT_COSTS_USD,
    break_even_client_price,
    client_price_for_target_margin,
    estimate_cogs,
    pricing_recommendation,
)


class CostModelTests(unittest.TestCase):
    def test_standard_scenario_cogs(self) -> None:
        usage = next(s for s in SCENARIOS if s.label == "estandar")
        cost = estimate_cogs(usage)
        expected = (
            3 * UNIT_COSTS_USD["google_serp_page"]
            + 2 * UNIT_COSTS_USD["harvest_company"]
            + UNIT_COSTS_USD["apify_compute_per_company"]
        )
        self.assertAlmostEqual(cost.total_cogs_usd, expected, places=6)
        self.assertLess(cost.total_cogs_usd, 0.02)

    def test_worst_case_is_most_expensive(self) -> None:
        costs = [estimate_cogs(s).total_cogs_usd for s in SCENARIOS]
        worst = next(s for s in SCENARIOS if s.label == "peor_caso")
        self.assertEqual(max(costs), estimate_cogs(worst).total_cogs_usd)
        self.assertGreaterEqual(estimate_cogs(worst).total_cogs_usd, 0.045)
        self.assertLessEqual(estimate_cogs(worst).total_cogs_usd, 0.055)

    def test_break_even_accounts_for_apify_commission(self) -> None:
        cogs = 0.05
        price = break_even_client_price(cogs)
        self.assertAlmostEqual(price, cogs / APIFY_STORE_REVENUE_SHARE, places=6)
        self.assertAlmostEqual(price * APIFY_STORE_REVENUE_SHARE - cogs, 0.0, places=6)

    def test_target_margin_formula(self) -> None:
        cogs = 0.05
        margin = 0.40
        price = client_price_for_target_margin(cogs, net_margin=margin)
        our_keep = price * APIFY_STORE_REVENUE_SHARE
        net = our_keep - cogs
        self.assertAlmostEqual(net / our_keep, margin, places=6)

    def test_recommendation_rounded_list_covers_worst_case(self) -> None:
        rec = pricing_recommendation(design_scenario="peor_caso", net_margin=0.40)
        list_price = rec["rounded_list_price_usd"]
        our_keep = list_price * APIFY_STORE_REVENUE_SHARE
        self.assertGreaterEqual(our_keep, rec["design_cogs_usd"])
        self.assertGreaterEqual(list_price, 0.10)
        self.assertLessEqual(list_price, 0.12)


if __name__ == "__main__":
    unittest.main()
