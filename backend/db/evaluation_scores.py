"""DB schema and CRUD for evaluation scoring results and extracted ground truth."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import psycopg2
import psycopg2.extras

logger = logging.getLogger("eia.db.evaluation_scores")


def init_evaluation_scores_schema(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS evaluation_ground_truth (
                id SERIAL PRIMARY KEY,
                evaluation_id INTEGER NOT NULL
                    REFERENCES evaluations(id) ON DELETE CASCADE,
                extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                llm_model TEXT,
                categories JSONB NOT NULL,
                UNIQUE (evaluation_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS evaluation_scores (
                id SERIAL PRIMARY KEY,
                project_id INTEGER NOT NULL
                    REFERENCES projects(id) ON DELETE CASCADE,
                evaluation_id INTEGER
                    REFERENCES evaluations(id) ON DELETE SET NULL,
                scored_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                category_f1 NUMERIC(6,4),
                category_precision NUMERIC(6,4),
                category_recall NUMERIC(6,4),
                significance_accuracy NUMERIC(6,4),
                semantic_coverage NUMERIC(6,4),
                overall_score NUMERIC(6,4),
                detail JSONB NOT NULL DEFAULT '{}'
            )
        """)
        # Idempotent migration: make evaluation_id nullable, switch unique to project_id only.
        # Only drop NOT NULL if the column currently has it (safe across all PG versions).
        cur.execute("""
            SELECT is_nullable FROM information_schema.columns
            WHERE table_name = 'evaluation_scores' AND column_name = 'evaluation_id'
        """)
        col_info = cur.fetchone()
        if col_info and col_info[0] == 'NO':
            cur.execute("""
                ALTER TABLE evaluation_scores
                  ALTER COLUMN evaluation_id DROP NOT NULL
            """)
        cur.execute("""
            ALTER TABLE evaluation_scores
              DROP CONSTRAINT IF EXISTS evaluation_scores_project_id_evaluation_id_key
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS evaluation_scores_project_id_key
              ON evaluation_scores (project_id)
        """)
        # Idempotent migration: add run_id FK to pipeline_runs (nullable).
        cur.execute("""
            ALTER TABLE evaluation_scores
              ADD COLUMN IF NOT EXISTS run_id INTEGER
                REFERENCES pipeline_runs(id) ON DELETE SET NULL
        """)
    conn.commit()
    logger.info("evaluation_ground_truth + evaluation_scores tables ready")


def get_ground_truth(conn: Any, evaluation_id: int) -> Optional[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM evaluation_ground_truth WHERE evaluation_id = %s",
            (evaluation_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def upsert_ground_truth(
    conn: Any,
    evaluation_id: int,
    categories: list,
    llm_model: Optional[str] = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluation_ground_truth (evaluation_id, categories, llm_model)
            VALUES (%s, %s::jsonb, %s)
            ON CONFLICT (evaluation_id) DO UPDATE SET
                categories = EXCLUDED.categories,
                llm_model  = EXCLUDED.llm_model,
                extracted_at = NOW()
            """,
            (evaluation_id, json.dumps(categories), llm_model),
        )
    conn.commit()


def upsert_score(conn: Any, project_id: int, scores: dict) -> dict:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO evaluation_scores (
                project_id,
                category_f1, category_precision, category_recall,
                significance_accuracy, semantic_coverage, overall_score, detail
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (project_id) DO UPDATE SET
                category_f1          = EXCLUDED.category_f1,
                category_precision   = EXCLUDED.category_precision,
                category_recall      = EXCLUDED.category_recall,
                significance_accuracy = EXCLUDED.significance_accuracy,
                semantic_coverage    = EXCLUDED.semantic_coverage,
                overall_score        = EXCLUDED.overall_score,
                detail               = EXCLUDED.detail,
                scored_at            = NOW()
            RETURNING *
            """,
            (
                project_id,
                scores.get("category_f1"),
                scores.get("category_precision"),
                scores.get("category_recall"),
                scores.get("significance_accuracy"),
                scores.get("semantic_coverage"),
                scores.get("overall_score"),
                json.dumps(scores.get("detail", {})),
            ),
        )
        row = cur.fetchone()
    conn.commit()
    if row is None:
        raise RuntimeError("upsert_score: INSERT...RETURNING returned no row")
    result = dict(row)
    if result.get("scored_at"):
        result["scored_at"] = result["scored_at"].isoformat()
    for k in ("category_f1", "category_precision", "category_recall",
               "significance_accuracy", "semantic_coverage", "overall_score"):
        if result.get(k) is not None:
            result[k] = float(result[k])
    return result


def get_score(conn: Any, project_id: int) -> Optional[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM evaluation_scores WHERE project_id = %s",
            (project_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    result = dict(row)
    if result.get("scored_at"):
        result["scored_at"] = result["scored_at"].isoformat()
    for k in ("category_f1", "category_precision", "category_recall",
               "significance_accuracy", "semantic_coverage", "overall_score"):
        if result.get(k) is not None:
            result[k] = float(result[k])
    return result
