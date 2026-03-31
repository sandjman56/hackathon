import logging

from backend.llm.provider_factory import get_embedding_provider
from backend.db.vector_store import get_vector_store

logger = logging.getLogger("eia.rag.retriever")


def retrieve(query: str, top_k: int = 5) -> list[str]:
    """Embed the query and retrieve top_k matching chunks from pgvector."""
    provider = get_embedding_provider()
    store = get_vector_store()

    query_embedding = provider.embed(query)

    results = store.query(
        query_embedding=query_embedding,
        similarity_top_k=top_k,
    )

    chunks = [node.text for node in results.nodes]
    logger.info(f"Retrieved {len(chunks)} chunks for query: {query[:80]}...")
    return chunks
