import os

import anthropic

from .base import LLMProvider


class AnthropicProvider(LLMProvider):
    """LLM provider backed by the Anthropic Python SDK."""

    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is not set.")
        self._model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        self._client = anthropic.Anthropic(api_key=api_key)

    @property
    def provider_name(self) -> str:
        return "anthropic"

    def complete(self, prompt: str, system: str = None) -> str:
        kwargs = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        response = self._client.messages.create(**kwargs)
        return response.content[0].text

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
