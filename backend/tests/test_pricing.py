"""Unit tests for the static pricing table and cost_usd()."""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from llm.pricing import MODEL_PRICING, cost_usd, LAST_UPDATED, SOURCES


class TestModelPricingTable(unittest.TestCase):
    """Every entry in MODEL_PRICING must have the required keys."""

    def test_all_entries_have_required_keys(self):
        required = {"provider", "label", "input", "output"}
        for model_id, info in MODEL_PRICING.items():
            with self.subTest(model_id=model_id):
                self.assertTrue(
                    required.issubset(info.keys()),
                    f"{model_id} missing keys: {required - info.keys()}",
                )

    def test_all_prices_are_positive(self):
        for model_id, info in MODEL_PRICING.items():
            with self.subTest(model_id=model_id):
                self.assertGreater(info["input"], 0)
                self.assertGreater(info["output"], 0)

    def test_last_updated_is_set(self):
        self.assertRegex(LAST_UPDATED, r"^\d{4}-\d{2}-\d{2}$")

    def test_sources_has_three_providers(self):
        self.assertIn("openai", SOURCES)
        self.assertIn("anthropic", SOURCES)
        self.assertIn("gemini", SOURCES)


class TestCostUsd(unittest.TestCase):

    def test_happy_path(self):
        # claude-haiku-4-5: input=1.00, output=5.00 per MTok
        cost = cost_usd("claude-haiku-4-5-20251001", 1000, 500)
        expected = (1000 * 1.00 + 500 * 5.00) / 1_000_000
        self.assertAlmostEqual(cost, expected, places=10)

    def test_zero_tokens(self):
        self.assertEqual(cost_usd("claude-haiku-4-5-20251001", 0, 0), 0.0)

    def test_unknown_model_returns_zero(self):
        self.assertEqual(cost_usd("nonexistent-model-xyz", 9999, 9999), 0.0)

    def test_sub_cent_precision(self):
        # gemini-2.5-flash: input=0.30, output=2.50
        cost = cost_usd("gemini-2.5-flash", 500, 100)
        expected = (500 * 0.30 + 100 * 2.50) / 1_000_000
        self.assertAlmostEqual(cost, expected, places=10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
