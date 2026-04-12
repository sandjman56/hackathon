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
