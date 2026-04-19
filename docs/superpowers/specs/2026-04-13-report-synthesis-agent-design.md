# Report Synthesis Agent — Design Spec

## Summary

The 5th and final agent in the EIA LangGraph pipeline. Consumes structured outputs from all 4 upstream agents and generates a NEPA Environmental Assessment document with per-section LLM narrative generation, inline confidence highlighting, and a structured disclaimer section.

## Constraints

- **No pipeline.py changes** — agent stays in `NON_LLM_AGENTS`, self-resolves its LLM via `get_llm_for_model()`
- **Sync only** — `def run(self, state)`, matching all other agents
- **Real upstream data shapes** — consumes `parsed_project`, `environmental_data`, `regulations`, `impact_matrix` as they exist today
- **`report` stays typed as `str` in `EIAPipelineState`** — we store a dict at runtime (TypedDict is not enforced); SSE serialization handles dicts fine

## Upstream Data Shapes (actual)

```python
# state["parsed_project"]
{"project_type": str, "scale": str, "location": str, "actions": [str]}

# state["environmental_data"]
{
    "query_location": {"lat": float, "lon": float},
    "usfws_species": {"count": int, "species": [{"name": str, ...}]},
    "nwi_wetlands": {"count": int, "wetlands": [{"type": str, ...}]},
    "fema_flood_zones": {"in_sfha": bool, "flood_zones": [{"flood_zone": str, ...}]},
    "usda_farmland": {"farmland_class": str, "is_prime": bool},
    "ejscreen": {"minority_pct": float, "low_income_pct": float, "percentile_pm25": float},
    "errors": {str: str}
}

# state["regulations"]
[{"name": str, "jurisdiction": str, "description": str, "citation": str}]

# state["impact_matrix"]
{
    "actions": [str],
    "categories": [str],
    "cells": [{
        "action": str, "category": str, "framework": str,
        "determination": {
            "significance": "significant"|"moderate"|"minimal"|"none",
            "confidence": float,
            "reasoning": str,
            "mitigation": [str],
            "needs_review": bool
        }
    }],
    "rag_fallbacks": []
}
```

## Output Schema

```python
state["report"] = {
    "reports": [{
        "framework_id": "NEPA",
        "document_type": "EA",
        "sections": [{
            "section_number": str,
            "section_title": str,
            "content": str,  # markdown
            "low_confidence_highlights": [{
                "text_excerpt": str,
                "confidence": float,
                "confidence_factors": {"data_completeness": float, "regulatory_clarity": float},
                "reasoning": str
            }],
            "requires_llm": bool
        }],
        "impact_matrix_table": {
            "actions": [str],
            "categories": [str],
            "cells": [{"action": str, "category": str, "significance": str, "confidence": float}]
        },
        "disclaimer_items": [{
            "category": str,
            "determination": str,
            "confidence": float,
            "reasoning": str
        }],
        "metadata": {
            "generated_at": str,
            "llm_model_used": str,
            "total_llm_calls": int,
            "total_tokens_used": int,
            "confidence_threshold": float,
            "low_confidence_count": int,
            "human_review_count": int
        }
    }],
    "stage": "complete"
}
```

## Section Plan (NEPA EA)

| # | Title | LLM? | Data source |
|---|-------|------|-------------|
| 1 | Title Page | No | `parsed_project`, `project_name`, `coordinates` |
| 2 | Purpose and Need | Yes | `parsed_project` (raw_description → description, project_type) |
| 3a | Proposed Action | Yes | `parsed_project` (actions, type, scale) |
| 3b | No-Action Alternative | Yes | `parsed_project` (project_type, location) |
| 4 | Affected Environment | Yes | `environmental_data` (all resource categories) |
| 5 | Environmental Consequences | Yes | `impact_matrix` cells grouped by category, `regulations` |
| 6 | Impact Matrix Table | No | `impact_matrix` (direct render) |
| 7 | Mitigation Measures | Yes | `impact_matrix` cells where mitigation is non-empty |
| 8 | Consultation and Coordination | No | `environmental_data` sources + errors |
| 9 | Confidence Disclaimer | No | `impact_matrix` cells where `needs_review` or confidence < 0.6 |
| 10 | Appendices | No | All upstream data (truncated summaries) |

6 LLM calls total (sections 2, 3a, 3b, 4, 5, 7).

## Architecture

### Files to create
- `backend/agents/report_synthesis.py` — main agent (rewrite stub)
- `backend/agents/templates/__init__.py` — TemplateRegistry + BaseTemplate
- `backend/agents/templates/nepa_ea.py` — NEPA EA template
- `backend/tests/test_report_synthesis.py` — unit tests

### Files NOT modified
- `backend/pipeline.py` — no changes

### LLM Resolution
Agent self-resolves via `get_llm_for_model("gemini-2.5-flash")` in `__init__`. Falls back gracefully if no API key — generates a report with "[LLM unavailable]" placeholders for narrative sections.

### Confidence Threshold
0.6, matching `CONFIDENCE_REVIEW_THRESHOLD` in impact_analysis.py.

### Template Registry
- `TemplateRegistry` maps `document_type` string to template class via `@register` decorator
- `BaseTemplate` defines interface: `sections`, `get_section_data()`, `get_section_prompt()`, `render_static_section()`
- `NepaEATemplate` implements all 10 sections
- Unimplemented document types return a stub report noting the template is not yet available

### LLM System Prompt
```
You are a technical writer generating sections of a NEPA Environmental Assessment.
Write in professional, concise environmental consulting language. Use passive voice
where conventional. Keep paragraphs short (3-5 sentences). Do not invent data —
only describe what is provided in the structured inputs.
```

Each section call passes only the data subset needed for that section.
