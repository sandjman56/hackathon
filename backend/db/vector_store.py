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
    """Enable pgvector extension and create core tables if needed.

    Also delegates to init_regulatory_sources_table() to ensure
    regulatory_sources and its Phase 1 eCFR columns are present before
    any callers attempt to use them.
    """
    # Import here to avoid circular imports; regulatory_sources imports
    # nothing from vector_store.
    from db.regulatory_sources import init_regulatory_sources_table

    conn = None
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id                  SERIAL PRIMARY KEY,
                project_id          INTEGER NOT NULL
                    REFERENCES projects(id) ON DELETE CASCADE,
                started_at          TIMESTAMPTZ,
                finished_at         TIMESTAMPTZ,
                total_duration_ms   INTEGER,
                total_cost_usd      NUMERIC(10,6),
                total_input_tokens  INTEGER,
                total_output_tokens INTEGER,
                saved_at            TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        # Agent output tables — one per pipeline agent
        for table_name in (
            "project_parser_outputs",
            "environmental_data_outputs",
            "regulatory_screening_outputs",
            "impact_analysis_outputs",
            "report_synthesis_outputs",
        ):
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id         SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    run_id     INTEGER REFERENCES pipeline_runs(id) ON DELETE SET NULL,
                    output     JSONB NOT NULL,
                    model      TEXT,
                    input_tokens  INTEGER,
                    output_tokens INTEGER,
                    cost_usd      NUMERIC(10,6),
                    duration_ms   INTEGER,
                    saved_at      TIMESTAMPTZ DEFAULT NOW()
                );
            """)

        # ── Idempotent migrations for existing installations ──────────────
        # Drop old UNIQUE(project_id) constraints (allow many runs per project)
        cur.execute(
            "ALTER TABLE pipeline_runs DROP CONSTRAINT IF EXISTS pipeline_runs_project_id_key"
        )
        for col in (
            "started_at TIMESTAMPTZ",
            "finished_at TIMESTAMPTZ",
            "total_duration_ms INTEGER",
            "total_cost_usd NUMERIC(10,6)",
            "total_input_tokens INTEGER",
            "total_output_tokens INTEGER",
        ):
            cur.execute(f"ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS {col}")

        for tbl in (
            "project_parser_outputs",
            "environmental_data_outputs",
            "regulatory_screening_outputs",
            "impact_analysis_outputs",
            "report_synthesis_outputs",
        ):
            cur.execute(
                f"ALTER TABLE {tbl} DROP CONSTRAINT IF EXISTS {tbl}_project_id_key"
            )
            cur.execute(
                f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS "
                f"run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE SET NULL"
            )
            cur.execute(
                f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS duration_ms INTEGER"
            )

        conn.commit()
        cur.close()

        # Create regulatory_sources (with Phase 1 eCFR columns) and the
        # regulatory_ingest_log audit table.  Uses the same connection so
        # everything is committed before we return.
        init_regulatory_sources_table(conn)

        logger.info(
            "Database initialized: pgvector extension enabled, "
            "documents + projects + regulatory tables ready"
        )
    except psycopg2.OperationalError as e:
        logger.error(f"Failed to connect to database: {e}")
        raise
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        raise
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


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
