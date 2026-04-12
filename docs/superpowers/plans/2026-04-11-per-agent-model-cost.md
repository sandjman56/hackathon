# Per-Agent Model Selection & Cost Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-agent LLM model dropdowns and per-agent cost tracking to the EIA pipeline UI

**Architecture:** Each provider's `complete()` returns an `LLMResult` dataclass carrying token counts. A static `pricing.py` maps model IDs to $/1M-token rates. The pipeline resolves model selections per-request (no startup singletons), emits `agent_cost` SSE events after each agent, and the frontend renders `<select>` dropdowns + cost chips per row.

**Tech Stack:** Python 3.12 / FastAPI / langchain (OpenAI, Gemini) / anthropic SDK / React 18 / Vite / Vitest / pytest

**Spec:** `docs/superpowers/specs/2026-04-11-per-agent-model-cost-design.md`

---

## Phase 1 — Backend Foundation

### Task 1: Add LLMResult dataclass to base.py

**Files:**
- Modify: `backend/llm/base.py`

- [ ] **Step 1: Add LLMResult dataclass and update complete() return annotation**

```python
# backend/llm/base.py — full replacement
from dataclasses import dataclass
from abc import ABC, abstractmethod


@dataclass
class LLMResult:
    """Return type for LLMProvider.complete() — carries token counts for cost tracking."""
    text: str
    input_tokens: int
    output_tokens: int
    model: str  # exact model id; matches a pricing.py key


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        raise NotImplementedError("Subclasses must implement provider_name")

    @abstractmethod
    def complete(self, prompt: str, system: str = None) -> LLMResult:
        raise NotImplementedError("Subclasses must implement complete()")

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        raise NotImplementedError("Subclasses must implement embed()")

    @abstractmethod
    def chat(self, messages: list[dict]) -> str:
        raise NotImplementedError("Subclasses must implement chat()")
```

- [ ] **Step 2: Run existing backend tests to verify nothing crashes**

