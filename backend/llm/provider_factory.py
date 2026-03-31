import os

from .base import LLMProvider


def get_llm_provider() -> LLMProvider:
    """Resolve the LLM_PROVIDER env var to a concrete LLMProvider instance."""
    provider = os.environ.get("LLM_PROVIDER", "openai").lower()

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
    """Resolve the EMBEDDING_PROVIDER env var to a concrete LLMProvider instance.

    Note: Anthropic does not support embeddings. Use 'openai', 'gemini', or 'ollama'.
    """
    provider = os.environ.get("EMBEDDING_PROVIDER", "openai").lower()

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
