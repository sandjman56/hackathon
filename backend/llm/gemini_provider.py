import os

from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from .base import LLMProvider


class GeminiProvider(LLMProvider):
    """LLM provider backed by Google Gemini via langchain-google-genai."""

    def __init__(self):
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY environment variable is not set.")
        model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
        embedding_model = os.environ.get("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001")

        self._llm = ChatGoogleGenerativeAI(model=model, google_api_key=api_key)
        self._embeddings = GoogleGenerativeAIEmbeddings(
            model=embedding_model,
            google_api_key=api_key,
            output_dimensionality=1536,
        )

    @property
    def provider_name(self) -> str:
        return "gemini"

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
