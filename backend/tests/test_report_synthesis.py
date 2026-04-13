"""Unit tests for ReportSynthesisAgent."""

import json
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.report_synthesis import ReportSynthesisAgent, CONFIDENCE_THRESHOLD
from llm.base import LLMResult


def make_llm(response: str = "Generated narrative content.") -> MagicMock:
    llm = MagicMock()
    llm.provider_name = "mock"
    llm.complete.return_value = LLMResult(
        text=response,
        input_tokens=100,
        output_tokens=80,
        model="mock-model",
    )
    return llm


# ── Realistic Pittsburgh highway project state ───────────────────────────────

SAMPLE_STATE = {
    "project_name": "Mon Valley Expressway Expansion",
    "coordinates": "40.3573,-79.8953",
    "description": (
        "Widening of a 4-mile section of PA Route 51 from 2 lanes to 4 lanes "
        "in the Mon Valley area south of Pittsburgh, including new interchange "
        "construction and stormwater management improvements."
    ),
    "parsed_project": {
        "project_type": "highway expansion",
        "scale": "4 miles, 2-to-4 lane widening",
        "location": "Mon Valley, Allegheny County, PA",
        "actions": [
            "land clearing and grading",
            "bridge construction",
            "road widening",
            "stormwater infrastructure",
            "operational traffic",
        ],
    },
    "environmental_data": {
        "query_location": {"lat": 40.3573, "lon": -79.8953},
        "usfws_species": {
            "count": 2,
            "species": [
                {"name": "Indiana Bat", "status": "Endangered"},
                {"name": "Northern Long-eared Bat", "status": "Threatened"},
            ],
        },
        "nwi_wetlands": {
            "count": 3,
            "wetlands": [
                {"type": "Freshwater Emergent"},
                {"type": "Freshwater Forested/Shrub"},
                {"type": "Riverine"},
            ],
        },
        "fema_flood_zones": {
            "in_sfha": True,
            "flood_zones": [
                {"flood_zone": "AE"},
                {"flood_zone": "X"},
            ],
        },
        "usda_farmland": {
            "farmland_class": "Not Prime Farmland",
            "is_prime": False,
        },
        "ejscreen": {
            "minority_pct": 0.35,
            "low_income_pct": 0.28,
            "percentile_pm25": 72.0,
        },
        "errors": {},
    },
    "regulations": [
        {
            "name": "Clean Water Act Section 404",
            "jurisdiction": "Federal",
            "description": "Wetland fill requires Section 404 permit",
            "citation": "33 USC §1344",
        },
        {
            "name": "ESA Section 7 Consultation",
            "jurisdiction": "Federal",
            "description": "Listed bat species in project area",
            "citation": "16 USC §1536",
        },
        {
            "name": "Executive Order 12898 (Environmental Justice)",
            "jurisdiction": "Federal",
            "description": "EJ community indicators above thresholds",
            "citation": "EO 12898",
        },
    ],
    "impact_matrix": {
        "actions": [
            "land clearing and grading",
            "bridge construction",
            "road widening",
            "stormwater infrastructure",
            "operational traffic",
        ],
        "categories": [
            "endangered_species",
            "wetlands",
            "floodplain",
            "environmental_justice",
            "air_quality",
            "noise",
            "traffic",
        ],
        "cells": [
            {
                "action": "land clearing and grading",
                "category": "endangered_species",
                "framework": "ESA Section 7",
                "determination": {
                    "significance": "significant",
                    "confidence": 0.88,
                    "reasoning": "Indiana Bat habitat disturbance during clearing.",
                    "mitigation": ["avoidance", "minimization"],
                    "needs_review": False,
                },
            },
            {
                "action": "road widening",
                "category": "wetlands",
                "framework": "Clean Water Act §404",
                "determination": {
                    "significance": "moderate",
                    "confidence": 0.82,
                    "reasoning": "3 NWI wetland features within project footprint.",
                    "mitigation": ["compensatory"],
                    "needs_review": False,
                },
            },
            {
                "action": "bridge construction",
                "category": "floodplain",
                "framework": "FEMA NFIP",
                "determination": {
                    "significance": "moderate",
                    "confidence": 0.75,
                    "reasoning": "Bridge footings in AE flood zone.",
                    "mitigation": ["minimization"],
                    "needs_review": False,
                },
            },
            {
                "action": "operational traffic",
                "category": "environmental_justice",
                "framework": "EO 12898",
                "determination": {
                    "significance": "moderate",
                    "confidence": 0.45,
                    "reasoning": "EJ indicators present but no direct displacement data.",
                    "mitigation": ["minimization"],
                    "needs_review": True,
                },
            },
            {
                "action": "operational traffic",
                "category": "air_quality",
                "framework": "Clean Air Act",
                "determination": {
                    "significance": "minimal",
                    "confidence": 0.55,
                    "reasoning": "No air quality monitoring data; based on project type.",
                    "mitigation": [],
                    "needs_review": True,
                },
            },
            {
                "action": "road widening",
                "category": "noise",
                "framework": "FHWA 23 CFR 772",
                "determination": {
                    "significance": "minimal",
                    "confidence": 0.7,
                    "reasoning": "Standard highway noise expected; no sensitive receptors data.",
                    "mitigation": ["minimization"],
                    "needs_review": False,
                },
            },
        ],
        "rag_fallbacks": [],
    },
}


