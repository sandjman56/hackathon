"""Unit tests for provider_factory helpers."""
import sys
import os
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from llm.provider_factory import (
    available_providers,
    get_llm_for_model,
    MissingAPIKeyError,
    UnknownModelError,
)


class TestAvailableProviders(unittest.TestCase):

    @patch.dict(os.environ, {"OPENAI_API_KEY": "k", "CLAUDE_KEY": "k", "GOOGLE_API_KEY": "k"})
    def test_all_set(self):
        result = available_providers()
        self.assertTrue(result["openai"])
        self.assertTrue(result["anthropic"])
        self.assertTrue(result["gemini"])

    def test_none_set(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("OPENAI_API_KEY", "CLAUDE_KEY", "GOOGLE_API_KEY")}
        with patch.dict(os.environ, env, clear=True):
            result = available_providers()
            self.assertFalse(result["openai"])
            self.assertFalse(result["anthropic"])
            self.assertFalse(result["gemini"])

    def test_partial(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("OPENAI_API_KEY", "GOOGLE_API_KEY")}
        env["CLAUDE_KEY"] = "k"
        with patch.dict(os.environ, env, clear=True):
            result = available_providers()
            self.assertFalse(result["openai"])
            self.assertTrue(result["anthropic"])
            self.assertFalse(result["gemini"])


class TestGetLlmForModel(unittest.TestCase):

    def test_unknown_model_raises(self):
        with self.assertRaises(UnknownModelError):
            get_llm_for_model("totally-fake-model-xyz")

    def test_missing_openai_key_raises(self):
        env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(MissingAPIKeyError):
                get_llm_for_model("gpt-5.4")

    def test_missing_claude_key_raises(self):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_KEY"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(MissingAPIKeyError):
                get_llm_for_model("claude-haiku-4-5-20251001")

    def test_missing_gemini_key_raises(self):
        env = {k: v for k, v in os.environ.items() if k != "GOOGLE_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(MissingAPIKeyError):
                get_llm_for_model("gemini-2.5-flash")


if __name__ == "__main__":
    unittest.main(verbosity=2)
