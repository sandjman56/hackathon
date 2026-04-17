"""Project-agnostic ground truth extractor.

Samples representative chunks from any stored EIS evaluation document,
calls an LLM once to extract structured impact findings, and returns
{category_name, significance, mitigation, evidence} per resource category.

No project-specific assumptions — works on any NEPA/EIS document.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import psycopg2.extras

from llm.base import LLMProvider

logger = logging.getLogger("eia.rag_eval.extractor")

_SYSTEM = """\
You are an expert environmental impact analyst. Given excerpts from an \
Environmental Impact Statement (EIS), extract ALL environmental resource \
categories that were evaluated and their impact significance determinations.

You MUST respond with ONLY a valid JSON array. No markdown, no explanation, \
no code fences — just the raw JSON array.

Each element must have exactly these fields:
{
  "category_name": "<normalized lowercase name, e.g. wetlands, air_quality, noise, environmental_justice>",
  "significance": "<significant | moderate | minimal | none>",
  "mitigation": ["<avoidance | minimization | compensatory>"],
  "evidence": "<one sentence quote or paraphrase from the text>"
}

Significance scale:
- "significant": Substantial, major, or unavoidable impacts; disproportionate \
adverse effects; major regulatory review triggered
- "moderate": Measurable impacts manageable with standard mitigation; minor \
permits required; temporary construction disruptions
- "minimal": Minor, localized, or short-term impacts; only routine best \
practices needed; net improvement possible
- "none": No adverse effect on this resource; net benefit; consistent with \
existing plans

Extract EVERY resource category you find significance language for. \
Return an empty array [] if no EIS content is found."""


def extract_ground_truth(
    conn: Any,
    evaluation_id: int,
    llm: LLMProvider,
    *,
    max_chunks: int = 40,
) -> tuple[list[dict], str]:
    """Return (categories_list, llm_model_name).

    Samples up to max_chunks chunks from the EIS, prioritising chunks from
    impact summary tables. Completely project-agnostic.
    """
    chunks = _sample_chunks(conn, evaluation_id, max_chunks=max_chunks)
    if not chunks:
        logger.warning(
            "[Extractor] No chunks for evaluation_id=%d", evaluation_id
        )
        return [], "none"

    prompt = _build_prompt(chunks)
    logger.info(
        "[Extractor] Sending %d chunks (%d chars) to LLM for evaluation_id=%d",
        len(chunks), len(prompt), evaluation_id,
    )

    result = llm.complete(prompt, system=_SYSTEM)
    categories = _parse_response(result.text)
    logger.info(
        "[Extractor] Extracted %d categories (model=%s input=%d output=%d)",
        len(categories), result.model,
        result.input_tokens, result.output_tokens,
    )
    return categories, result.model


def _sample_chunks(
    conn: Any, evaluation_id: int, max_chunks: int
) -> list[dict]:
    """Fetch chunks prioritising table/summary content over body text."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Priority 1: chunks that contain tables (impact summary tables)
        cur.execute(
            """
            SELECT content, breadcrumb, chunk_label
            FROM evaluation_chunks
            WHERE evaluation_id = %s
              AND (metadata->>'has_table')::boolean = true
            ORDER BY
                COALESCE((metadata->>'chapter')::int, 0),
                metadata->>'section_number',
                (metadata->>'chunk_index')::int
            LIMIT %s
            """,
            (evaluation_id, max(1, max_chunks // 2)),
        )
        table_rows = [dict(r) for r in cur.fetchall()]
        seen = {r["chunk_label"] for r in table_rows}

        remaining = max_chunks - len(table_rows)
        if remaining > 0:
            cur.execute(
                """
                SELECT content, breadcrumb, chunk_label
                FROM evaluation_chunks
                WHERE evaluation_id = %s
                ORDER BY
                    COALESCE((metadata->>'chapter')::int, 0),
                    metadata->>'section_number',
                    (metadata->>'chunk_index')::int
                LIMIT %s
                """,
                (evaluation_id, max_chunks * 4),
            )
            all_rows = [dict(r) for r in cur.fetchall()]
            extras = [r for r in all_rows if r["chunk_label"] not in seen][
                :remaining
            ]
            table_rows.extend(extras)

    return table_rows


def _build_prompt(chunks: list[dict]) -> str:
    parts = ["The following are excerpts from an Environmental Impact Statement:\n"]
    for c in chunks:
        content = (c.get("content") or "").strip()
        if content:
            parts.append(f"[{c.get('breadcrumb', '')}]\n{content}\n")
    return "\n".join(parts)


def _parse_response(raw: str) -> list[dict]:
    if not raw:
        return []
    clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        m = re.search(r"\[[\s\S]*\]", clean)
        if not m:
            logger.warning("[Extractor] No JSON array in LLM response")
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            logger.warning("[Extractor] Failed to parse JSON from LLM response")
            return []

    if not isinstance(data, list):
        return []

    valid = []
    for item in data:
        if not isinstance(item, dict):
            continue
        sig = str(item.get("significance", "none")).lower()
        if sig not in ("significant", "moderate", "minimal", "none"):
            sig = "none"
        mit = item.get("mitigation") or []
        if not isinstance(mit, list):
            mit = []
        mit = [m for m in mit if m in ("avoidance", "minimization", "compensatory")]
        valid.append({
            "category_name": str(item.get("category_name", "unknown")).lower().strip(),
            "significance": sig,
            "mitigation": mit,
            "evidence": str(item.get("evidence", "")),
        })

    return valid
