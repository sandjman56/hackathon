"""Unit tests for ProjectParserAgent."""
import json
import sys
import os
import unittest
from unittest.mock import MagicMock

# Add backend root to path so imports work without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.project_parser import ProjectParserAgent
from llm.base import LLMResult


def make_llm(response: str) -> MagicMock:
    """Return a mock LLMProvider whose complete() returns an LLMResult."""
    llm = MagicMock()
    llm.provider_name = "mock"
    llm.complete.return_value = LLMResult(
        text=response,
        input_tokens=10,
        output_tokens=5,
        model="mock-model",
    )
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

    def test_usage_populated(self):
        usage = self.result.get("_usage", {}).get("project_parser")
        self.assertIsNotNone(usage)
        self.assertEqual(usage["input_tokens"], 10)
        self.assertEqual(usage["output_tokens"], 5)
        self.assertEqual(usage["model"], "mock-model")


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


class TestProjectParserActions(unittest.TestCase):
    RESPONSE_WITH_ACTIONS = json.dumps({
        "project_type": "solar farm",
        "scale": "50 MW",
        "location": "Pittsburgh, PA",
        "actions": [
            "site clearing and grading",
            "solar panel installation",
            "access road construction",
            "electrical interconnection",
        ],
    })

    def setUp(self):
        self.agent = ProjectParserAgent(make_llm(self.RESPONSE_WITH_ACTIONS))
        self.result = self.agent.run(dict(BASE_STATE))

    def test_actions_key_present(self):
        self.assertIn("actions", self.result["parsed_project"])

    def test_actions_is_list(self):
        self.assertIsInstance(self.result["parsed_project"]["actions"], list)

    def test_actions_count(self):
        self.assertEqual(len(self.result["parsed_project"]["actions"]), 4)

    def test_actions_are_strings(self):
        for action in self.result["parsed_project"]["actions"]:
            self.assertIsInstance(action, str)

    def test_fallback_actions_when_missing(self):
        """LLM returns valid JSON but no actions key → defaults to empty list."""
        no_actions = json.dumps({"project_type": "pipeline", "scale": "10mi", "location": "PA"})
        agent = ProjectParserAgent(make_llm(no_actions))
        result = agent.run(dict(BASE_STATE))
        self.assertEqual(result["parsed_project"]["actions"], [])

    def test_fallback_actions_on_bad_json(self):
        """Total parse failure → fallback includes empty actions."""
        agent = ProjectParserAgent(make_llm("not json"))
        result = agent.run(dict(BASE_STATE))
        self.assertEqual(result["parsed_project"]["actions"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
