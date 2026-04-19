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