Run: `cd backend && python -m pytest tests/test_project_parser.py -v`
Expected: PASS (tests use mocks, not real providers — the ABC change doesn't affect them yet)

- [ ] **Step 3: Commit**

```bash
git add backend/llm/base.py
git commit -m "feat(llm): add LLMResult dataclass to base.py

LLMProvider.complete() now declares LLMResult return type.
Downstream providers and agents updated in following commits."
```

---

### Task 2: Create pricing table with tests

**Files:**
- Create: `backend/llm/pricing.py`
- Create: `backend/tests/test_pricing.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_pricing.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_pricing.py -v`
Expected: FAIL (ImportError — `llm.pricing` does not exist yet)

- [ ] **Step 3: Write pricing.py implementation**

```python
# backend/llm/pricing.py
"""Per-model pricing table for cost tracking in the pipeline.

All prices are USD per 1,000,000 tokens, taken from each provider's
official pricing page on LAST_UPDATED.

Refresh workflow: re-run web searches for each SOURCES URL,
update the numbers + LAST_UPDATED, and commit.
"""

LAST_UPDATED = "2026-04-11"

SOURCES = {
    "openai": "https://openai.com/api/pricing/",
    "anthropic": "https://www.anthropic.com/pricing",
    "gemini": "https://ai.google.dev/pricing",
}

# Each entry: {"provider": str, "label": str, "input": float, "output": float}
# input/output are USD per 1,000,000 tokens.
MODEL_PRICING: dict[str, dict] = {
    "gpt-5.4": {
        "provider": "openai",
        "label": "OpenAI \u00b7 GPT-5.4",
        "input": 2.50,
        "output": 15.00,
    },
    "gpt-5.4-mini": {
        "provider": "openai",
        "label": "OpenAI \u00b7 GPT-5.4 mini",
        "input": 0.75,
        "output": 4.50,
    },
    "claude-opus-4-6": {
        "provider": "anthropic",
        "label": "Claude \u00b7 Opus 4.6",
        "input": 5.00,
        "output": 25.00,
    },
    "claude-sonnet-4-6": {
        "provider": "anthropic",
        "label": "Claude \u00b7 Sonnet 4.6",
        "input": 3.00,
        "output": 15.00,
    },
    "claude-haiku-4-5-20251001": {
        "provider": "anthropic",
        "label": "Claude \u00b7 Haiku 4.5",
        "input": 1.00,
        "output": 5.00,
    },
    "gemini-2.5-pro": {
        "provider": "gemini",
        "label": "Gemini \u00b7 2.5 Pro",
        "input": 1.25,
        "output": 10.00,
    },
    "gemini-2.5-flash": {
        "provider": "gemini",
        "label": "Gemini \u00b7 2.5 Flash",
        "input": 0.30,
        "output": 2.50,
    },
    "gemini-2.0-flash": {
        "provider": "gemini",
        "label": "Gemini \u00b7 2.0 Flash",
        "input": 0.10,
        "output": 0.40,
    },
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute USD cost for one completion. Returns 0.0 for unknown models."""
    p = MODEL_PRICING.get(model)
    if not p:
        return 0.0
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_pricing.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/llm/pricing.py backend/tests/test_pricing.py
git commit -m "feat(llm): add static pricing table with verified 2026 prices

Prices sourced from each provider's official pricing page on 2026-04-11.
Includes gpt-5.4, Claude 4.5/4.6, and Gemini 2.0/2.5 families."
```

---

### Task 3: Update all four providers to return LLMResult

Each provider's `complete()` now returns `LLMResult` with token counts from the SDK response. Constructors gain an optional `model` kwarg so the factory can override the env-var default per request.

**Files:**
- Modify: `backend/llm/openai_provider.py`
- Modify: `backend/llm/anthropic_provider.py`
- Modify: `backend/llm/gemini_provider.py`
- Modify: `backend/llm/ollama_provider.py`

- [ ] **Step 1: Update OpenAI provider**

```python
# backend/llm/openai_provider.py — full replacement
import logging
import os

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from .base import LLMProvider, LLMResult

logger = logging.getLogger("eia.llm.openai")


class OpenAIProvider(LLMProvider):
    """LLM provider backed by OpenAI via langchain-openai."""

    def __init__(self, model: str | None = None):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set.")
        self._model = model or os.environ.get("OPENAI_MODEL", "gpt-4o")
        embedding_model = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

        self._llm = ChatOpenAI(model=self._model, api_key=api_key)
        self._embeddings = OpenAIEmbeddings(model=embedding_model, api_key=api_key)

    @property
    def provider_name(self) -> str:
        return "openai"

    def complete(self, prompt: str, system: str = None) -> LLMResult:
        messages = []
        if system:
            messages.append(("system", system))
        messages.append(("human", prompt))
        response = self._llm.invoke(messages)
        usage = (response.response_metadata or {}).get("token_usage", {})
        if not usage:
            logger.warning("usage metadata missing from OpenAI response — cost will be $0")
        return LLMResult(
            text=response.content,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            model=self._model,
        )

    def embed(self, text: str) -> list[float]:
        return self._embeddings.embed_query(text)

    def chat(self, messages: list[dict]) -> str:
        langchain_messages = []
        for msg in messages:
            langchain_messages.append((msg["role"], msg["content"]))
        response = self._llm.invoke(langchain_messages)
        return response.content
```

- [ ] **Step 2: Update Anthropic provider**

```python
# backend/llm/anthropic_provider.py — full replacement
import logging
import os

import anthropic

from .base import LLMProvider, LLMResult

logger = logging.getLogger("eia.llm.anthropic")


class AnthropicProvider(LLMProvider):
    """LLM provider backed by the Anthropic Python SDK."""

    def __init__(self, model: str | None = None):
        api_key = os.environ.get("CLAUDE_KEY")
        if not api_key:
            raise ValueError("CLAUDE_KEY environment variable is not set.")
        self._model = model or os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
        self._client = anthropic.Anthropic(api_key=api_key)

    @property
    def provider_name(self) -> str:
        return "anthropic"

    def complete(self, prompt: str, system: str = None) -> LLMResult:
        kwargs = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        response = self._client.messages.create(**kwargs)
        usage = getattr(response, "usage", None)
        if not usage:
            logger.warning("usage metadata missing from Anthropic response — cost will be $0")
        return LLMResult(
            text=response.content[0].text,
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
            model=self._model,
        )

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError(
            "Anthropic does not provide an embedding API. "
            "Configure EMBEDDING_PROVIDER=openai or ollama instead."
        )

    def chat(self, messages: list[dict]) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            messages=messages,
        )
        return response.content[0].text
```

- [ ] **Step 3: Update Gemini provider**

```python
# backend/llm/gemini_provider.py — full replacement
import logging
import os

from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from .base import LLMProvider, LLMResult

logger = logging.getLogger("eia.llm.gemini")


class GeminiProvider(LLMProvider):
    """LLM provider backed by Google Gemini via langchain-google-genai."""

    def __init__(self, model: str | None = None):
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY environment variable is not set.")
        self._model = model or os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
        embedding_model = os.environ.get("GEMINI_EMBEDDING_MODEL", "models/text-embedding-004")

        self._llm = ChatGoogleGenerativeAI(model=self._model, google_api_key=api_key)
        self._embeddings = GoogleGenerativeAIEmbeddings(model=embedding_model, google_api_key=api_key)

    @property
    def provider_name(self) -> str:
        return "gemini"

    def complete(self, prompt: str, system: str = None) -> LLMResult:
        messages = []
        if system:
            messages.append(("system", system))
        messages.append(("human", prompt))
        response = self._llm.invoke(messages)
        usage = getattr(response, "usage_metadata", None) or {}
        if not usage:
            logger.warning("usage metadata missing from Gemini response — cost will be $0")
        return LLMResult(
            text=response.content,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            model=self._model,
        )

    def embed(self, text: str) -> list[float]:
        return self._embeddings.embed_query(text)

    def chat(self, messages: list[dict]) -> str:
        langchain_messages = []
        for msg in messages:
            langchain_messages.append((msg["role"], msg["content"]))
        response = self._llm.invoke(langchain_messages)
        return response.content
```

- [ ] **Step 4: Update Ollama provider**

```python
# backend/llm/ollama_provider.py — full replacement
import os

import ollama

from .base import LLMProvider, LLMResult


class OllamaProvider(LLMProvider):
    """LLM provider backed by a local Ollama instance. Fully offline, no API keys required."""

    def __init__(self):
        self._base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        self._model = os.environ.get("OLLAMA_MODEL", "llama3")
        self._client = ollama.Client(host=self._base_url)

    @property
    def provider_name(self) -> str:
        return "ollama"

    def complete(self, prompt: str, system: str = None) -> LLMResult:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = self._client.chat(model=self._model, messages=messages)
        return LLMResult(
            text=response["message"]["content"],
            input_tokens=0,
            output_tokens=0,
            model="ollama-local",
        )

    def embed(self, text: str) -> list[float]:
        response = self._client.embeddings(model=self._model, prompt=text)
        return response["embedding"]

    def chat(self, messages: list[dict]) -> str:
        response = self._client.chat(model=self._model, messages=messages)
        return response["message"]["content"]
```

- [ ] **Step 5: Commit**

```bash
git add backend/llm/openai_provider.py backend/llm/anthropic_provider.py backend/llm/gemini_provider.py backend/llm/ollama_provider.py
git commit -m "feat(llm): update all providers to return LLMResult with token counts

Each complete() now returns LLMResult(text, input_tokens, output_tokens, model).
Constructors accept optional model kwarg for per-request override.
Defensive fallback: missing usage metadata logs warning, returns zero tokens."
```

---

### Task 4: Add provider factory helpers with tests

**Files:**
- Modify: `backend/llm/provider_factory.py`
- Create: `backend/tests/test_provider_factory.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_provider_factory.py
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

    @patch.dict(os.environ, {}, clear=True)
    def test_none_set(self):
        # Ensure the vars we check are absent
        for key in ("OPENAI_API_KEY", "CLAUDE_KEY", "GOOGLE_API_KEY"):
            os.environ.pop(key, None)
        result = available_providers()
        self.assertFalse(result["openai"])
        self.assertFalse(result["anthropic"])
        self.assertFalse(result["gemini"])

    @patch.dict(os.environ, {"CLAUDE_KEY": "k"}, clear=True)
    def test_partial(self):
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("GOOGLE_API_KEY", None)
        result = available_providers()
        self.assertFalse(result["openai"])
        self.assertTrue(result["anthropic"])
        self.assertFalse(result["gemini"])


class TestGetLlmForModel(unittest.TestCase):

    def test_unknown_model_raises(self):
        with self.assertRaises(UnknownModelError):
            get_llm_for_model("totally-fake-model-xyz")

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_openai_key_raises(self):
        os.environ.pop("OPENAI_API_KEY", None)
        with self.assertRaises(MissingAPIKeyError):
            get_llm_for_model("gpt-5.4")

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_claude_key_raises(self):
        os.environ.pop("CLAUDE_KEY", None)
        with self.assertRaises(MissingAPIKeyError):
            get_llm_for_model("claude-haiku-4-5-20251001")

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_gemini_key_raises(self):
        os.environ.pop("GOOGLE_API_KEY", None)
        with self.assertRaises(MissingAPIKeyError):
            get_llm_for_model("gemini-2.5-flash")


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_provider_factory.py -v`
Expected: FAIL (ImportError — `MissingAPIKeyError`, `UnknownModelError`, `available_providers`, `get_llm_for_model` don't exist yet)

- [ ] **Step 3: Implement factory helpers**

```python
# backend/llm/provider_factory.py — full replacement
import os

from .base import LLMProvider


class MissingAPIKeyError(RuntimeError):
    """Raised when a model's provider requires an API key that isn't set."""
    pass


class UnknownModelError(ValueError):
    """Raised when a model_id isn't in the pricing table."""
    pass


def get_llm_provider() -> LLMProvider:
    """Resolve the LLM_PROVIDER env var to a concrete LLMProvider instance."""
    provider = os.environ.get("LLM_PROVIDER", "gemini").lower()

    if provider == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider()
    elif provider == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    elif provider == "gemini":
        from .gemini_provider import GeminiProvider
        return GeminiProvider()
    elif provider == "ollama":
        from .ollama_provider import OllamaProvider
        return OllamaProvider()
    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER: '{provider}'. "
            f"Supported values: openai, anthropic, gemini, ollama"
        )


def get_embedding_provider() -> LLMProvider:
    """Resolve the EMBEDDING_PROVIDER env var to a concrete LLMProvider instance."""
    provider = os.environ.get("EMBEDDING_PROVIDER", "gemini").lower()

    if provider == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider()
    elif provider == "gemini":
        from .gemini_provider import GeminiProvider
        return GeminiProvider()
    elif provider == "ollama":
        from .ollama_provider import OllamaProvider
        return OllamaProvider()
    elif provider == "anthropic":
        raise ValueError(
            "Anthropic does not provide an embedding API. "
            "Set EMBEDDING_PROVIDER to 'openai', 'gemini', or 'ollama' instead."
        )
    else:
        raise ValueError(
            f"Unknown EMBEDDING_PROVIDER: '{provider}'. "
            f"Supported values: openai, gemini, ollama"
        )


def get_llm_for_model(model_id: str) -> LLMProvider:
    """Instantiate the correct provider class for a pricing.py model id.

    Raises MissingAPIKeyError if the required env var is absent.
    Raises UnknownModelError if model_id is not in MODEL_PRICING.
    """
    from .pricing import MODEL_PRICING

    if model_id not in MODEL_PRICING:
        raise UnknownModelError(f"unknown model: {model_id!r}")

    provider_name = MODEL_PRICING[model_id]["provider"]

    if provider_name == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            raise MissingAPIKeyError("OPENAI_API_KEY not set")
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(model=model_id)

    if provider_name == "anthropic":
        if not os.environ.get("CLAUDE_KEY"):
            raise MissingAPIKeyError("CLAUDE_KEY not set")
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(model=model_id)

    if provider_name == "gemini":
        if not os.environ.get("GOOGLE_API_KEY"):
            raise MissingAPIKeyError("GOOGLE_API_KEY not set")
        from .gemini_provider import GeminiProvider
        return GeminiProvider(model=model_id)

    raise UnknownModelError(f"unknown provider for model {model_id!r}")


def available_providers() -> dict[str, bool]:
    """Check which provider API keys are set. Used by GET /api/providers."""
    return {
        "openai": bool(os.environ.get("OPENAI_API_KEY")),
        "anthropic": bool(os.environ.get("CLAUDE_KEY")),
        "gemini": bool(os.environ.get("GOOGLE_API_KEY")),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_provider_factory.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/llm/provider_factory.py backend/tests/test_provider_factory.py
git commit -m "feat(llm): add get_llm_for_model, available_providers, error classes

get_llm_for_model(model_id) resolves a pricing.py key to a provider instance.
available_providers() checks env vars without instantiating.
MissingAPIKeyError / UnknownModelError for pre-flight validation."
```

---

### Task 5: Update project_parser to consume LLMResult and populate _usage

**Files:**
- Modify: `backend/agents/project_parser.py`
- Modify: `backend/tests/test_project_parser.py`

- [ ] **Step 1: Update the test mock to return LLMResult and add _usage assertion**

In `backend/tests/test_project_parser.py`, change the import and `make_llm` helper, and add a new test:

Add import at top:
```python
from llm.base import LLMResult
```

Replace `make_llm`:
```python
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
```

Add to `TestProjectParserHappyPath`:
```python
    def test_usage_populated(self):
        usage = self.result.get("_usage", {}).get("project_parser")
        self.assertIsNotNone(usage)
        self.assertEqual(usage["input_tokens"], 10)
        self.assertEqual(usage["output_tokens"], 5)
        self.assertEqual(usage["model"], "mock-model")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_project_parser.py::TestProjectParserHappyPath::test_usage_populated -v`
Expected: FAIL — `_usage` key not in result (agent doesn't populate it yet)

- [ ] **Step 3: Update project_parser.py**

In `backend/agents/project_parser.py`, change the `run()` method.

Replace:
```python
            raw = self.llm.complete(prompt, system=_SYSTEM)
            logger.info("[ProjectParser] LLM response: %s", raw[:300])
```
With:
```python
            llm_result = self.llm.complete(prompt, system=_SYSTEM)
            raw = llm_result.text
            logger.info("[ProjectParser] LLM response: %s", raw[:300])
```

Add before `state["parsed_project"] = result` (line 75):
```python
        state.setdefault("_usage", {})["project_parser"] = {
            "input_tokens": llm_result.input_tokens,
            "output_tokens": llm_result.output_tokens,
            "model": llm_result.model,
        }
```

In the `except` block, after `result = { ... }` (line 73), add:
```python
            llm_result = None  # no usage on failure
```

And wrap the _usage population in a guard:
```python
        if llm_result:
            state.setdefault("_usage", {})["project_parser"] = {
                "input_tokens": llm_result.input_tokens,
                "output_tokens": llm_result.output_tokens,
                "model": llm_result.model,
            }
```

The key change: declare `llm_result = None` before the `try` block, assign it inside `try`, and only populate `_usage` if it's not None.

- [ ] **Step 4: Run all project_parser tests**

Run: `cd backend && python -m pytest tests/test_project_parser.py -v`
Expected: All PASS (including new `test_usage_populated`)

- [ ] **Step 5: Commit**

```bash
git add backend/agents/project_parser.py backend/tests/test_project_parser.py
git commit -m "feat(agents): project_parser consumes LLMResult, populates _usage

complete() now returns LLMResult; text extracted via .text attribute.
state['_usage']['project_parser'] carries input_tokens, output_tokens, model."
```

---

### Task 6: Update regulatory_screening to consume LLMResult and populate _usage

**Files:**
- Modify: `backend/agents/regulatory_screening.py`
- Modify: `backend/tests/test_regulatory_agent.py`

- [ ] **Step 1: Update the test mock and add _usage assertion**

In `backend/tests/test_regulatory_agent.py`, add import:
```python
from llm.base import LLMResult
```

In `test_agent_returns_regs_when_corpus_present`, replace:
```python
    fake_llm.complete.return_value = json.dumps([{
        "name": "NEPA Environmental Assessment",
        "jurisdiction": "Federal",
        "description": "Triggered by 40 CFR 1501.3.",
        "citation": "40 CFR \u00a71501.3",
    }])
```
With:
```python
    fake_llm.complete.return_value = LLMResult(
        text=json.dumps([{
            "name": "NEPA Environmental Assessment",
            "jurisdiction": "Federal",
            "description": "Triggered by 40 CFR 1501.3.",
            "citation": "40 CFR \u00a71501.3",
        }]),
        input_tokens=123,
        output_tokens=45,
        model="claude-haiku-4-5-20251001",
    )
```

Add assertion at end of that test:
```python
    usage = out.get("_usage", {}).get("regulatory_screening")
    assert usage is not None
    assert usage["input_tokens"] == 123
    assert usage["output_tokens"] == 45
    assert usage["model"] == "claude-haiku-4-5-20251001"
```

In `test_agent_invalid_llm_json_returns_empty`, replace:
```python
    fake_llm.complete.return_value = "not valid json at all"
```
With:
```python
    fake_llm.complete.return_value = LLMResult(
        text="not valid json at all",
        input_tokens=50,
        output_tokens=10,
        model="mock-model",
    )
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && python -m pytest tests/test_regulatory_agent.py::test_agent_returns_regs_when_corpus_present -v`
Expected: FAIL — agent still treats `complete()` return as a string

- [ ] **Step 3: Update regulatory_screening.py**

In `backend/agents/regulatory_screening.py`, change the LLM call site in `run()`.

Replace (around line 137):
```python
        raw = self.llm.complete(prompt, system=_SYSTEM)
```
With:
```python
        llm_result = self.llm.complete(prompt, system=_SYSTEM)
        raw = llm_result.text
```

Replace (around line 138):
```python
        log("LLM returned in %.2fs (%d chars)", time.time() - t0, len(raw or ""))
        log("LLM raw response (first 2000 chars): %s", (raw or "")[:2000])
```
With:
```python
        log("LLM returned in %.2fs (%d chars)", time.time() - t0, len(raw or ""))
        log("LLM raw response (first 2000 chars): %s", (raw or "")[:2000])
        log("LLM tokens: input=%d output=%d model=%s",
            llm_result.input_tokens, llm_result.output_tokens, llm_result.model)
```

Add before `state["regulations"] = regs` (around line 148):
```python
        state.setdefault("_usage", {})["regulatory_screening"] = {
            "input_tokens": llm_result.input_tokens,
            "output_tokens": llm_result.output_tokens,
            "model": llm_result.model,
        }
```

Note: the `_usage` population goes after the LLM call but before the return. If the LLM call succeeds (even with bad JSON), we still capture the token usage.

- [ ] **Step 4: Run all regulatory tests**

Run: `cd backend && python -m pytest tests/test_regulatory_agent.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/agents/regulatory_screening.py backend/tests/test_regulatory_agent.py
git commit -m "feat(agents): regulatory_screening consumes LLMResult, populates _usage

Token usage now tracked via state['_usage']['regulatory_screening'].
Tests updated to provide LLMResult mocks."
```

---

### Task 7: Remove unused llm parameter from stub agents

**Files:**
- Modify: `backend/agents/environmental_data.py`
- Modify: `backend/agents/impact_analysis.py`
- Modify: `backend/agents/report_synthesis.py`

- [ ] **Step 1: Update environmental_data.py**

Remove `from llm.base import LLMProvider` import.

Replace constructor:
```python
class EnvironmentalDataAgent:
    """Queries all 5 federal REST APIs (USFWS, NWI, FEMA, Farmland, EJScreen)
    by project coordinates and returns raw geodata for downstream analysis."""

    def __init__(self):
        pass
```

The `run()` method is unchanged — it never referenced `self.llm`.

- [ ] **Step 2: Update impact_analysis.py**

Remove `from llm.base import LLMProvider` import.

Replace constructor and remove `self.llm` references in logging:
```python
class ImpactAnalysisAgent:
    """Reasons over collected geodata and regulatory context to populate a
    significance matrix across environmental impact categories (wetlands,
    endangered species, floodplains, farmland, environmental justice, etc.)."""

    def __init__(self):
        pass

    def run(self, state: dict) -> dict:
        logger.info("[ImpactAnalysis] Starting")
```

Replace the two lines that reference `self.llm.provider_name` (around lines 17 and 68):
```python
        # Line 17: was logger.info("... LLM provider: %s", self.llm.provider_name)
        # Line 68: was logger.info("... Invoking %s ...", self.llm.provider_name)
```
Change to:
```python
        logger.info("[ImpactAnalysis] Starting (stub — no LLM)")
        # ... (keep all the environmental data logging as-is)
        logger.warning("[ImpactAnalysis] STUB — LLM impact scoring not yet implemented; "
                       "impact_matrix set to []")
```

- [ ] **Step 3: Update report_synthesis.py**

Remove `from llm.base import LLMProvider` import.

Replace constructor:
```python
class ReportSynthesisAgent:
    """Generates the final screening-level EIA document from the significance
    matrix and identified regulations, producing a structured report suitable
    for regulatory submission."""

    def __init__(self):
        pass

    def run(self, state: dict) -> dict:
        logger.info("[ReportSynthesis] Starting (stub — no LLM)")
```

Replace the two lines referencing `self.llm.provider_name` (around lines 17 and 39):
```python
        # was: logger.info("... LLM provider: %s", self.llm.provider_name)
        # was: logger.info("... Invoking %s ...", self.llm.provider_name)
```
Change to remove the provider references but keep the structural logging.

- [ ] **Step 4: Run existing tests**

Run: `cd backend && python -m pytest tests/ -v --ignore=tests/test_regulatory_agent.py -k "not regulatory"`
Expected: PASS (no tests directly test these stubs)

- [ ] **Step 5: Commit**

```bash
git add backend/agents/environmental_data.py backend/agents/impact_analysis.py backend/agents/report_synthesis.py
git commit -m "refactor(agents): remove unused llm param from 3 non-LLM agents

environmental_data, impact_analysis, report_synthesis never called self.llm.
Removing the parameter makes it explicit they're non-LLM agents and prevents
the pipeline from needing to instantiate an LLM for them."
```

---

## Phase 2 — Pipeline Integration

### Task 8: Rewrite pipeline for per-agent model resolution and cost emission

**Files:**
- Modify: `backend/pipeline.py`

- [ ] **Step 1: Add imports and new constants at top of pipeline.py**

Add imports (after existing imports):
```python
from llm.provider_factory import get_llm_for_model, MissingAPIKeyError, UnknownModelError
from llm.pricing import cost_usd
```

Add constants after `AGENT_OUTPUT_KEYS`:
```python
DEFAULT_MODELS: dict[str, str] = {
    "project_parser":       "gemini-2.5-flash",
    "environmental_data":   "gemini-2.5-flash",   # not used (non-LLM agent)
    "regulatory_screening": "claude-haiku-4-5-20251001",
    "impact_analysis":      "gemini-2.5-flash",   # not used (stub)
    "report_synthesis":     "gemini-2.5-flash",   # not used (stub)
}

NON_LLM_AGENTS = frozenset({
    "environmental_data",
    "impact_analysis",
    "report_synthesis",
})
```

- [ ] **Step 2: Update `_make_agent_node` to accept resolved_llms dict**

Replace the current `_make_agent_node` function:
```python
def _make_agent_node(agent_key: str, agent_class, resolved_llms: dict, embedding_provider: LLMProvider):
    """Create a LangGraph node function wrapping an agent's .run() call."""
    if agent_key in NON_LLM_AGENTS:
        agent = agent_class()
    elif agent_key == "regulatory_screening":
        agent = agent_class(resolved_llms[agent_key], embedding_provider)
    else:
        agent = agent_class(resolved_llms[agent_key])

    def node_fn(state: EIAPipelineState) -> dict:
        logger.info("[GRAPH] Entering node: %s", agent_key)
        status = dict(state.get("pipeline_status", {}))
        status[agent_key] = "running"

        try:
            updated_state = agent.run(dict(state))
            status[agent_key] = "complete"
            logger.info("[GRAPH] Node %s \u2192 complete", agent_key)

            result = {"pipeline_status": status}
            for k, v in updated_state.items():
                if k != "pipeline_status" and (k not in state or state[k] != v):
                    result[k] = v
            return result

        except Exception as exc:
            logger.error("[GRAPH] Node %s \u2192 ERROR: %s", agent_key, exc, exc_info=True)
            status[agent_key] = "error"
            errors = dict(state.get("errors", {}))
            errors[agent_key] = str(exc)
            return {"pipeline_status": status, "errors": errors}

    return node_fn
```

- [ ] **Step 3: Update `build_pipeline` and `run_eia_pipeline` signatures**

Replace `build_pipeline`:
```python
def build_pipeline(resolved_llms: dict[str, LLMProvider], embedding_provider: LLMProvider):
    """Construct and compile the EIA LangGraph pipeline."""
    graph = StateGraph(EIAPipelineState)
    for agent_key, agent_class in AGENT_REGISTRY:
        graph.add_node(agent_key, _make_agent_node(agent_key, agent_class, resolved_llms, embedding_provider))
    prev = START
    for agent_key, _ in AGENT_REGISTRY:
        graph.add_edge(prev, agent_key)
        prev = agent_key
    graph.add_edge(prev, END)
    return graph.compile()
```

Replace `run_eia_pipeline`:
```python
def run_eia_pipeline(
    project_name: str,
    coordinates: str,
    description: str,
    models: dict[str, str],
    embedding_provider: LLMProvider,
) -> dict:
    resolved_llms = {}
    for agent_key, _ in AGENT_REGISTRY:
        if agent_key not in NON_LLM_AGENTS:
            model_id = models.get(agent_key) or DEFAULT_MODELS[agent_key]
            resolved_llms[agent_key] = get_llm_for_model(model_id)
    compiled = build_pipeline(resolved_llms, embedding_provider)
    initial_state: EIAPipelineState = {
        "project_name": project_name,
        "coordinates": coordinates,
        "description": description,
        "pipeline_status": {key: "pending" for key, _ in AGENT_REGISTRY},
        "parsed_project": {},
        "environmental_data": {},
        "regulations": [],
        "impact_matrix": [],
        "report": "",
        "errors": {},
    }
    final_state = compiled.invoke(initial_state)
    return {
        "project_name": final_state["project_name"],
        "coordinates": final_state["coordinates"],
        "description": final_state["description"],
        "pipeline_status": final_state["pipeline_status"],
        "impact_matrix": final_state.get("impact_matrix", []),
        "regulations": final_state.get("regulations", []),
    }
```

- [ ] **Step 4: Rewrite `stream_eia_pipeline` signature, add pre-flight and agent_cost emission**

Replace the full function signature:
```python
def stream_eia_pipeline(
    project_name: str,
    coordinates: str,
    description: str,
    models: dict[str, str],
    embedding_provider: LLMProvider,
):
```

Replace the print line at the top of the function:
```python
    print(
        f"[PIPELINE] stream_eia_pipeline entered \u2014 "
        f"project={project_name!r} models={models}",
        flush=True, file=sys.stderr,
    )
```

Add pre-flight validation after `_cancel_flag.clear()` and the log buffer setup, before the `try` block. Insert this right before `pipeline_status = {key: "pending" ...}`:

```python
    # Pre-flight: resolve all LLM agents upfront so we fail fast
    resolved_llms: dict[str, LLMProvider] = {}
    merged_models = {k: models.get(k) or DEFAULT_MODELS[k] for k, _ in AGENT_REGISTRY}
    try:
        for agent_key, _ in AGENT_REGISTRY:
            if agent_key not in NON_LLM_AGENTS:
                resolved_llms[agent_key] = get_llm_for_model(merged_models[agent_key])
    except (MissingAPIKeyError, UnknownModelError) as exc:
        logger.error("[PIPELINE] Pre-flight validation failed: %s", exc)
        yield _sse_event("pipeline_error", {
            "msg": str(exc),
            "type": type(exc).__name__,
        })
        eia_root.removeHandler(log_buffer)
        return
```

Inside the main loop, replace agent instantiation (currently lines 308-311):
```python
            if agent_key in NON_LLM_AGENTS:
                agent = agent_class()
            elif agent_key == "regulatory_screening":
                agent = agent_class(resolved_llms[agent_key], embedding_provider)
            else:
                agent = agent_class(resolved_llms[agent_key])
```

After the `yield _sse_event("agent_complete", ...)` (around line 370), add agent_cost emission:
```python
                # Emit agent_cost event
                usage = state.get("_usage", {}).get(agent_key, {})
                agent_model = merged_models[agent_key]
                agent_cost = cost_usd(
                    agent_model,
                    usage.get("input_tokens", 0),
                    usage.get("output_tokens", 0),
                )
                yield _sse_event("agent_cost", {
                    "agent": agent_key,
                    "model": agent_model,
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "cost_usd": agent_cost,
                })
```

In the `except` block (after `yield _sse_event("agent_error", ...)`), add zero-cost emission:
```python
                # Emit zero-cost event on error
                agent_model = merged_models[agent_key]
                yield _sse_event("agent_cost", {
                    "agent": agent_key,
                    "model": agent_model,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                })
```

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline.py
git commit -m "feat(pipeline): per-agent model resolution, pre-flight validation, agent_cost SSE

stream_eia_pipeline now accepts models dict instead of pre-built providers.
Pre-flight resolves all LLM agents upfront — fails fast on missing keys.
Emits agent_cost SSE event after each agent (zero for non-LLM agents).
DEFAULT_MODELS migrated from gemini-2.0-flash to gemini-2.5-flash."
```

---

### Task 9: Update main.py API layer

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add GET /api/providers endpoint and update RunRequest**

Add `Field` to the pydantic import:
```python
from pydantic import BaseModel, Field
```

Update `RunRequest`:
```python
class RunRequest(BaseModel):
    project_name: str
    coordinates: str
    description: str
    models: dict[str, str] = Field(default_factory=dict)
```

Add `/api/providers` endpoint (after the health endpoint):
```python
@app.get("/api/providers")
def get_providers():
    from llm.pricing import MODEL_PRICING, LAST_UPDATED, SOURCES
    from llm.provider_factory import available_providers
    return {
        "available": available_providers(),
        "models": [
            {"id": mid, "label": info["label"], "provider": info["provider"],
             "input": info["input"], "output": info["output"]}
            for mid, info in MODEL_PRICING.items()
        ],
        "pricing_last_updated": LAST_UPDATED,
        "pricing_sources": SOURCES,
    }
```

- [ ] **Step 2: Update lifespan — remove llm_provider and screening_llm singletons**

Replace the lifespan function. Key changes:
- Remove `llm = get_llm_provider()` — no longer needed at startup
- Remove `screening_llm` creation
- Remove `app.state.llm_provider` and `app.state.screening_llm`
- Keep `emb = get_embedding_provider()` and `app.state.embedding_provider`

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[LIFESPAN] Initialising embedding provider\u2026", flush=True, file=sys.stdout)
    try:
        init_db()
        try:
            _conn = _get_connection()
            init_regulatory_sources_table(_conn)
            _conn.close()
        except Exception as exc:
            print(f"[LIFESPAN] regulatory_sources init failed: {exc}",
                  flush=True, file=sys.stdout)
            raise
        emb = get_embedding_provider()
    except Exception as exc:
        print(f"[LIFESPAN] INIT FAILED: {exc}", flush=True, file=sys.stdout)
        raise
    logger.info("Embedding provider: %s", emb.provider_name)
    print(f"[LIFESPAN] Embedding={emb.provider_name}", flush=True, file=sys.stdout)

    app.state.embedding_provider = emb

    try:
        _conn = _get_connection()
        dim = detect_embedding_dimension(emb)
        init_regulatory_table(_conn, embedding_dim=dim)
        _conn.close()
        print(f"[LIFESPAN] regulatory_chunks table ready (dim={dim})",
              flush=True, file=sys.stdout)
    except Exception as exc:
        print(f"[LIFESPAN] regulatory_chunks init failed: {exc}",
              flush=True, file=sys.stdout)

    yield
```

Update the import line — remove `get_llm_provider` since it's no longer used at startup:
```python
from llm.provider_factory import get_embedding_provider
```

- [ ] **Step 3: Update /api/run handler to pass models dict**

```python
@app.post("/api/run")
def run_pipeline(req: RunRequest):
    return StreamingResponse(
        stream_eia_pipeline(
            project_name=req.project_name,
            coordinates=req.coordinates,
            description=req.description,
            models=req.models,
            embedding_provider=app.state.embedding_provider,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 4: Update /api/health — remove llm_provider reference**

```python
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "embedding_provider": app.state.embedding_provider.provider_name,
    }
```

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat(api): add /api/providers, accept models in /api/run, remove startup LLM singletons

GET /api/providers returns model catalog + which provider keys are available.
POST /api/run accepts optional models dict for per-agent model selection.
LLM providers are now instantiated per-request, not at startup."
```

---

### Task 10: Pipeline cost integration test

**Files:**
- Create: `backend/tests/test_pipeline_cost.py`

- [ ] **Step 1: Write the test file**

```python
# backend/tests/test_pipeline_cost.py
"""Integration tests for pipeline cost emission logic.

Uses fake agent classes to avoid real LLM/API calls while testing
the pipeline's cost-tracking SSE events end-to-end.
"""
import json
import sys
import os
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from llm.base import LLMResult


# ── Fake agents ──────────────────────────────────────────────────────────

class _FakeProjectParser:
    def __init__(self, llm):
        self.llm = llm

    def run(self, state):
        result = self.llm.complete("test")
        state["parsed_project"] = {"project_type": "test", "scale": "1MW", "location": "here"}
        state.setdefault("_usage", {})["project_parser"] = {
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "model": result.model,
        }
        return state


class _FakeEnvData:
    def __init__(self):
        pass

    def run(self, state):
        state["environmental_data"] = {"fema_flood_zones": {"in_sfha": False}}
        return state


class _FakeRegScreening:
    def __init__(self, llm, embedding_provider):
        self.llm = llm

    def run(self, state):
        result = self.llm.complete("test")
        state["regulations"] = []
        state.setdefault("_usage", {})["regulatory_screening"] = {
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "model": result.model,
        }
        return state


class _FakeImpact:
    def __init__(self):
        pass

    def run(self, state):
        state["impact_matrix"] = []
        return state


class _FakeReport:
    def __init__(self):
        pass

    def run(self, state):
        state["report"] = ""
        return state


# ── Helpers ──────────────────────────────────────────────────────────────

FAKE_REGISTRY = [
    ("project_parser", _FakeProjectParser),
    ("environmental_data", _FakeEnvData),
    ("regulatory_screening", _FakeRegScreening),
    ("impact_analysis", _FakeImpact),
    ("report_synthesis", _FakeReport),
]


def _parse_sse(raw_events: list[str]) -> list[tuple[str, dict]]:
    """Parse SSE event strings into (event_type, data) tuples."""
    result = []
    for event_str in raw_events:
        event_type = ""
        data_str = ""
        for line in event_str.strip().split("\n"):
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                data_str = line[6:]
        if data_str:
            try:
                result.append((event_type, json.loads(data_str)))
            except json.JSONDecodeError:
                pass
    return result


def _make_mock_llm(input_tokens=100, output_tokens=50, model="gemini-2.5-flash"):
    llm = MagicMock()
    llm.provider_name = "mock"
    llm.complete.return_value = LLMResult(
        text="test", input_tokens=input_tokens, output_tokens=output_tokens, model=model,
    )
    return llm


def _run_pipeline(models=None):
    """Run stream_eia_pipeline with FAKE_REGISTRY and return parsed SSE events."""
    mock_llm = _make_mock_llm()
    mock_embedder = MagicMock()
    mock_embedder.provider_name = "mock"

    with patch("pipeline.AGENT_REGISTRY", FAKE_REGISTRY), \
         patch("pipeline.get_llm_for_model", return_value=mock_llm):
        from pipeline import stream_eia_pipeline
        events = list(stream_eia_pipeline(
            project_name="Test",
            coordinates="40.0,-79.0",
            description="Test project",
            models=models or {},
            embedding_provider=mock_embedder,
        ))
    return _parse_sse(events)


# ── Tests ────────────────────────────────────────────────────────────────

def test_emits_one_agent_cost_per_agent():
    parsed = _run_pipeline()
    cost_events = [(t, d) for t, d in parsed if t == "agent_cost"]
    assert len(cost_events) == 5, f"Expected 5 agent_cost events, got {len(cost_events)}"


def test_llm_agents_have_nonzero_cost():
    parsed = _run_pipeline()
    cost_events = {d["agent"]: d for t, d in parsed if t == "agent_cost"}
    pp = cost_events["project_parser"]
    assert pp["input_tokens"] == 100
    assert pp["output_tokens"] == 50
    assert pp["cost_usd"] > 0


def test_non_llm_agents_have_zero_cost():
    parsed = _run_pipeline()
    cost_events = {d["agent"]: d for t, d in parsed if t == "agent_cost"}
    for agent in ("environmental_data", "impact_analysis", "report_synthesis"):
        assert cost_events[agent]["input_tokens"] == 0
        assert cost_events[agent]["output_tokens"] == 0
        assert cost_events[agent]["cost_usd"] == 0.0


def test_cost_after_complete():
    parsed = _run_pipeline()
    for agent_key in ("project_parser", "regulatory_screening"):
        complete_idx = next(
            i for i, (t, d) in enumerate(parsed)
            if t == "agent_complete" and d.get("agent") == agent_key
        )
        cost_idx = next(
            i for i, (t, d) in enumerate(parsed)
            if t == "agent_cost" and d.get("agent") == agent_key
        )
        assert cost_idx > complete_idx, \
            f"agent_cost must come after agent_complete for {agent_key}"


def test_missing_api_key_emits_pipeline_error():
    from llm.provider_factory import MissingAPIKeyError

    mock_embedder = MagicMock()
    mock_embedder.provider_name = "mock"

    def raise_missing(model_id):
        raise MissingAPIKeyError(f"KEY not set for {model_id}")

    with patch("pipeline.AGENT_REGISTRY", FAKE_REGISTRY), \
         patch("pipeline.get_llm_for_model", side_effect=raise_missing):
        from pipeline import stream_eia_pipeline
        events = list(stream_eia_pipeline(
            project_name="Test",
            coordinates="40.0,-79.0",
            description="Test",
            models={},
            embedding_provider=mock_embedder,
        ))

    parsed = _parse_sse(events)
    error_events = [(t, d) for t, d in parsed if t == "pipeline_error"]
    assert len(error_events) == 1
    assert "MissingAPIKeyError" in error_events[0][1]["type"]

    cost_events = [(t, d) for t, d in parsed if t == "agent_cost"]
    assert len(cost_events) == 0, "No agent_cost events when pre-flight fails"
```

- [ ] **Step 2: Run tests**

Run: `cd backend && python -m pytest tests/test_pipeline_cost.py -v`
Expected: All PASS (tests use fake agent classes and mock factory)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_pipeline_cost.py
git commit -m "test(pipeline): add integration tests for agent_cost SSE emission

Tests verify: one cost event per agent, LLM agents nonzero, non-LLM agents zero,
cost after complete ordering, pre-flight MissingAPIKeyError handling."
```

---

## Phase 3 — Frontend

### Task 11: Create useModelSelections hook with test

**Files:**
- Create: `frontend/src/hooks/useModelSelections.js`
- Create: `frontend/src/hooks/useModelSelections.test.js`

- [ ] **Step 1: Write the failing test**

```js
// frontend/src/hooks/useModelSelections.test.js
import { renderHook, act, waitFor } from '@testing-library/react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import useModelSelections, { DEFAULT_MODELS } from './useModelSelections.js'

const MOCK_PROVIDERS_RESPONSE = {
  available: { openai: true, anthropic: true, gemini: true },
  models: [
    { id: 'gpt-5.4', label: 'OpenAI \u00b7 GPT-5.4', provider: 'openai', input: 2.5, output: 15.0 },
    { id: 'gemini-2.5-flash', label: 'Gemini \u00b7 2.5 Flash', provider: 'gemini', input: 0.3, output: 2.5 },
    { id: 'claude-haiku-4-5-20251001', label: 'Claude \u00b7 Haiku 4.5', provider: 'anthropic', input: 1.0, output: 5.0 },
  ],
  pricing_last_updated: '2026-04-11',
}

beforeEach(() => {
  localStorage.clear()
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => MOCK_PROVIDERS_RESPONSE,
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('useModelSelections', () => {
  it('initializes with DEFAULT_MODELS when localStorage is empty', () => {
    const { result } = renderHook(() => useModelSelections())
    expect(result.current.selections).toEqual(DEFAULT_MODELS)
  })

  it('setSelection updates state and writes to localStorage', () => {
    const { result } = renderHook(() => useModelSelections())
    act(() => {
      result.current.setSelection('project_parser', 'gpt-5.4')
    })
    expect(result.current.selections.project_parser).toBe('gpt-5.4')
    const stored = JSON.parse(localStorage.getItem('eia.model_selections'))
    expect(stored.project_parser).toBe('gpt-5.4')
  })

  it('fetches /api/providers on mount', async () => {
    renderHook(() => useModelSelections())
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/providers')
      )
    })
  })

  it('replaces stale localStorage selections with defaults', async () => {
    localStorage.setItem(
      'eia.model_selections',
      JSON.stringify({ project_parser: 'stale-model-that-no-longer-exists' })
    )
    const { result } = renderHook(() => useModelSelections())
    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })
    // stale selection replaced with default
    expect(result.current.selections.project_parser).toBe(DEFAULT_MODELS.project_parser)
  })

  it('populates availableProviders after fetch', async () => {
    const { result } = renderHook(() => useModelSelections())
    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })
    expect(result.current.availableProviders.openai).toBe(true)
    expect(result.current.availableProviders.anthropic).toBe(true)
  })

  it('populates modelCatalog after fetch', async () => {
    const { result } = renderHook(() => useModelSelections())
    await waitFor(() => {
      expect(result.current.modelCatalog.length).toBeGreaterThan(0)
    })
    expect(result.current.modelCatalog[0].id).toBe('gpt-5.4')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/hooks/useModelSelections.test.js`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement the hook**

```js
// frontend/src/hooks/useModelSelections.js
import { useState, useEffect } from 'react'

const DEFAULT_MODELS = {
  project_parser: 'gemini-2.5-flash',
  environmental_data: 'gemini-2.5-flash',
  regulatory_screening: 'claude-haiku-4-5-20251001',
  impact_analysis: 'gemini-2.5-flash',
  report_synthesis: 'gemini-2.5-flash',
}

const STORAGE_KEY = 'eia.model_selections'

export default function useModelSelections() {
  const [selections, setSelections] = useState(() => {
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY))
      return { ...DEFAULT_MODELS, ...stored }
    } catch {
      return { ...DEFAULT_MODELS }
    }
  })
  const [availableProviders, setAvailableProviders] = useState({})
  const [modelCatalog, setModelCatalog] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const apiBase = import.meta.env.VITE_API_URL ?? ''
    fetch(`${apiBase}/api/providers`)
      .then((r) => r.json())
      .then((data) => {
        setAvailableProviders(data.available || {})
        setModelCatalog(data.models || [])
        // Validate stored selections against catalog
        const validIds = new Set((data.models || []).map((m) => m.id))
        setSelections((prev) => {
          const cleaned = { ...prev }
          for (const [agent, modelId] of Object.entries(cleaned)) {
            if (!validIds.has(modelId)) {
              cleaned[agent] = DEFAULT_MODELS[agent]
            }
          }
          localStorage.setItem(STORAGE_KEY, JSON.stringify(cleaned))
          return cleaned
        })
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const setSelection = (agentKey, modelId) => {
    setSelections((prev) => {
      const next = { ...prev, [agentKey]: modelId }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      return next
    })
  }

  return { selections, setSelection, availableProviders, modelCatalog, loading }
}

export { DEFAULT_MODELS }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/hooks/useModelSelections.test.js`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useModelSelections.js frontend/src/hooks/useModelSelections.test.js
git commit -m "feat(frontend): add useModelSelections hook with localStorage persistence

Fetches /api/providers on mount, validates stored selections against catalog,
falls back to DEFAULT_MODELS for stale or missing entries."
```

---

### Task 12: Create ModelDropdown component with test

**Files:**
- Create: `frontend/src/components/ModelDropdown.jsx`
- Create: `frontend/src/components/ModelDropdown.test.jsx`

- [ ] **Step 1: Write the failing test**

```jsx
// frontend/src/components/ModelDropdown.test.jsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import ModelDropdown, { NON_LLM_AGENTS } from './ModelDropdown.jsx'

const CATALOG = [
  { id: 'gpt-5.4', label: 'OpenAI \u00b7 GPT-5.4', provider: 'openai' },
  { id: 'gpt-5.4-mini', label: 'OpenAI \u00b7 GPT-5.4 mini', provider: 'openai' },
  { id: 'claude-haiku-4-5-20251001', label: 'Claude \u00b7 Haiku 4.5', provider: 'anthropic' },
  { id: 'gemini-2.5-flash', label: 'Gemini \u00b7 2.5 Flash', provider: 'gemini' },
]

const ALL_AVAILABLE = { openai: true, anthropic: true, gemini: true }
const PARTIAL_AVAILABLE = { openai: true, anthropic: false, gemini: true }

describe('ModelDropdown', () => {
  it('renders a <select> for LLM agents', () => {
    render(
      <ModelDropdown
        agentKey="project_parser"
        selections={{ project_parser: 'gemini-2.5-flash' }}
        setSelection={() => {}}
        availableProviders={ALL_AVAILABLE}
        modelCatalog={CATALOG}
      />
    )
    expect(screen.getByRole('combobox')).toBeInTheDocument()
  })

  it('renders "no LLM" pill for non-LLM agents', () => {
    for (const agent of NON_LLM_AGENTS) {
      const { container } = render(
        <ModelDropdown
          agentKey={agent}
          selections={{}}
          setSelection={() => {}}
          availableProviders={ALL_AVAILABLE}
          modelCatalog={CATALOG}
        />
      )
      expect(container.textContent).toContain('no LLM')
    }
  })

  it('renders options grouped by provider', () => {
    render(
      <ModelDropdown
        agentKey="project_parser"
        selections={{ project_parser: 'gemini-2.5-flash' }}
        setSelection={() => {}}
        availableProviders={ALL_AVAILABLE}
        modelCatalog={CATALOG}
      />
    )
    const options = screen.getAllByRole('option')
    expect(options.length).toBe(CATALOG.length)
  })

  it('disables options when provider unavailable', () => {
    render(
      <ModelDropdown
        agentKey="project_parser"
        selections={{ project_parser: 'gemini-2.5-flash' }}
        setSelection={() => {}}
        availableProviders={PARTIAL_AVAILABLE}
        modelCatalog={CATALOG}
      />
    )
    const haiku = screen.getByRole('option', { name: 'Claude \u00b7 Haiku 4.5' })
    expect(haiku).toBeDisabled()
  })

  it('calls setSelection on change', () => {
    const spy = vi.fn()
    render(
      <ModelDropdown
        agentKey="project_parser"
        selections={{ project_parser: 'gemini-2.5-flash' }}
        setSelection={spy}
        availableProviders={ALL_AVAILABLE}
        modelCatalog={CATALOG}
      />
    )
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'gpt-5.4' } })
    expect(spy).toHaveBeenCalledWith('project_parser', 'gpt-5.4')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/ModelDropdown.test.jsx`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement the component**

```jsx
// frontend/src/components/ModelDropdown.jsx

const NON_LLM_AGENTS = new Set([
  'environmental_data',
  'impact_analysis',
  'report_synthesis',
])

export { NON_LLM_AGENTS }

export default function ModelDropdown({
  agentKey,
  selections,
  setSelection,
  availableProviders,
  modelCatalog,
}) {
  if (NON_LLM_AGENTS.has(agentKey)) {
    return <span style={styles.noLlmPill}>no LLM</span>
  }

  const value = selections[agentKey] || ''

  // Group models by provider
  const grouped = {}
  for (const m of modelCatalog) {
    if (!grouped[m.provider]) grouped[m.provider] = []
    grouped[m.provider].push(m)
  }

  const providerLabels = {
    openai: 'OpenAI',
    anthropic: 'Claude',
    gemini: 'Gemini',
  }

  return (
    <select
      value={value}
      onChange={(e) => setSelection(agentKey, e.target.value)}
      style={styles.select}
    >
      {Object.entries(grouped).map(([provider, models]) => (
        <optgroup key={provider} label={providerLabels[provider] || provider}>
          {models.map((m) => (
            <option
              key={m.id}
              value={m.id}
              disabled={!availableProviders[m.provider]}
              title={
                !availableProviders[m.provider]
                  ? `${provider.toUpperCase()} API key not set on backend`
                  : undefined
              }
            >
              {m.label}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  )
}

const styles = {
  select: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-secondary)',
    background: 'var(--bg-primary)',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    padding: '2px 4px',
    maxWidth: '140px',
    cursor: 'pointer',
    outline: 'none',
  },
  noLlmPill: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    color: 'var(--text-muted)',
    padding: '2px 6px',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    opacity: 0.6,
  },
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/ModelDropdown.test.jsx`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ModelDropdown.jsx frontend/src/components/ModelDropdown.test.jsx
git commit -m "feat(frontend): add ModelDropdown component with provider grouping

Renders <select> grouped by provider for LLM agents.
Shows 'no LLM' pill for non-LLM agents.
Disables options when provider API key is unavailable."
```

---

### Task 13: Wire ModelDropdown and cost chips into AgentPipeline

**Files:**
- Modify: `frontend/src/components/AgentPipeline.jsx`
- Modify: `frontend/src/components/AgentPipeline.test.jsx`

- [ ] **Step 1: Extend the test file with new assertions**

Add to `frontend/src/components/AgentPipeline.test.jsx`:

```jsx
import ModelDropdown, { NON_LLM_AGENTS } from './ModelDropdown.jsx'

// Update baseProps to include new props
const extendedProps = {
  ...baseProps,
  selections: {
    project_parser: 'gemini-2.5-flash',
    environmental_data: 'gemini-2.5-flash',
    regulatory_screening: 'claude-haiku-4-5-20251001',
    impact_analysis: 'gemini-2.5-flash',
    report_synthesis: 'gemini-2.5-flash',
  },
  setSelection: vi.fn(),
  availableProviders: { openai: true, anthropic: true, gemini: true },
  modelCatalog: [
    { id: 'gemini-2.5-flash', label: 'Gemini \u00b7 2.5 Flash', provider: 'gemini' },
    { id: 'claude-haiku-4-5-20251001', label: 'Claude \u00b7 Haiku 4.5', provider: 'anthropic' },
  ],
  agentCosts: {},
}

describe('AgentPipeline model dropdowns', () => {
  it('renders select dropdowns for LLM agents', () => {
    render(<AgentPipeline {...extendedProps} />)
    const selects = screen.getAllByRole('combobox')
    // project_parser and regulatory_screening are LLM agents
    expect(selects.length).toBe(2)
  })

  it('renders "no LLM" pill for non-LLM agents', () => {
    const { container } = render(<AgentPipeline {...extendedProps} />)
    const pills = container.querySelectorAll('span')
    const noLlmPills = Array.from(pills).filter((s) => s.textContent === 'no LLM')
    expect(noLlmPills.length).toBe(3)
  })
})

describe('AgentPipeline cost chips', () => {
  it('shows \u2014 when no cost data', () => {
    const { container } = render(<AgentPipeline {...extendedProps} />)
    // All 5 rows should show \u2014 for cost
    const dashes = container.querySelectorAll('[data-testid="cost-chip"]')
    dashes.forEach((chip) => {
      expect(chip.textContent).toBe('\u2014')
    })
  })

  it('shows cost value when agentCosts has data', () => {
    const props = {
      ...extendedProps,
      agentCosts: {
        project_parser: { cost_usd: 0.0042 },
      },
    }
    const { container } = render(<AgentPipeline {...props} />)
    expect(container.textContent).toContain('$0.0042')
  })

  it('shows TOTAL in header', () => {
    const props = {
      ...extendedProps,
      agentCosts: {
        project_parser: { cost_usd: 0.003 },
        regulatory_screening: { cost_usd: 0.001 },
      },
    }
    render(<AgentPipeline {...props} />)
    expect(screen.getByText(/TOTAL/)).toBeInTheDocument()
    expect(screen.getByText('$0.0040')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/AgentPipeline.test.jsx`
Expected: FAIL (AgentPipeline doesn't accept new props yet)

- [ ] **Step 3: Update AgentPipeline.jsx**

Add import at top:
```jsx
import ModelDropdown, { NON_LLM_AGENTS } from './ModelDropdown.jsx'
```

Add `CostChip` helper component (before the main export):
```jsx
function CostChip({ cost }) {
  if (cost === undefined || cost === null || cost === 0) {
    return <span data-testid="cost-chip" style={{ ...styles.costChip, color: 'var(--text-muted)' }}>{'\u2014'}</span>
  }
  if (cost < 0.0001) {
    return <span data-testid="cost-chip" style={{ ...styles.costChip, color: 'var(--text-secondary)' }}>&lt;$0.0001</span>
  }
  const color = cost >= 1.0 ? 'var(--yellow-warn)' : 'var(--text-secondary)'
  const formatted = cost >= 1.0 ? `$${cost.toFixed(2)}` : `$${cost.toFixed(4)}`
  return <span data-testid="cost-chip" style={{ ...styles.costChip, color }}>{formatted}</span>
}
```

Update component signature:
```jsx
export default function AgentPipeline({
  pipelineState,
  agentOutputs = {},
  selections = {},
  setSelection,
  availableProviders = {},
  modelCatalog = [],
  agentCosts = {},
}) {
```

Add `TOTAL` chip in the header label div. Replace:
```jsx
      <div style={styles.label}>PIPELINE STATUS</div>
```
With:
```jsx
      <div style={styles.label}>
        <span>PIPELINE STATUS</span>
        <span style={styles.totalChip}>
          TOTAL{' '}
          <CostChip cost={Object.values(agentCosts).reduce((sum, c) => sum + (c?.cost_usd || 0), 0)} />
        </span>
      </div>
```

Inside each agent row (after the `<span style={getDotStyle(status)} />` and `<span style={styles.agentName}>{agent.name}</span>`), add ModelDropdown and CostChip:
```jsx
                <ModelDropdown
                  agentKey={agent.key}
                  selections={selections}
                  setSelection={setSelection || (() => {})}
                  availableProviders={availableProviders}
                  modelCatalog={modelCatalog}
                />
                <CostChip cost={agentCosts[agent.key]?.cost_usd} />
```

Add these styles to the `styles` object:
```js
  costChip: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    padding: '1px 4px',
    flexShrink: 0,
  },
  totalChip: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-secondary)',
    marginLeft: 'auto',
  },
```

Update the `label` style to be a flex row:
```js
  label: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--text-muted)',
    letterSpacing: '1.5px',
    marginBottom: '16px',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/AgentPipeline.test.jsx`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AgentPipeline.jsx frontend/src/components/AgentPipeline.test.jsx
git commit -m "feat(frontend): wire ModelDropdown and cost chips into AgentPipeline

Each row shows a model dropdown (or 'no LLM' pill) and a cost chip.
Header displays TOTAL cost summed across all agents.
Cost formatting: \u2014 for zero, $X.XXXX for sub-dollar, $X.XX for \u2265$1."
```

---

### Task 14: Wire hooks into App.jsx and update ProjectForm.jsx

**Files:**
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/components/ProjectForm.jsx`

- [ ] **Step 1: Update App.jsx**

Add import:
```jsx
import useModelSelections from './hooks/useModelSelections.js'
```

Add state and hook inside `function App()`, after existing state declarations:
```jsx
  const { selections, setSelection, availableProviders, modelCatalog } = useModelSelections()
  const [agentCosts, setAgentCosts] = useState({})

  const handleCostUpdate = (data) => {
    setAgentCosts((prev) => ({ ...prev, [data.agent]: data }))
  }
```

In `handleSubmit` or wherever the pipeline starts (look for where `onRunningChange?.(true)` is called in ProjectForm, but we reset costs in App via a callback). Add cost reset at the beginning of a new run. Since `ProjectForm` calls `onRunningChange(true)`, we can reset in `handleRunningChange`:

Replace:
```jsx
  const handleRunningChange = (isRunning) => {
    setRunning(isRunning)
  }
```
With:
```jsx
  const handleRunningChange = (isRunning) => {
    if (isRunning) setAgentCosts({})
    setRunning(isRunning)
  }
```

Remove the hardcoded Gemini badge. Replace:
```jsx
          <span style={styles.providerBadge}>Gemini</span>
```
With nothing (delete the line).

Pass new props to `ProjectForm`:
```jsx
            <ProjectForm
              onResult={handleResult}
              onPipelineUpdate={handlePipelineUpdate}
              onStepsUpdate={handleStepsUpdate}
              onLog={handleLog}
              onRunningChange={handleRunningChange}
              modelSelections={selections}
              onCostUpdate={handleCostUpdate}
            />
```

Pass new props to `AgentPipeline`:
```jsx
              <AgentPipeline
                pipelineState={pipelineState}
                agentOutputs={agentOutputs}
                selections={selections}
                setSelection={setSelection}
                availableProviders={availableProviders}
                modelCatalog={modelCatalog}
                agentCosts={agentCosts}
              />
```

Remove the `providerBadge` style from the `styles` object (it's no longer used).

- [ ] **Step 2: Update ProjectForm.jsx**

Update the component signature to accept new props:
```jsx
export default function ProjectForm({
  onResult,
  onPipelineUpdate,
  onStepsUpdate,
  onLog,
  onRunningChange,
  modelSelections,
  onCostUpdate,
}) {
```

In `handleSubmit`, update the POST body to include models. Replace:
```jsx
        body: JSON.stringify({
          project_name: projectName,
          coordinates,
          description,
        }),
```
With:
```jsx
        body: JSON.stringify({
          project_name: projectName,
          coordinates,
          description,
          models: modelSelections || {},
        }),
```

In `handleSSEEvent`, add the `agent_cost` case. After the `case 'agent_error':` block, add:
```jsx
      case 'agent_cost':
        onCostUpdate?.(data)
        break
```

- [ ] **Step 3: Run all frontend tests**

Run: `cd frontend && npx vitest run`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.jsx frontend/src/components/ProjectForm.jsx
git commit -m "feat(frontend): wire model selections and cost tracking through App

App.jsx mounts useModelSelections, passes props down to AgentPipeline and ProjectForm.
ProjectForm sends models in POST /api/run and handles agent_cost SSE events.
Removed hardcoded Gemini badge from header."
```

---

## Phase 4 — Verification

### Task 15: Manual verification checklist

No code changes — run through each scenario to verify the feature works end-to-end.

- [ ] **Step 1: Start backend and frontend locally**

```bash
# Terminal 1
cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 5050

# Terminal 2
cd frontend && npm run dev
```

- [ ] **Step 2: Fresh load verification**

Open `http://localhost:5173`. Verify:
- All five agent rows show a dropdown or "no LLM" pill
- `project_parser` defaults to `Gemini · 2.5 Flash`
- `regulatory_screening` defaults to `Claude · Haiku 4.5`
- Three non-LLM rows show `no LLM` pill
- No `Gemini` badge in the top-right header

- [ ] **Step 3: Selection persistence**

Change `regulatory_screening` dropdown to a different model. Reload the page. Verify the selection persists.

- [ ] **Step 4: Missing API key handling**

Stop the backend. Remove `CLAUDE_KEY` from env. Restart backend. Reload frontend. Verify all Claude options are greyed out with tooltip.

- [ ] **Step 5: Run the pipeline and verify cost chips**

Restore all API keys. Run the pipeline with a test project. Verify:
- `project_parser` and `regulatory_screening` rows show non-zero cost chips after completing
- `environmental_data`, `impact_analysis`, `report_synthesis` show `—`
- Header `TOTAL` equals the sum of the two non-zero costs

- [ ] **Step 6: Cancel mid-run**

Run the pipeline again. Press `/q` during `regulatory_screening`. Verify:
- `project_parser` cost chip is populated
- `regulatory_screening` chip stays `—`
- `TOTAL` equals only the `project_parser` cost

---

## File Summary

**New files (8):**
- `backend/llm/pricing.py`
- `backend/tests/test_pricing.py`
- `backend/tests/test_provider_factory.py`
- `backend/tests/test_pipeline_cost.py`
- `frontend/src/hooks/useModelSelections.js`
- `frontend/src/hooks/useModelSelections.test.js`
- `frontend/src/components/ModelDropdown.jsx`
- `frontend/src/components/ModelDropdown.test.jsx`

**Modified files (17):**
- `backend/llm/base.py`
- `backend/llm/openai_provider.py`
- `backend/llm/anthropic_provider.py`
- `backend/llm/gemini_provider.py`
- `backend/llm/ollama_provider.py`
- `backend/llm/provider_factory.py`
- `backend/agents/project_parser.py`
- `backend/agents/regulatory_screening.py`
- `backend/agents/environmental_data.py`
- `backend/agents/impact_analysis.py`
- `backend/agents/report_synthesis.py`
- `backend/pipeline.py`
- `backend/main.py`
- `backend/tests/test_project_parser.py`
- `backend/tests/test_regulatory_agent.py`
- `frontend/src/App.jsx`
- `frontend/src/components/ProjectForm.jsx`
- `frontend/src/components/AgentPipeline.jsx`
- `frontend/src/components/AgentPipeline.test.jsx`
