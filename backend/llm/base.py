from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the name of this provider (e.g. 'openai', 'anthropic', 'ollama')."""
        raise NotImplementedError("Subclasses must implement provider_name")

    @abstractmethod
    def complete(self, prompt: str, system: str = None) -> str:
        """Generate a completion for the given prompt."""
        raise NotImplementedError("Subclasses must implement complete()")

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Return an embedding vector for the given text."""
        raise NotImplementedError("Subclasses must implement embed()")

    @abstractmethod
    def chat(self, messages: list[dict]) -> str:
        """Generate a response given a list of chat messages."""
        raise NotImplementedError("Subclasses must implement chat()")
