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
