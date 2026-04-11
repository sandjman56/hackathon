"""Unit tests for ProjectParserAgent."""
import json
import sys
import os
import unittest
from unittest.mock import MagicMock

# Add backend root to path so imports work without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.project_parser import ProjectParserAgent


def make_llm(response: str) -> MagicMock:
    """Return a mock LLMProvider whose complete() returns `response`."""
    llm = MagicMock()
    llm.provider_name = "mock"
    llm.complete.return_value = response
    return llm


BASE_STATE = {
    "project_name": "Riverside Solar Farm",
    "coordinates": "40.4406, -79.9959",
    "description": (
        "A 50 MW utility-scale solar farm on 400 acres of former farmland "
        "near Pittsburgh. Construction will disturb approximately 200 acres "
        "of land and cross two small tributaries."
    ),
}

VALID_RESPONSE = json.dumps({
    "project_type": "solar farm",
    "scale": "50 MW",
    "location": "Pittsburgh, PA",
})


class TestProjectParserHappyPath(unittest.TestCase):
    def setUp(self):
        self.agent = ProjectParserAgent(make_llm(VALID_RESPONSE))
        self.result = self.agent.run(dict(BASE_STATE))

    def test_parsed_project_key_present(self):
        self.assertIn("parsed_project", self.result)

    def test_project_type(self):
        self.assertEqual(self.result["parsed_project"]["project_type"], "solar farm")

    def test_scale(self):
        self.assertEqual(self.result["parsed_project"]["scale"], "50 MW")

    def test_location(self):
        self.assertEqual(self.result["parsed_project"]["location"], "Pittsburgh, PA")

    def test_original_state_keys_preserved(self):
        for key in BASE_STATE:
            self.assertIn(key, self.result)

    def test_llm_called_once(self):
        self.agent.llm.complete.call_count == 1


class TestProjectParserMarkdownFences(unittest.TestCase):
    """LLM wraps response in ```json ... ``` — should still parse."""

    def test_fenced_json(self):
        fenced = f"```json\n{VALID_RESPONSE}\n```"
        agent = ProjectParserAgent(make_llm(fenced))
        result = agent.run(dict(BASE_STATE))
        self.assertEqual(result["parsed_project"]["project_type"], "solar farm")

    def test_plain_fenced_json(self):
        fenced = f"```\n{VALID_RESPONSE}\n```"
        agent = ProjectParserAgent(make_llm(fenced))
        result = agent.run(dict(BASE_STATE))
        self.assertEqual(result["parsed_project"]["scale"], "50 MW")


class TestProjectParserFallback(unittest.TestCase):
    """Bad LLM output → safe fallback, no crash."""

    def _run_with(self, bad_response: str) -> dict:
        agent = ProjectParserAgent(make_llm(bad_response))
        return agent.run(dict(BASE_STATE))

    def test_invalid_json_uses_fallback(self):
        result = self._run_with("Sorry, I cannot help with that.")
        pp = result["parsed_project"]
        self.assertEqual(pp["project_type"], "unknown")
        self.assertEqual(pp["scale"], "unknown")

    def test_empty_response_uses_fallback(self):
        result = self._run_with("")
        self.assertIn("parsed_project", result)

    def test_fallback_location_uses_coordinates(self):
        result = self._run_with("not json")
        self.assertEqual(result["parsed_project"]["location"], BASE_STATE["coordinates"])

    def test_partial_json_missing_keys(self):
        partial = json.dumps({"project_type": "pipeline"})
        agent = ProjectParserAgent(make_llm(partial))
        result = agent.run(dict(BASE_STATE))
        pp = result["parsed_project"]
        self.assertEqual(pp["project_type"], "pipeline")
        self.assertEqual(pp["scale"], "unknown")          # default


class TestProjectParserOutputTypes(unittest.TestCase):
    """Ensure output types are always correct regardless of LLM weirdness."""

    def test_all_fields_are_strings(self):
        agent = ProjectParserAgent(make_llm(VALID_RESPONSE))
        result = agent.run(dict(BASE_STATE))
        pp = result["parsed_project"]
        self.assertIsInstance(pp["project_type"], str)
        self.assertIsInstance(pp["scale"], str)
        self.assertIsInstance(pp["location"], str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
