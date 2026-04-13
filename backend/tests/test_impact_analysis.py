"""Unit tests for ImpactAnalysisAgent."""
import json
import sys
import os
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.impact_analysis import (
    ImpactAnalysisAgent,
    CONFIDENCE_REVIEW_THRESHOLD,
    SIGNIFICANCE_LEVELS,
)
from llm.base import LLMResult


def make_llm(response: str) -> MagicMock:
    llm = MagicMock()
    llm.provider_name = "mock"
    llm.complete.return_value = LLMResult(
        text=response,
        input_tokens=200,
        output_tokens=150,
        model="mock-model",
    )
    return llm


SAMPLE_STATE = {
    "parsed_project": {
        "project_type": "solar farm",
        "scale": "50 MW",
        "location": "Pittsburgh, PA",
        "actions": ["site clearing", "panel installation"],
    },
    "environmental_data": {
        "usfws_species": {
            "count": 2,
            "species": [
                {"name": "Indiana Bat", "status": "Endangered"},
                {"name": "Northern Long-eared Bat", "status": "Threatened"},
            ],
        },
        "nwi_wetlands": {"count": 1, "wetlands": [{"type": "Freshwater Pond"}]},
        "fema_flood_zones": {"in_sfha": False, "flood_zones": []},
        "usda_farmland": {"farmland_class": "Prime", "is_prime": True},
        "ejscreen": {"minority_pct": 0.2, "low_income_pct": 0.15},
    },
    "regulations": [
        {
            "name": "ESA Section 7 Consultation",
            "jurisdiction": "Federal",
            "description": "T&E species present",
            "citation": "50 CFR §402",
        },
    ],
}

VALID_LLM_RESPONSE = json.dumps({
    "cells": [
        {
            "action": "site clearing",
            "category": "endangered_species",
            "framework": "ESA Section 7 Consultation",
            "determination": {
                "significance": "significant",
                "confidence": 0.9,
                "reasoning": "2 listed bat species; habitat disturbance likely.",
                "mitigation": ["avoidance", "minimization"],
            },
        },
        {
            "action": "panel installation",
            "category": "wetlands",
            "framework": "ESA Section 7 Consultation",
            "determination": {
                "significance": "minimal",
                "confidence": 0.4,
                "reasoning": "1 wetland feature nearby but no direct fill expected.",
                "mitigation": [],
            },
        },
    ]
})


class TestImpactAnalysisHappyPath(unittest.TestCase):
    def setUp(self):
        self.agent = ImpactAnalysisAgent(make_llm(VALID_LLM_RESPONSE))
        self.result = self.agent.run(dict(SAMPLE_STATE))
        self.matrix = self.result["impact_matrix"]

    def test_impact_matrix_key_present(self):
        self.assertIn("impact_matrix", self.result)

    def test_matrix_has_actions(self):
        self.assertEqual(self.matrix["actions"],
                         ["site clearing", "panel installation"])

    def test_matrix_has_categories(self):
        cats = self.matrix["categories"]
        self.assertIn("endangered_species", cats)
        self.assertIn("wetlands", cats)

    def test_cells_count(self):
        self.assertEqual(len(self.matrix["cells"]), 2)

    def test_cell_structure(self):
        cell = self.matrix["cells"][0]
        self.assertIn("action", cell)
        self.assertIn("category", cell)
        self.assertIn("framework", cell)
        self.assertIn("determination", cell)

    def test_determination_fields(self):
        det = self.matrix["cells"][0]["determination"]
        self.assertIn("significance", det)
        self.assertIn("confidence", det)
        self.assertIn("reasoning", det)
        self.assertIn("mitigation", det)
        self.assertIn("needs_review", det)

    def test_significance_value(self):
        det = self.matrix["cells"][0]["determination"]
        self.assertEqual(det["significance"], "significant")

    def test_confidence_value(self):
        det = self.matrix["cells"][0]["determination"]
        self.assertEqual(det["confidence"], 0.9)

    def test_rag_fallbacks_empty(self):
        self.assertEqual(self.matrix["rag_fallbacks"], [])

    def test_usage_tracked(self):
        usage = self.result.get("_usage", {}).get("impact_analysis")
        self.assertIsNotNone(usage)
        self.assertEqual(usage["input_tokens"], 200)
        self.assertEqual(usage["output_tokens"], 150)
        self.assertEqual(usage["model"], "mock-model")