# ── Degraded state: EJScreen failed, sparse regulations ─────────────────────

DEGRADED_STATE = {
    "project_name": "Test Degraded Project",
    "coordinates": "40.0,-80.0",
    "description": "A small commercial development.",
    "parsed_project": {
        "project_type": "commercial development",
        "scale": "2 acres",
        "location": "Rural PA",
        "actions": ["site preparation", "construction"],
    },
    "environmental_data": {
        "query_location": {"lat": 40.0, "lon": -80.0},
        "usfws_species": None,
        "nwi_wetlands": {"count": 0, "wetlands": []},
        "fema_flood_zones": None,
        "usda_farmland": {"farmland_class": "Prime", "is_prime": True},
        "ejscreen": None,
        "errors": {"usfws": "timeout", "fema": "404 Not Found", "ejscreen": "rate limited"},
    },
    "regulations": [],
    "impact_matrix": {
        "actions": ["site preparation", "construction"],
        "categories": ["prime_farmland"],
        "cells": [
            {
                "action": "site preparation",
                "category": "prime_farmland",
                "framework": "Farmland Protection Policy Act",
                "determination": {
                    "significance": "moderate",
                    "confidence": 0.4,
                    "reasoning": "Prime farmland conversion but limited acreage data.",
                    "mitigation": ["avoidance"],
                    "needs_review": True,
                },
            },
        ],
        "rag_fallbacks": [],
    },
}


# ── Tests ────────────────────────────────────────────────────────────────────

class TestReportSynthesisHappyPath(unittest.TestCase):
    """Full pipeline with mock LLM and realistic Pittsburgh highway data."""

    def setUp(self):
        self.agent = ReportSynthesisAgent(make_llm())
        result = self.agent.run(dict(SAMPLE_STATE))
        self.report = result["report"]

    def test_report_key_present(self):
        self.assertIn("reports", self.report)
        self.assertEqual(self.report["stage"], "complete")

    def test_single_nepa_report(self):
        self.assertEqual(len(self.report["reports"]), 1)
        r = self.report["reports"][0]
        self.assertEqual(r["framework_id"], "NEPA")
        self.assertEqual(r["document_type"], "EA")

    def test_all_sections_present(self):
        sections = self.report["reports"][0]["sections"]
        ids = [s["section_number"] for s in sections]
        self.assertEqual(ids, ["1", "2", "3a", "3b", "4", "5", "6", "7", "8", "9", "10"])

    def test_section_structure(self):
        for section in self.report["reports"][0]["sections"]:
            self.assertIn("section_number", section)
            self.assertIn("section_title", section)
            self.assertIn("content", section)
            self.assertIn("low_confidence_highlights", section)
            self.assertIn("requires_llm", section)
            self.assertIsInstance(section["content"], str)
            self.assertTrue(len(section["content"]) > 0)

    def test_title_page_static(self):
        title = self.report["reports"][0]["sections"][0]
        self.assertFalse(title["requires_llm"])
        self.assertIn("Mon Valley Expressway Expansion", title["content"])
        self.assertIn("Automated EIA Screening System", title["content"])

    def test_llm_called_for_narrative_sections(self):
        """LLM should be called for sections 2, 3a, 3b, 4, 5, 7."""
        self.assertEqual(self.agent._total_llm_calls, 6)

    def test_impact_matrix_table(self):
        table = self.report["reports"][0]["impact_matrix_table"]
        self.assertEqual(len(table["actions"]), 5)
        self.assertEqual(len(table["categories"]), 7)
        self.assertTrue(len(table["cells"]) > 0)
        cell = table["cells"][0]
        self.assertIn("action", cell)
        self.assertIn("category", cell)
        self.assertIn("significance", cell)
        self.assertIn("confidence", cell)

    def test_metadata(self):
        meta = self.report["reports"][0]["metadata"]
        self.assertEqual(meta["total_llm_calls"], 6)
        self.assertIn("generated_at", meta)
        self.assertEqual(meta["confidence_threshold"], CONFIDENCE_THRESHOLD)
        self.assertTrue(meta["total_tokens_used"] > 0)

    def test_usage_tracked_in_state(self):
        agent = ReportSynthesisAgent(make_llm())
        result = agent.run(dict(SAMPLE_STATE))
        usage = result.get("_usage", {}).get("report_synthesis")
        self.assertIsNotNone(usage)
        self.assertEqual(usage["input_tokens"], 600)   # 6 calls × 100
        self.assertEqual(usage["output_tokens"], 480)   # 6 calls × 80
        self.assertEqual(usage["model"], "mock-model")


