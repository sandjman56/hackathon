"""Project-agnostic scoring engine.

Computes three metrics against ground truth extracted from any EIS document:
  1. Category F1  — precision/recall over agent-designed categories only
  2. Significance accuracy — ordinal partial-credit comparison (off-by-1 = 0.5)
  3. Semantic coverage — cosine similarity of agent reasoning vs. EIS chunks

No project-specific assumptions. Works for any (project, evaluation_doc) pair.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from rag.evaluation.store import search_evaluation_chunks

logger = logging.getLogger("eia.rag_eval.scorer")

# Fixed set of categories the Impact Analysis Agent is designed to evaluate.
# F1 is computed ONLY over this set — FEIS categories outside this scope are
# intentionally not counted. Displayed as a scope note in the UI.
AGENT_CATEGORIES = frozenset([
    "wetlands",
    "air_quality",
    "noise",
    "traffic",
    "environmental_justice",
    "endangered_species",
    "floodplain",
    "prime_farmland",
])

AGENT_SCOPE_NOTE = (
    "F1 is computed over the 8 categories the Impact Analysis Agent is "
    "designed to evaluate. EIS resource categories outside this scope are "
    "not counted against the agent."
)

_SIGNIFICANCE_SCALE = {"significant": 3, "moderate": 2, "minimal": 1, "none": 0}
_SIGNIFICANCE_ORDER = ["significant", "moderate", "minimal", "none"]


def normalize_category(name: str) -> str:
    """Normalize a category name for fuzzy matching.

    Works on both agent snake_case names and narrative EIS names from any
    project document — no hardcoded project-specific strings.
    """
    name = name.lower()
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    stopwords = {
        "and", "or", "the", "of", "a", "an",
        "impact", "impacts", "resource", "resources",
        "environmental", "section", "assessment",
    }
    tokens = [t for t in name.split() if t not in stopwords]
    return " ".join(tokens)


def _build_gt_lookup(ground_truth: list[dict]) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for entry in ground_truth:
        norm = normalize_category(entry["category_name"])
        lookup[norm] = entry
    return lookup


def _match_agent_to_gt(agent_cat: str, gt_lookup: dict[str, dict]) -> dict | None:
    """Match an agent category name to the closest ground truth entry.

    1. Exact normalized match.
    2. Token-overlap match (any shared token).
    Returns None if no match is found.
    """
    agent_norm = normalize_category(agent_cat)
    if agent_norm in gt_lookup:
        return gt_lookup[agent_norm]

    agent_tokens = set(agent_norm.split())
    best_match: dict | None = None
    best_overlap = 0
    for gt_norm, entry in gt_lookup.items():
        gt_tokens = set(gt_norm.split())
        overlap = len(agent_tokens & gt_tokens)
        if overlap > best_overlap:
            best_overlap = overlap
            best_match = entry

    return best_match if best_overlap > 0 else None


def _agent_max_significance(category: str, cells: list[dict]) -> str:
    """Most severe significance the agent assigned to a category across all actions."""
    best_idx = len(_SIGNIFICANCE_ORDER) - 1  # starts at "none"
    for cell in cells:
        if cell.get("category") != category:
            continue
        sig = cell.get("determination", {}).get("significance", "none")
        try:
            idx = _SIGNIFICANCE_ORDER.index(sig)
            if idx < best_idx:
                best_idx = idx
        except ValueError:
            pass
    return _SIGNIFICANCE_ORDER[best_idx]


def compute_scores(
    impact_matrix: dict,
    ground_truth: list[dict],
    conn: Any,
    evaluation_id: int,
    emb_provider: Any,
) -> dict:
    """Compute all three scoring metrics.

    Parameters
    ----------
    impact_matrix:
        The ``impact_matrix`` dict from impact_analysis_outputs.output.
    ground_truth:
        List of category dicts from the extractor (any EIS document).
    conn:
        Live DB connection (read-only).
    evaluation_id:
        EIS document's evaluation_id (for semantic chunk search).
    emb_provider:
        Embedding provider (for semantic coverage metric).
    """
    gt_lookup = _build_gt_lookup(ground_truth)
    cells = impact_matrix.get("cells") or []

    # ── Metric 1: Category F1 ───────────────────────────────────────────────
    tp, fp, fn = [], [], []
    per_category: dict[str, dict] = {}

    for agent_cat in AGENT_CATEGORIES:
        gt_entry = _match_agent_to_gt(agent_cat, gt_lookup)
        gt_sig = gt_entry["significance"] if gt_entry else "none"
        gt_positive = gt_sig != "none"

        agent_sig = _agent_max_significance(agent_cat, cells)
        agent_positive = agent_sig != "none"

        if agent_positive and gt_positive:
            label = "TP"; tp.append(agent_cat)
        elif agent_positive and not gt_positive:
            label = "FP"; fp.append(agent_cat)
        elif not agent_positive and gt_positive:
            label = "FN"; fn.append(agent_cat)
        else:
            label = "TN"

        per_category[agent_cat] = {
            "label": label,
            "agent_significance": agent_sig,
            "gt_significance": gt_sig,
            "gt_matched_name": gt_entry["category_name"] if gt_entry else None,
            "gt_evidence": gt_entry.get("evidence", "") if gt_entry else "",
        }

    precision = len(tp) / (len(tp) + len(fp)) if (tp or fp) else 1.0
    recall = len(tp) / (len(tp) + len(fn)) if (tp or fn) else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    # ── Metric 2: Significance accuracy (ordinal, partial credit) ───────────
    sig_scores = []
    for info in per_category.values():
        if info["label"] in ("TP", "FP", "FN"):
            agent_val = _SIGNIFICANCE_SCALE.get(info["agent_significance"], 0)
            gt_val = _SIGNIFICANCE_SCALE.get(info["gt_significance"], 0)
            diff = abs(agent_val - gt_val)
            sig_scores.append(1.0 if diff == 0 else 0.5 if diff == 1 else 0.0)

    sig_accuracy = sum(sig_scores) / len(sig_scores) if sig_scores else 0.0

    # ── Metric 3: Semantic coverage ─────────────────────────────────────────
    sem_coverage = _compute_semantic_coverage(
        cells, conn, evaluation_id, emb_provider
    )

    # ── Overall weighted score ───────────────────────────────────────────────
    # Weights: F1=40%, sig=40%, semantic=20%
    overall = round(f1 * 0.4 + sig_accuracy * 0.4 + sem_coverage * 0.2, 4)

    return {
        "category_f1": round(f1, 4),
        "category_precision": round(precision, 4),
        "category_recall": round(recall, 4),
        "significance_accuracy": round(sig_accuracy, 4),
        "semantic_coverage": round(sem_coverage, 4),
        "overall_score": overall,
        "detail": {
            "per_category": per_category,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "significance_samples": len(sig_scores),
            "scope_note": AGENT_SCOPE_NOTE,
        },
    }


def _compute_semantic_coverage(
    cells: list[dict],
    conn: Any,
    evaluation_id: int,
    emb_provider: Any,
) -> float:
    """Average max cosine similarity of agent reasoning texts vs. EIS chunks."""
    reasoning_texts = [
        c["determination"]["reasoning"]
        for c in cells
        if c.get("determination", {}).get("reasoning")
    ]
    if not reasoning_texts:
        return 0.0

    sample = reasoning_texts[:10]
    sim_scores: list[float] = []

    for text in sample:
        try:
            emb = emb_provider.embed(text)
            results = search_evaluation_chunks(
                conn, emb, evaluation_id=evaluation_id, top_k=1
            )
            if results:
                sim_scores.append(float(results[0].get("similarity", 0.0)))
        except Exception as exc:
            logger.warning("[Scorer] Semantic coverage error: %s", exc)

    return round(sum(sim_scores) / len(sim_scores), 4) if sim_scores else 0.0
