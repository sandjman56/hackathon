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
