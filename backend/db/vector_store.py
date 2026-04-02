import os
import logging

import psycopg2
from llama_index.vector_stores.postgres import PGVectorStore

logger = logging.getLogger("eia.db")


def _get_connection():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError(
            "DATABASE_URL environment variable is not set. "
            "Please set it to your PostgreSQL connection string."
        )
    return psycopg2.connect(database_url)


def init_db():
    """Enable pgvector extension and create the documents table if needed."""
    try:
        conn = _get_connection()
        cur = conn.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id SERIAL PRIMARY KEY,
                content TEXT,
                metadata JSONB,
                embedding vector(1536)
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                coordinates TEXT NOT NULL,
                description TEXT,
                saved_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Database initialized: pgvector extension enabled, documents table ready")
    except psycopg2.OperationalError as e:
        logger.error(f"Failed to connect to database: {e}")
        raise
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        raise


def get_vector_store() -> PGVectorStore:
    """Return a LlamaIndex PGVectorStore connected to the documents table."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError(
            "DATABASE_URL environment variable is not set. "
            "Please set it to your PostgreSQL connection string."
        )

    return PGVectorStore.from_params(
        connection_string=database_url,
        table_name="documents",
        embed_dim=1536,
    )
