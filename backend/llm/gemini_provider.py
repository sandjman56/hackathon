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
        embedding_model = os.environ.get("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001")

        self._llm = ChatGoogleGenerativeAI(model=self._model, google_api_key=api_key)
        self._embeddings = GoogleGenerativeAIEmbeddings(
            model=embedding_model,
            google_api_key=api_key,
            output_dimensionality=1536,
        )

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
