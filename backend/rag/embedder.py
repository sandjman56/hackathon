import logging

from llama_index.core import SimpleDirectoryReader
from llama_index.core.node_parser import SentenceSplitter

from ..llm.provider_factory import get_embedding_provider
from ..db.vector_store import get_vector_store

logger = logging.getLogger("eia.rag.embedder")


def embed_documents(file_paths: list[str]):
    """Load documents from file paths, chunk them, embed, and store in pgvector."""
    provider = get_embedding_provider()
    store = get_vector_store()

    reader = SimpleDirectoryReader(input_files=file_paths)
    documents = reader.load_data()

    splitter = SentenceSplitter(chunk_size=512, chunk_overlap=50)
    nodes = splitter.get_nodes_from_documents(documents)

    logger.info(f"Embedding {len(nodes)} chunks from {len(file_paths)} document(s)")

    for i, node in enumerate(nodes):
        embedding = provider.embed(node.text)
        node.embedding = embedding
        logger.info(f"  Embedded chunk {i + 1}/{len(nodes)}")

    store.add(nodes)
    logger.info("All chunks stored in pgvector")