class TestDisclaimerAndConfidence(unittest.TestCase):
    """Verify confidence thresholding and disclaimer generation."""

    def setUp(self):
        self.agent = ReportSynthesisAgent(make_llm())
        result = self.agent.run(dict(SAMPLE_STATE))
        self.report_data = result["report"]["reports"][0]

    def test_disclaimer_items_captured(self):
        items = self.report_data["disclaimer_items"]
        # Two cells have needs_review=True (EJ at 0.45, air at 0.55)
        self.assertEqual(len(items), 2)

    def test_disclaimer_item_structure(self):
        for item in self.report_data["disclaimer_items"]:
            self.assertIn("category", item)
            self.assertIn("determination", item)
            self.assertIn("confidence", item)
            self.assertIn("reasoning", item)
            self.assertLess(item["confidence"], CONFIDENCE_THRESHOLD)

    def test_low_confidence_highlights_in_consequences(self):
        consequences = [
            s for s in self.report_data["sections"]
            if s["section_number"] == "5"
        ][0]
        highlights = consequences["low_confidence_highlights"]
        self.assertEqual(len(highlights), 2)
        for h in highlights:
            self.assertIn("text_excerpt", h)
            self.assertIn("confidence", h)
            self.assertIn("confidence_factors", h)
            self.assertIn("reasoning", h)
            self.assertLess(h["confidence"], CONFIDENCE_THRESHOLD)

    def test_human_review_count_in_metadata(self):
        meta = self.report_data["metadata"]
        self.assertEqual(meta["human_review_count"], 2)
        self.assertEqual(meta["low_confidence_count"], 2)


