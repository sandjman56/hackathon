import os

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from backend.llm.base import LLMProvider


class OpenAIProvider(LLMProvider):
    """LLM provider backed by OpenAI via langchain-openai."""

    def __init__(self):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set.")
        model = os.environ.get("OPENAI_MODEL", "gpt-4o")
        embedding_model = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

        self._llm = ChatOpenAI(model=model, api_key=api_key)
        self._embeddings = OpenAIEmbeddings(model=embedding_model, api_key=api_key)

    @property
    def provider_name(self) -> str:
        return "openai"

    def complete(self, prompt: str, system: str = None) -> str:
        messages = []
        if system:
            messages.append(("system", system))
        messages.append(("human", prompt))
        response = self._llm.invoke(messages)
        return response.content

    def embed(self, text: str) -> list[float]:
        return self._embeddings.embed_query(text)

    def chat(self, messages: list[dict]) -> str:
        langchain_messages = []
        for msg in messages:
            langchain_messages.append((msg["role"], msg["content"]))
        response = self._llm.invoke(langchain_messages)
        return response.content
