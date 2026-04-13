"""Report Synthesis Agent — final stage of the EIA pipeline.

Consumes structured outputs from the Project Parser, Environmental Data,
Regulatory Screening, and Impact Analysis agents to generate a NEPA
Environmental Assessment document with LLM-generated narrative sections,
inline confidence highlighting, and a structured disclaimer.
"""

import logging
import re
import time
import uuid
from datetime import datetime, timezone

from llm.base import LLMProvider, LLMResult

# Import templates — the nepa_ea module registers itself on import
from agents.templates import TemplateRegistry
import agents.templates.nepa_ea  # noqa: F401 — triggers @register

logger = logging.getLogger("eia.agents.report_synthesis")

CONFIDENCE_THRESHOLD = 0.6

_SYSTEM = """\
You are a technical writer generating sections of a NEPA Environmental \
Assessment document. Write in professional, concise environmental consulting \
language. Do not editorialize or add opinions. State findings factually based \
on the data provided. Use passive voice where conventional in EA documents \
(e.g., "Wetlands were identified within the project area" rather than "We \
found wetlands"). Keep paragraphs short (3-5 sentences). Do not invent data \
— only describe what is provided in the structured inputs. Return ONLY the \
section content as markdown. Do not include the section title or number.\
"""


class ReportSynthesisAgent:
    """Generates the final screening-level EIA document from upstream
    pipeline outputs, producing a structured report with per-section
    narrative, confidence highlighting, and disclaimer aggregation."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_llm_calls = 0
        self._model_used = ""

    def run(self, state: dict) -> dict:
        cid = uuid.uuid4().hex[:8]
        log = lambda msg, *a: logger.info(f"[ReportSynthesis:{cid}] " + msg, *a)
        warn = lambda msg, *a: logger.warning(f"[ReportSynthesis:{cid}] " + msg, *a)
        t0 = time.time()

        log("Starting report synthesis — provider: %s", self.llm.provider_name)

        # Reset per-run counters
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_llm_calls = 0

        # Select template — hardcoded to NEPA EA for v1
        try:
            template = TemplateRegistry.get_template("EA")
        except ValueError:
            warn("No EA template registered — returning empty report")
            state["report"] = self._empty_report("No template available")
            return state

        log("Template: %s (%d sections)", template.document_type,
            len(template.sections))

        # Generate each section
        sections = []
        all_low_confidence = []

        for section_def in template.sections:
            sid = section_def["id"]
            title = section_def["title"]
            requires_llm = section_def["requires_llm"]

            log("Section %s: %s (llm=%s)", sid, title, requires_llm)
            section_data = template.get_section_data(sid, state)

            if requires_llm:
                content = self._generate_narrative(
                    template, sid, section_data, log, warn
                )
            else:
                content = template.render_static_section(sid, section_data)

            # Extract low-confidence highlights for consequence sections
            highlights = []
            if sid == "5":
                highlights = self._extract_highlights(state)
                all_low_confidence.extend(highlights)

            sections.append({
                "section_number": sid,
                "section_title": title,
                "content": content,
                "low_confidence_highlights": highlights,
                "requires_llm": requires_llm,
            })

        # Build disclaimer items from impact matrix
        disclaimer_items = self._build_disclaimer_items(state)

        # Build impact matrix table structure for frontend
        matrix = state.get("impact_matrix") or {}
        impact_matrix_table = {
            "actions": matrix.get("actions", []),
            "categories": matrix.get("categories", []),
            "cells": [
                {
                    "action": c.get("action", ""),
                    "category": c.get("category", ""),
                    "significance": c.get("determination", {}).get("significance", ""),
                    "confidence": c.get("determination", {}).get("confidence", 0),
                }
                for c in matrix.get("cells", [])
            ],
        }

        # Metadata
        metadata = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "llm_model_used": self._model_used or "none",
            "total_llm_calls": self._total_llm_calls,
            "total_tokens_used": self._total_input_tokens + self._total_output_tokens,
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "low_confidence_count": len(all_low_confidence),
            "human_review_count": sum(
                1 for c in matrix.get("cells", [])
                if c.get("determination", {}).get("needs_review")
            ),
        }

        report = {
            "reports": [
                {
                    "framework_id": "NEPA",
                    "document_type": "EA",
                    "sections": sections,
                    "impact_matrix_table": impact_matrix_table,
                    "disclaimer_items": disclaimer_items,
                    "metadata": metadata,
                }
            ],
            "stage": "complete",
        }

        state["report"] = report

        # Track token usage for pipeline cost reporting
        state.setdefault("_usage", {})["report_synthesis"] = {
            "input_tokens": self._total_input_tokens,
            "output_tokens": self._total_output_tokens,
            "model": self._model_used or "none",
        }

        log("Report complete — %d sections, %d LLM calls, %d total tokens "
            "in %.1fs",
            len(sections), self._total_llm_calls,
            self._total_input_tokens + self._total_output_tokens,
            time.time() - t0)

        return state

    # ── Narrative generation ─────────────────────────────────────────────

    def _generate_narrative(self, template, section_id: str,
                            section_data: dict, log, warn) -> str:
        """Call LLM to generate narrative content for a single section."""
        prompt = template.get_section_prompt(section_id, section_data)
        if not prompt:
            return "*[No content to generate for this section]*"

        try:
            result: LLMResult = self.llm.complete(prompt, system=_SYSTEM)
            self._total_llm_calls += 1
            self._total_input_tokens += result.input_tokens
            self._total_output_tokens += result.output_tokens
            self._model_used = result.model

            log("Section %s LLM: %d in / %d out tokens",
                section_id, result.input_tokens, result.output_tokens)

            text = result.text.strip()
            # Strip markdown fences if the LLM wrapped its output
            text = re.sub(r"^```(?:markdown)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            return text

        except Exception as exc:
            warn("LLM call failed for section %s: %s", section_id, exc)
            return f"*[Error generating narrative: {exc}]*"

    # ── Confidence highlighting ──────────────────────────────────────────

    def _extract_highlights(self, state: dict) -> list[dict]:
        """Extract low-confidence items from impact matrix for inline
        highlighting in the Environmental Consequences section."""
        matrix = state.get("impact_matrix") or {}
        highlights = []
        for cell in matrix.get("cells", []):
            det = cell.get("determination", {})
            conf = det.get("confidence", 1.0)
            if conf < CONFIDENCE_THRESHOLD:
                highlights.append({
                    "text_excerpt": (
                        f"{cell.get('category', '?')} / "
                        f"{cell.get('action', '?')}: "
                        f"{det.get('significance', '?')}"
                    ),
                    "confidence": conf,
                    "confidence_factors": {
                        "data_completeness": conf,  # proxy — real factors not in upstream
                        "regulatory_clarity": min(conf + 0.1, 1.0),
                    },
                    "reasoning": det.get("reasoning", ""),
                })
        return highlights

    # ── Disclaimer building ──────────────────────────────────────────────

    def _build_disclaimer_items(self, state: dict) -> list[dict]:
        """Aggregate all cells needing human review into disclaimer items."""
        matrix = state.get("impact_matrix") or {}
        items = []
        for cell in matrix.get("cells", []):
            det = cell.get("determination", {})
            if det.get("needs_review") or det.get("confidence", 1.0) < CONFIDENCE_THRESHOLD:
                items.append({
                    "category": cell.get("category", ""),
                    "determination": det.get("significance", ""),
                    "confidence": det.get("confidence", 0),
                    "reasoning": det.get("reasoning", ""),
                })
        return items

    # ── Fallback ─────────────────────────────────────────────────────────

    def _empty_report(self, reason: str) -> dict:
        """Return a minimal report structure when generation can't proceed."""
        return {
            "reports": [],
            "stage": "error",
            "error": reason,
        }