class TestDegradedState(unittest.TestCase):
    """Test with missing API data and sparse regulations."""

    def setUp(self):
        self.agent = ReportSynthesisAgent(make_llm())
        result = self.agent.run(dict(DEGRADED_STATE))
        self.report_data = result["report"]["reports"][0]

    def test_report_still_generates(self):
        self.assertEqual(len(self.report_data["sections"]), 11)

    def test_consultation_shows_errors(self):
        consultation = [
            s for s in self.report_data["sections"]
            if s["section_number"] == "8"
        ][0]
        self.assertIn("Error", consultation["content"])

    def test_disclaimer_flags_low_confidence(self):
        items = self.report_data["disclaimer_items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["category"], "prime_farmland")

    def test_matrix_table_sparse(self):
        table = self.report_data["impact_matrix_table"]
        self.assertEqual(len(table["actions"]), 2)
        self.assertEqual(len(table["categories"]), 1)
        self.assertEqual(len(table["cells"]), 1)


class TestLLMError(unittest.TestCase):
    """Test behavior when LLM calls raise exceptions."""

    def test_llm_exception_handled_gracefully(self):
        llm = MagicMock()
        llm.provider_name = "mock"
        llm.complete.side_effect = RuntimeError("API timeout")

        agent = ReportSynthesisAgent(llm)
        result = agent.run(dict(SAMPLE_STATE))
        report = result["report"]

        self.assertEqual(report["stage"], "complete")
        for section in report["reports"][0]["sections"]:
            if section["requires_llm"]:
                self.assertIn("Error generating narrative", section["content"])


class TestMatrixTableRendering(unittest.TestCase):
    """Verify the static matrix table section renders correctly."""

    def setUp(self):
        self.agent = ReportSynthesisAgent(make_llm())
        result = self.agent.run(dict(SAMPLE_STATE))
        self.matrix_section = [
            s for s in result["report"]["reports"][0]["sections"]
            if s["section_number"] == "6"
        ][0]

    def test_matrix_is_markdown_table(self):
        content = self.matrix_section["content"]
        self.assertIn("| Category |", content)
        self.assertIn("|---|", content)

    def test_matrix_contains_significance_symbols(self):
        content = self.matrix_section["content"]
        # Should have at least some significance symbols
        has_symbol = any(s in content for s in ["X", "!", "~", "-"])
        self.assertTrue(has_symbol)

    def test_matrix_contains_legend(self):
        content = self.matrix_section["content"]
        self.assertIn("Legend", content)


class TestMitigationSection(unittest.TestCase):
    """Verify mitigation section only appears when mitigation exists."""

    def test_mitigation_llm_called_when_data_exists(self):
        agent = ReportSynthesisAgent(make_llm())
        agent.run(dict(SAMPLE_STATE))
        # Section 7 (mitigation) should trigger an LLM call since
        # SAMPLE_STATE has cells with mitigation
        self.assertEqual(agent._total_llm_calls, 6)

    def test_no_mitigation_data(self):
        """When no cells have mitigation, section 7 prompt is empty."""
        state = dict(SAMPLE_STATE)
        state["impact_matrix"] = {
            "actions": ["build"],
            "categories": ["air"],
            "cells": [{
                "action": "build",
                "category": "air",
                "framework": "CAA",
                "determination": {
                    "significance": "none",
                    "confidence": 0.9,
                    "reasoning": "No impact.",
                    "mitigation": [],
                    "needs_review": False,
                },
            }],
            "rag_fallbacks": [],
        }
        agent = ReportSynthesisAgent(make_llm())
        agent.run(state)
        # 5 LLM calls instead of 6 — mitigation prompt is empty so skipped
        self.assertEqual(agent._total_llm_calls, 5)


class TestMissingUpstreamData(unittest.TestCase):
    """Test with completely missing upstream agent outputs."""

    def test_empty_state(self):
        agent = ReportSynthesisAgent(make_llm())
        state = {
            "project_name": "Empty",
            "coordinates": "",
            "description": "",
        }
        result = agent.run(state)
        report = result["report"]
        self.assertEqual(report["stage"], "complete")
        self.assertEqual(len(report["reports"][0]["sections"]), 11)

    def test_none_values_in_state(self):
        agent = ReportSynthesisAgent(make_llm())
        state = {
            "project_name": "None Test",
            "coordinates": "",
            "description": "",
            "parsed_project": None,
            "environmental_data": None,
            "regulations": None,
            "impact_matrix": None,
        }
        result = agent.run(state)
        report = result["report"]
        self.assertEqual(report["stage"], "complete")


class TestConfidenceThreshold(unittest.TestCase):
    """Verify threshold logic across a range of confidence values."""

    def _make_state_with_confidence(self, confidence: float) -> dict:
        state = dict(SAMPLE_STATE)
        state["impact_matrix"] = {
            "actions": ["build"],
            "categories": ["wetlands"],
            "cells": [{
                "action": "build",
                "category": "wetlands",
                "framework": "CWA",
                "determination": {
                    "significance": "moderate",
                    "confidence": confidence,
                    "reasoning": "Test case.",
                    "mitigation": [],
                    "needs_review": confidence < 0.6,
                },
            }],
            "rag_fallbacks": [],
        }
        return state

    def test_confidence_0_4_flagged(self):
        agent = ReportSynthesisAgent(make_llm())
        result = agent.run(self._make_state_with_confidence(0.4))
        items = result["report"]["reports"][0]["disclaimer_items"]
        self.assertEqual(len(items), 1)

    def test_confidence_0_59_flagged(self):
        agent = ReportSynthesisAgent(make_llm())
        result = agent.run(self._make_state_with_confidence(0.59))
        items = result["report"]["reports"][0]["disclaimer_items"]
        self.assertEqual(len(items), 1)

    def test_confidence_0_6_not_flagged(self):
        agent = ReportSynthesisAgent(make_llm())
        result = agent.run(self._make_state_with_confidence(0.6))
        items = result["report"]["reports"][0]["disclaimer_items"]
        self.assertEqual(len(items), 0)

    def test_confidence_0_95_not_flagged(self):
        agent = ReportSynthesisAgent(make_llm())
        result = agent.run(self._make_state_with_confidence(0.95))
        items = result["report"]["reports"][0]["disclaimer_items"]
        self.assertEqual(len(items), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
