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