class TestImpactAnalysisReviewFlagging(unittest.TestCase):
    def test_low_confidence_flagged(self):
        """Cell with confidence < threshold gets needs_review=True."""
        agent = ImpactAnalysisAgent(make_llm(VALID_LLM_RESPONSE))
        result = agent.run(dict(SAMPLE_STATE))
        low_conf_cell = result["impact_matrix"]["cells"][1]
        self.assertTrue(low_conf_cell["determination"]["needs_review"])

    def test_high_confidence_not_flagged(self):
        agent = ImpactAnalysisAgent(make_llm(VALID_LLM_RESPONSE))
        result = agent.run(dict(SAMPLE_STATE))
        high_conf_cell = result["impact_matrix"]["cells"][0]
        self.assertFalse(high_conf_cell["determination"]["needs_review"])


class TestImpactAnalysisFallback(unittest.TestCase):
    def test_empty_response(self):
        agent = ImpactAnalysisAgent(make_llm(""))
        result = agent.run(dict(SAMPLE_STATE))
        self.assertEqual(result["impact_matrix"]["cells"], [])

    def test_garbage_response(self):
        agent = ImpactAnalysisAgent(make_llm("I cannot help with that."))
        result = agent.run(dict(SAMPLE_STATE))
        self.assertEqual(result["impact_matrix"]["cells"], [])

    def test_markdown_fenced_json(self):
        fenced = f"```json\n{VALID_LLM_RESPONSE}\n```"
        agent = ImpactAnalysisAgent(make_llm(fenced))
        result = agent.run(dict(SAMPLE_STATE))
        self.assertEqual(len(result["impact_matrix"]["cells"]), 2)


class TestImpactAnalysisValidation(unittest.TestCase):
    def test_invalid_significance_defaults_to_none(self):
        bad = json.dumps({"cells": [{
            "action": "a", "category": "c", "framework": "f",
            "determination": {"significance": "EXTREME", "confidence": 0.5,
                              "reasoning": "x", "mitigation": []},
        }]})
        agent = ImpactAnalysisAgent(make_llm(bad))
        result = agent.run(dict(SAMPLE_STATE))
        self.assertEqual(
            result["impact_matrix"]["cells"][0]["determination"]["significance"],
            "none",
        )

    def test_confidence_clamped_to_range(self):
        bad = json.dumps({"cells": [{
            "action": "a", "category": "c", "framework": "f",
            "determination": {"significance": "moderate", "confidence": 1.5,
                              "reasoning": "x", "mitigation": []},
        }]})
        agent = ImpactAnalysisAgent(make_llm(bad))
        result = agent.run(dict(SAMPLE_STATE))
        self.assertLessEqual(
            result["impact_matrix"]["cells"][0]["determination"]["confidence"],
            1.0,
        )

    def test_invalid_mitigation_filtered(self):
        bad = json.dumps({"cells": [{
            "action": "a", "category": "c", "framework": "f",
            "determination": {"significance": "moderate", "confidence": 0.8,
                              "reasoning": "x",
                              "mitigation": ["avoidance", "magic", "compensation"]},
        }]})
        agent = ImpactAnalysisAgent(make_llm(bad))
        result = agent.run(dict(SAMPLE_STATE))
        mit = result["impact_matrix"]["cells"][0]["determination"]["mitigation"]
        self.assertEqual(mit, ["avoidance"])


class TestImpactAnalysisNoActions(unittest.TestCase):
    def test_infers_actions_from_project_type(self):
        state = dict(SAMPLE_STATE)
        state["parsed_project"] = {
            "project_type": "pipeline",
            "scale": "10mi",
            "location": "PA",
        }
        agent = ImpactAnalysisAgent(make_llm(VALID_LLM_RESPONSE))
        result = agent.run(state)
        actions = result["impact_matrix"]["actions"]
        self.assertEqual(len(actions), 3)
        self.assertTrue(all("pipeline" in a for a in actions))


if __name__ == "__main__":
    unittest.main(verbosity=2)
