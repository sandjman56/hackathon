# Impact Analysis Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire up the Impact Analysis agent as the computation layer that cross-references project actions against environmental resources using regulatory framework criteria, producing a 2D impact matrix with per-cell determinations, confidence scores, and mitigation flags.

**Architecture:** The agent receives structured outputs from three upstream agents (Project Parser, Environmental Data, Regulatory Screening) and produces an impact matrix where rows are environmental resource categories, columns are discrete project actions, and each cell contains a determination scoped to a specific regulatory framework. The agent uses an LLM (default: Gemini 2.5 Flash) for structured reasoning over pre-digested data — it does not perform RAG queries itself. A `rag_fallbacks` tracking field is defined in the schema but left empty for v1; frequent low-confidence determinations signal that the Regulatory Screening agent's output schema needs enrichment.

**Tech Stack:** Python, FastAPI pipeline (LangGraph), Gemini 2.5 Flash (default LLM), React frontend

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/pipeline.py` | Modify | Replace `ImpactRow` with new matrix types; update `EIAPipelineState`; remove `impact_analysis` from `NON_LLM_AGENTS`; update initial state shape |
| `backend/agents/project_parser.py` | Modify | Extend prompt to also extract a list of discrete project `actions`; update result normalization |
| `backend/agents/impact_analysis.py` | Rewrite | Full agent implementation: system prompt, prompt builder, LLM call, JSON parsing, confidence flagging, usage tracking |
| `backend/tests/test_impact_analysis.py` | Create | Unit tests for the Impact Analysis agent |
| `backend/tests/test_project_parser.py` | Modify | Add tests for the new `actions` field |
| `backend/tests/test_pipeline_cost.py` | Modify | Update `_FakeImpact` to match new schema and accept `llm` param |
| `frontend/src/components/ResultsPanel.jsx` | Modify | Render 2D matrix grid with confidence/mitigation indicators |

---

## Task 1: Extend Project Parser to extract project actions

The Impact Analysis agent needs discrete project actions as matrix columns. Currently `parsed_project` only has `project_type`, `scale`, and `location`. We add an `actions` list.

**Files:**
- Modify: `backend/agents/project_parser.py:15-27` (prompt template)
- Modify: `backend/agents/project_parser.py:62-66` (result normalization)
- Modify: `backend/tests/test_project_parser.py`

- [ ] **Step 1: Write failing tests for the `actions` field**

Add to `backend/tests/test_project_parser.py`:

```python
VALID_RESPONSE = json.dumps({
    "project_type": "solar farm",
    "scale": "50 MW",
    "location": "Pittsburgh, PA",
    "actions": [
        "site clearing and grading",
        "solar panel installation",
        "access road construction",
        "electrical interconnection",
    ],
})


class TestProjectParserActions(unittest.TestCase):
    def setUp(self):
        self.agent = ProjectParserAgent(make_llm(VALID_RESPONSE))
        self.result = self.agent.run(dict(BASE_STATE))

    def test_actions_key_present(self):
        self.assertIn("actions", self.result["parsed_project"])

    def test_actions_is_list(self):
        self.assertIsInstance(self.result["parsed_project"]["actions"], list)

    def test_actions_count(self):
        self.assertEqual(len(self.result["parsed_project"]["actions"]), 4)

    def test_actions_are_strings(self):
        for action in self.result["parsed_project"]["actions"]:
            self.assertIsInstance(action, str)

    def test_fallback_actions_when_missing(self):
        """LLM returns valid JSON but no actions key → defaults to empty list."""
        no_actions = json.dumps({"project_type": "pipeline", "scale": "10mi", "location": "PA"})
        agent = ProjectParserAgent(make_llm(no_actions))
        result = agent.run(dict(BASE_STATE))
        self.assertEqual(result["parsed_project"]["actions"], [])

    def test_fallback_actions_on_bad_json(self):
        """Total parse failure → fallback includes empty actions."""
        agent = ProjectParserAgent(make_llm("not json"))
        result = agent.run(dict(BASE_STATE))
        self.assertEqual(result["parsed_project"]["actions"], [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_project_parser.py::TestProjectParserActions -v`
Expected: FAIL — `actions` key not present in parsed_project

- [ ] **Step 3: Update prompt template and result normalization**

In `backend/agents/project_parser.py`, update `_PROMPT_TEMPLATE` to:

```python
_PROMPT_TEMPLATE = """\
Project name: {project_name}
Coordinates: {coordinates}
Description: {description}

Extract the following fields and return them as a JSON object:
- project_type  (string): the category of project, e.g. "solar farm", "highway expansion", "warehouse", "pipeline", etc.
- scale         (string): size or scope, e.g. "5 MW", "12 miles", "200,000 sq ft", "unknown"
- location      (string): human-readable place name inferred from the description or coordinates
- actions       (list of strings): discrete physical activities the project involves, e.g. ["site clearing and grading", "building construction", "utility trenching", "road paving"]. List 3-8 specific actions.

Return exactly this structure:
{{"project_type": "...", "scale": "...", "location": "...", "actions": ["...", "..."]}}
"""
```

Update the result normalization block (around line 62-66):

```python
            # Normalise to expected keys with safe defaults
            raw_actions = parsed.get("actions", [])
            if not isinstance(raw_actions, list):
                raw_actions = []
            result = {
                "project_type": str(parsed.get("project_type", "unknown")),
                "scale":        str(parsed.get("scale", "unknown")),
                "location":     str(parsed.get("location", coordinates or "unknown")),
                "actions":      [str(a) for a in raw_actions if a],
            }
```

Also update the fallback block (around line 71-75):

```python
            result = {
                "project_type": "unknown",
                "scale": "unknown",
                "location": coordinates or "unknown",
                "actions": [],
            }
```

- [ ] **Step 4: Update the existing `VALID_RESPONSE` constant**

The existing `VALID_RESPONSE` at module level needs to include `actions` so existing tests still pass with the new field:

```python
VALID_RESPONSE = json.dumps({
    "project_type": "solar farm",
    "scale": "50 MW",
    "location": "Pittsburgh, PA",
    "actions": [
        "site clearing and grading",
        "solar panel installation",
        "access road construction",
        "electrical interconnection",
    ],
})
```

- [ ] **Step 5: Run all Project Parser tests**

Run: `cd backend && python -m pytest tests/test_project_parser.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/agents/project_parser.py backend/tests/test_project_parser.py
git commit -m "feat(parser): extract discrete project actions for impact matrix columns"
```

---

## Task 2: Define new impact matrix schema in pipeline.py

Replace the flat `ImpactRow` with a rich 2D matrix schema. Update pipeline wiring to treat Impact Analysis as an LLM agent.

**Files:**
- Modify: `backend/pipeline.py:60-87` (type definitions)
- Modify: `backend/pipeline.py:118-122` (AGENT_STEPS)
- Modify: `backend/pipeline.py:146-158` (DEFAULT_MODELS, NON_LLM_AGENTS)
- Modify: `backend/pipeline.py:236-237,307,468` (initial state shape)

- [ ] **Step 1: Replace type definitions**

In `backend/pipeline.py`, replace the `ImpactRow` and `Regulation` TypedDicts (lines 60-69) with:

```python
# ── State schema ──────────────────────────────────────────────────────────────

class ImpactDetermination(TypedDict):
    significance: str   # "significant" | "moderate" | "minimal" | "none"
    confidence: float   # 0.0 – 1.0
    reasoning: str      # why this determination was made
    mitigation: list    # applicable: "avoidance", "minimization", "compensatory"
    needs_review: bool  # True when confidence < 0.6

class ImpactCell(TypedDict):
    action: str         # project action/component (column)
    category: str       # environmental resource category (row)
    framework: str      # regulatory framework governing this evaluation
    determination: ImpactDetermination

class RAGFallback(TypedDict):
    action: str
    category: str
    query: str
    reason: str

class ImpactMatrixOutput(TypedDict):
    actions: list       # distinct project actions (column headers)
    categories: list    # distinct resource categories (row headers)
    cells: list         # list of ImpactCell dicts
    rag_fallbacks: list # list of RAGFallback dicts (empty for v1)

class Regulation(TypedDict):
    name: str
    description: str
    jurisdiction: str
```

- [ ] **Step 2: Update `EIAPipelineState`**

Change the `impact_matrix` type annotation:

```python
class EIAPipelineState(TypedDict):
    # Input fields
    project_name: str
    coordinates: str
    description: str

    # Pipeline tracking
    pipeline_status: dict
    errors: dict

    # Agent outputs
    parsed_project: dict
    environmental_data: dict
    regulations: list[Regulation]
    impact_matrix: dict  # ImpactMatrixOutput
    report: str
```

- [ ] **Step 3: Remove `impact_analysis` from `NON_LLM_AGENTS`**

```python
NON_LLM_AGENTS = frozenset({
    "environmental_data",
    "report_synthesis",
})
```

Update `DEFAULT_MODELS` comment:

```python
DEFAULT_MODELS: dict[str, str] = {
    "project_parser":       "gemini-2.5-flash",
    "environmental_data":   "gemini-2.5-flash",   # not used (non-LLM agent)
    "regulatory_screening": "claude-haiku-4-5-20251001",
    "impact_analysis":      "gemini-2.5-flash",
    "report_synthesis":     "gemini-2.5-flash",   # not used (stub)
}
```

- [ ] **Step 4: Update initial state shapes**

In `run_eia_pipeline` (line 236) and `stream_eia_pipeline` (line 307), change:

```python
"impact_matrix": [],
```

to:

```python
"impact_matrix": {},
```

In `run_eia_pipeline` return (line 246) and `stream_eia_pipeline` result event (line 468), change:

```python
"impact_matrix": state.get("impact_matrix", []),
```

to:

```python
"impact_matrix": state.get("impact_matrix", {}),
```

- [ ] **Step 5: Update `AGENT_STEPS` for impact_analysis**

```python
"impact_analysis": [
    {"name": "build_context", "label": "Building impact context from upstream data"},
    {"name": "evaluate_determinations", "label": "Evaluating impact determinations (LLM)"},
    {"name": "validate_matrix", "label": "Validating matrix and flagging low confidence"},
],
```

- [ ] **Step 6: Run pipeline cost tests to verify no regressions (expect failures from fake agent shape)**

Run: `cd backend && python -m pytest tests/test_pipeline_cost.py -v`
Expected: Some failures because `_FakeImpact` still returns `[]` and has no `llm` param. This is expected — we fix it in Task 5.

- [ ] **Step 7: Commit**

```bash
git add backend/pipeline.py
git commit -m "feat(pipeline): replace ImpactRow with 2D matrix schema, wire impact_analysis as LLM agent"
```

---

## Task 3: Implement the Impact Analysis agent

The core of the plan. Replace the stub with a real LLM-backed agent that builds the 2D matrix.

**Files:**
- Rewrite: `backend/agents/impact_analysis.py`

- [ ] **Step 1: Write the complete agent**

Replace `backend/agents/impact_analysis.py` with:

```python
import json
import logging
import re

from llm.base import LLMProvider

logger = logging.getLogger("eia.agents.impact_analysis")

CONFIDENCE_REVIEW_THRESHOLD = 0.6

SIGNIFICANCE_LEVELS = ("significant", "moderate", "minimal", "none")

MITIGATION_CATEGORIES = ("avoidance", "minimization", "compensatory")

_SYSTEM = """\
You are an environmental impact analysis specialist. Your job is to evaluate \
how specific project actions affect environmental resource categories under \
applicable regulatory frameworks.

You MUST respond with ONLY a valid JSON object. No markdown, no explanation, \
no code fences — just the raw JSON.

The JSON object must have this structure:
{
  "cells": [
    {
      "action": "<project action>",
      "category": "<environmental resource category>",
      "framework": "<regulatory framework name>",
      "determination": {
        "significance": "<significant | moderate | minimal | none>",
        "confidence": <0.0 to 1.0>,
        "reasoning": "<1-2 sentences: what data supports this determination>",
        "mitigation": ["<avoidance | minimization | compensatory>"]
      }
    }
  ]
}

Significance scale:
- "significant": Direct, substantial, or irreversible impact that triggers \
major regulatory review or mitigation requirements.
- "moderate": Measurable impact that requires standard mitigation or minor \
permits but is manageable.
- "minimal": Detectable but minor impact requiring only routine best practices.
- "none": No meaningful impact from this action on this resource.

Confidence scoring rules:
- 0.85–1.0: Environmental data API returned specific quantified data AND the \
regulation description includes explicit thresholds.
- 0.65–0.84: Data available from APIs but regulatory threshold is a judgment \
call (no explicit numeric threshold in the regulation description).
- 0.45–0.64: Only partial data (some APIs errored or returned empty) or the \
regulation is tangentially related.
- 0.25–0.44: No direct data; determination relies on general domain knowledge \
about this project type.
- 0.0–0.24: Pure extrapolation; no supporting data or regulatory context.

Mitigation — include ONLY categories that genuinely apply:
- "avoidance": The impact could be avoided by project design changes.
- "minimization": The impact can be reduced through construction practices or \
operational controls.
- "compensatory": The impact must be offset (e.g., wetland mitigation banking, \
habitat conservation easements).

Rules:
- Evaluate EVERY combination of action × category × applicable framework.
- Skip combinations where a framework clearly does not govern a category \
(e.g., Clean Water Act does not govern air quality).
- If environmental data for a category is missing or errored, you may still \
evaluate but set confidence ≤ 0.4 and note the data gap in reasoning.
- Do NOT invent environmental data. Only reference data provided in the input.\
"""


class ImpactAnalysisAgent:
    """Cross-references project actions against environmental resources using
    regulatory framework criteria to produce a 2D impact matrix with per-cell
    determinations, confidence scores, and mitigation flags."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def run(self, state: dict) -> dict:
        logger.info("[ImpactAnalysis] Starting — provider: %s",
                    self.llm.provider_name)

        parsed = state.get("parsed_project") or {}
        env = state.get("environmental_data") or {}
        regs = state.get("regulations") or []

        actions = parsed.get("actions") or []
        if not actions:
            actions = self._infer_actions(parsed)
            logger.info("[ImpactAnalysis] No actions from parser; inferred: %s",
                        actions)

        categories = self._identify_categories(env)
        logger.info("[ImpactAnalysis] Actions (%d): %s", len(actions), actions)
        logger.info("[ImpactAnalysis] Categories (%d): %s",
                    len(categories), categories)
        logger.info("[ImpactAnalysis] Regulations (%d): %s",
                    len(regs), [r.get("name") for r in regs])

        prompt = self._build_prompt(parsed, env, regs, actions, categories)
        logger.info("[ImpactAnalysis] Prompt built: %d chars", len(prompt))

        llm_result = self.llm.complete(prompt, system=_SYSTEM)
        raw = llm_result.text
        logger.info("[ImpactAnalysis] LLM returned %d chars in model=%s "
                     "(input=%d output=%d)",
                     len(raw or ""), llm_result.model,
                     llm_result.input_tokens, llm_result.output_tokens)

        cells = self._parse_cells(raw)
        cells = self._flag_reviews(cells)

        logger.info("[ImpactAnalysis] Parsed %d cells", len(cells))
        review_count = sum(
            1 for c in cells
            if c.get("determination", {}).get("needs_review")
        )
        if review_count:
            logger.warning("[ImpactAnalysis] %d cells flagged for human review "
                           "(confidence < %.1f)",
                           review_count, CONFIDENCE_REVIEW_THRESHOLD)

        state.setdefault("_usage", {})["impact_analysis"] = {
            "input_tokens": llm_result.input_tokens,
            "output_tokens": llm_result.output_tokens,
            "model": llm_result.model,
        }

        state["impact_matrix"] = {
            "actions": actions,
            "categories": categories,
            "cells": cells,
            "rag_fallbacks": [],
        }

        logger.info("[ImpactAnalysis] Node complete — %d actions × %d categories "
                     "= %d cells", len(actions), len(categories), len(cells))
        return state

    # ── Helpers ────────────────────────────────────────────────────────────

    def _infer_actions(self, parsed: dict) -> list[str]:
        """Fallback: derive generic actions from project type if parser
        didn't extract them."""
        project_type = parsed.get("project_type", "unknown")
        return [
            f"{project_type} — site preparation",
            f"{project_type} — construction",
            f"{project_type} — operation",
        ]

    def _identify_categories(self, env: dict) -> list[str]:
        """Build the list of environmental resource categories based on
        which data sources have data."""
        categories = []
        if env.get("usfws_species"):
            categories.append("endangered_species")
        if env.get("nwi_wetlands"):
            categories.append("wetlands")
        if env.get("fema_flood_zones"):
            categories.append("floodplain")
        if env.get("usda_farmland"):
            categories.append("prime_farmland")
        if env.get("ejscreen"):
            categories.append("environmental_justice")
        # Always include these — LLM can reason about them from project type
        categories.extend(["air_quality", "noise", "traffic"])
        return categories

    def _build_prompt(self, parsed: dict, env: dict, regs: list,
                      actions: list, categories: list) -> str:
        env_summary = self._summarize_env(env)
        regs_text = self._format_regulations(regs)

        return f"""\
PROJECT:
  type: {parsed.get('project_type', 'unknown')}
  scale: {parsed.get('scale', 'unknown')}
  location: {parsed.get('location', 'unknown')}

PROJECT ACTIONS (evaluate each as a column):
{chr(10).join(f"  - {a}" for a in actions)}

ENVIRONMENTAL DATA (from federal APIs):
{env_summary}

APPLICABLE REGULATIONS (from regulatory screening):
{regs_text}

ENVIRONMENTAL CATEGORIES TO EVALUATE (rows):
{chr(10).join(f"  - {c}" for c in categories)}

For each (action × category × applicable framework) combination, produce a \
determination with significance, confidence, reasoning, and mitigation. \
Return JSON only."""

    def _summarize_env(self, env: dict) -> str:
        parts = []

        species = env.get("usfws_species", {})
        if species:
            names = [s.get("name", "?") for s in species.get("species", [])]
            parts.append(
                f"  Endangered species: {species.get('count', 0)} listed — "
                f"{', '.join(names[:5])}"
            )

        wetlands = env.get("nwi_wetlands", {})
        if wetlands:
            types = [w.get("type", "?") for w in wetlands.get("wetlands", [])]
            parts.append(
                f"  Wetlands: {wetlands.get('count', 0)} features — "
                f"{', '.join(types[:5])}"
            )

        fema = env.get("fema_flood_zones", {})
        if fema:
            zones = [z.get("flood_zone", "?")
                     for z in fema.get("flood_zones", [])]
            parts.append(
                f"  Flood zones: in_sfha={fema.get('in_sfha', False)} — "
                f"zones: {', '.join(zones) or 'none'}"
            )

        farmland = env.get("usda_farmland", {})
        if farmland:
            parts.append(
                f"  Farmland: class={farmland.get('farmland_class', '?')} "
                f"is_prime={farmland.get('is_prime', False)}"
            )

        ej = env.get("ejscreen", {})
        if ej:
            parts.append(
                f"  EJ Screen: minority_pct={ej.get('minority_pct', '?')} "
                f"low_income_pct={ej.get('low_income_pct', '?')} "
                f"pm25_pct={ej.get('percentile_pm25', '?')}"
            )

        errors = env.get("errors", {})
        if errors:
            parts.append(
                f"  DATA GAPS: {', '.join(errors.keys())} APIs returned errors"
            )

        return "\n".join(parts) if parts else "  No environmental data available"

    def _format_regulations(self, regs: list) -> str:
        if not regs:
            return "  No regulations identified by screening agent"
        lines = []
        for i, r in enumerate(regs, 1):
            lines.append(
                f"  [{i}] {r.get('name', '?')} ({r.get('jurisdiction', '?')})\n"
                f"      Citation: {r.get('citation', '?')}\n"
                f"      Why triggered: {r.get('description', '?')}"
            )
        return "\n".join(lines)

    def _parse_cells(self, raw: str) -> list[dict]:
        """Extract cells array from LLM JSON response."""
        if not raw:
            logger.warning("[ImpactAnalysis] Empty LLM response")
            return []

        # Strip markdown fences if present
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()

        # Try parsing as object with "cells" key first
        try:
            data = json.loads(clean)
        except json.JSONDecodeError:
            # Try to find JSON object in the output
            m = re.search(r"\{[\s\S]*\}", clean)
            if not m:
                logger.warning("[ImpactAnalysis] No JSON object found in response")
                return []
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                logger.warning("[ImpactAnalysis] Failed to parse extracted JSON")
                return []

        if isinstance(data, dict):
            cells_raw = data.get("cells", [])
        elif isinstance(data, list):
            cells_raw = data
        else:
            return []

        cells = []
        for item in cells_raw:
            if not isinstance(item, dict):
                continue
            det = item.get("determination") or {}
            sig = str(det.get("significance", "none")).lower()
            if sig not in SIGNIFICANCE_LEVELS:
                sig = "none"
            conf = det.get("confidence", 0.5)
            if not isinstance(conf, (int, float)):
                conf = 0.5
            conf = max(0.0, min(1.0, float(conf)))
            raw_mit = det.get("mitigation") or []
            if not isinstance(raw_mit, list):
                raw_mit = []
            mitigation = [
                str(m) for m in raw_mit
                if str(m).lower() in MITIGATION_CATEGORIES
            ]
            cells.append({
                "action": str(item.get("action", "")),
                "category": str(item.get("category", "")),
                "framework": str(item.get("framework", "")),
                "determination": {
                    "significance": sig,
                    "confidence": round(conf, 2),
                    "reasoning": str(det.get("reasoning", "")),
                    "mitigation": mitigation,
                    "needs_review": False,  # set in _flag_reviews
                },
            })
        return cells

    def _flag_reviews(self, cells: list[dict]) -> list[dict]:
        """Mark cells with confidence below threshold for human review."""
        for cell in cells:
            det = cell.get("determination", {})
            if det.get("confidence", 0) < CONFIDENCE_REVIEW_THRESHOLD:
                det["needs_review"] = True
        return cells
```

- [ ] **Step 2: Verify the agent file is syntactically valid**

Run: `cd backend && python -c "from agents.impact_analysis import ImpactAnalysisAgent; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/agents/impact_analysis.py
git commit -m "feat(impact): implement LLM-backed impact analysis with 2D matrix output"
```

---

## Task 4: Unit tests for the Impact Analysis agent

Follow the same pattern as `test_project_parser.py` — mock the LLM, test parsing/validation/fallback.

**Files:**
- Create: `backend/tests/test_impact_analysis.py`

- [ ] **Step 1: Write the test file**

Create `backend/tests/test_impact_analysis.py`:

```python
"""Unit tests for ImpactAnalysisAgent."""
import json
import sys
import os
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.impact_analysis import (
    ImpactAnalysisAgent,
    CONFIDENCE_REVIEW_THRESHOLD,
    SIGNIFICANCE_LEVELS,
)
from llm.base import LLMResult


def make_llm(response: str) -> MagicMock:
    llm = MagicMock()
    llm.provider_name = "mock"
    llm.complete.return_value = LLMResult(
        text=response,
        input_tokens=200,
        output_tokens=150,
        model="mock-model",
    )
    return llm


SAMPLE_STATE = {
    "parsed_project": {
        "project_type": "solar farm",
        "scale": "50 MW",
        "location": "Pittsburgh, PA",
        "actions": ["site clearing", "panel installation"],
    },
    "environmental_data": {
        "usfws_species": {
            "count": 2,
            "species": [
                {"name": "Indiana Bat", "status": "Endangered"},
                {"name": "Northern Long-eared Bat", "status": "Threatened"},
            ],
        },
        "nwi_wetlands": {"count": 1, "wetlands": [{"type": "Freshwater Pond"}]},
        "fema_flood_zones": {"in_sfha": False, "flood_zones": []},
        "usda_farmland": {"farmland_class": "Prime", "is_prime": True},
        "ejscreen": {"minority_pct": 0.2, "low_income_pct": 0.15},
    },
    "regulations": [
        {
            "name": "ESA Section 7 Consultation",
            "jurisdiction": "Federal",
            "description": "T&E species present",
            "citation": "50 CFR §402",
        },
    ],
}

VALID_LLM_RESPONSE = json.dumps({
    "cells": [
        {
            "action": "site clearing",
            "category": "endangered_species",
            "framework": "ESA Section 7 Consultation",
            "determination": {
                "significance": "significant",
                "confidence": 0.9,
                "reasoning": "2 listed bat species; habitat disturbance likely.",
                "mitigation": ["avoidance", "minimization"],
            },
        },
        {
            "action": "panel installation",
            "category": "wetlands",
            "framework": "ESA Section 7 Consultation",
            "determination": {
                "significance": "minimal",
                "confidence": 0.4,
                "reasoning": "1 wetland feature nearby but no direct fill expected.",
                "mitigation": [],
            },
        },
    ]
})


class TestImpactAnalysisHappyPath(unittest.TestCase):
    def setUp(self):
        self.agent = ImpactAnalysisAgent(make_llm(VALID_LLM_RESPONSE))
        self.result = self.agent.run(dict(SAMPLE_STATE))
        self.matrix = self.result["impact_matrix"]

    def test_impact_matrix_key_present(self):
        self.assertIn("impact_matrix", self.result)

    def test_matrix_has_actions(self):
        self.assertEqual(self.matrix["actions"],
                         ["site clearing", "panel installation"])

    def test_matrix_has_categories(self):
        cats = self.matrix["categories"]
        self.assertIn("endangered_species", cats)
        self.assertIn("wetlands", cats)

    def test_cells_count(self):
        self.assertEqual(len(self.matrix["cells"]), 2)

    def test_cell_structure(self):
        cell = self.matrix["cells"][0]
        self.assertIn("action", cell)
        self.assertIn("category", cell)
        self.assertIn("framework", cell)
        self.assertIn("determination", cell)

    def test_determination_fields(self):
        det = self.matrix["cells"][0]["determination"]
        self.assertIn("significance", det)
        self.assertIn("confidence", det)
        self.assertIn("reasoning", det)
        self.assertIn("mitigation", det)
        self.assertIn("needs_review", det)

    def test_significance_value(self):
        det = self.matrix["cells"][0]["determination"]
        self.assertEqual(det["significance"], "significant")

    def test_confidence_value(self):
        det = self.matrix["cells"][0]["determination"]
        self.assertEqual(det["confidence"], 0.9)

    def test_rag_fallbacks_empty(self):
        self.assertEqual(self.matrix["rag_fallbacks"], [])

    def test_usage_tracked(self):
        usage = self.result.get("_usage", {}).get("impact_analysis")
        self.assertIsNotNone(usage)
        self.assertEqual(usage["input_tokens"], 200)
        self.assertEqual(usage["output_tokens"], 150)
        self.assertEqual(usage["model"], "mock-model")


class TestImpactAnalysisReviewFlagging(unittest.TestCase):
    def test_low_confidence_flagged(self):
        """Cell with confidence < threshold gets needs_review=True."""
        agent = ImpactAnalysisAgent(make_llm(VALID_LLM_RESPONSE))
        result = agent.run(dict(SAMPLE_STATE))
        low_conf_cell = result["impact_matrix"]["cells"][1]
        self.assertTrue(low_conf_cell["determination"]["needs_review"])

    def test_high_confidence_not_flagged(self):
        agent = ImpactAnalysisAgent(make_llm(VALID_LLM_RESPONSE))
        result = agent.run(dict(SAMPLE_STATE))
        high_conf_cell = result["impact_matrix"]["cells"][0]
        self.assertFalse(high_conf_cell["determination"]["needs_review"])


class TestImpactAnalysisFallback(unittest.TestCase):
    def test_empty_response(self):
        agent = ImpactAnalysisAgent(make_llm(""))
        result = agent.run(dict(SAMPLE_STATE))
        self.assertEqual(result["impact_matrix"]["cells"], [])

    def test_garbage_response(self):
        agent = ImpactAnalysisAgent(make_llm("I cannot help with that."))
        result = agent.run(dict(SAMPLE_STATE))
        self.assertEqual(result["impact_matrix"]["cells"], [])

    def test_markdown_fenced_json(self):
        fenced = f"```json\n{VALID_LLM_RESPONSE}\n```"
        agent = ImpactAnalysisAgent(make_llm(fenced))
        result = agent.run(dict(SAMPLE_STATE))
        self.assertEqual(len(result["impact_matrix"]["cells"]), 2)


class TestImpactAnalysisValidation(unittest.TestCase):
    def test_invalid_significance_defaults_to_none(self):
        bad = json.dumps({"cells": [{
            "action": "a", "category": "c", "framework": "f",
            "determination": {"significance": "EXTREME", "confidence": 0.5,
                              "reasoning": "x", "mitigation": []},
        }]})
        agent = ImpactAnalysisAgent(make_llm(bad))
        result = agent.run(dict(SAMPLE_STATE))
        self.assertEqual(
            result["impact_matrix"]["cells"][0]["determination"]["significance"],
            "none",
        )

    def test_confidence_clamped_to_range(self):
        bad = json.dumps({"cells": [{
            "action": "a", "category": "c", "framework": "f",
            "determination": {"significance": "moderate", "confidence": 1.5,
                              "reasoning": "x", "mitigation": []},
        }]})
        agent = ImpactAnalysisAgent(make_llm(bad))
        result = agent.run(dict(SAMPLE_STATE))
        self.assertLessEqual(
            result["impact_matrix"]["cells"][0]["determination"]["confidence"],
            1.0,
        )

    def test_invalid_mitigation_filtered(self):
        bad = json.dumps({"cells": [{
            "action": "a", "category": "c", "framework": "f",
            "determination": {"significance": "moderate", "confidence": 0.8,
                              "reasoning": "x",
                              "mitigation": ["avoidance", "magic", "compensation"]},
        }]})
        agent = ImpactAnalysisAgent(make_llm(bad))
        result = agent.run(dict(SAMPLE_STATE))
        mit = result["impact_matrix"]["cells"][0]["determination"]["mitigation"]
        self.assertEqual(mit, ["avoidance"])


class TestImpactAnalysisNoActions(unittest.TestCase):
    def test_infers_actions_from_project_type(self):
        state = dict(SAMPLE_STATE)
        state["parsed_project"] = {
            "project_type": "pipeline",
            "scale": "10mi",
            "location": "PA",
        }
        agent = ImpactAnalysisAgent(make_llm(VALID_LLM_RESPONSE))
        result = agent.run(state)
        actions = result["impact_matrix"]["actions"]
        self.assertEqual(len(actions), 3)
        self.assertTrue(all("pipeline" in a for a in actions))


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run the tests**

Run: `cd backend && python -m pytest tests/test_impact_analysis.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_impact_analysis.py
git commit -m "test(impact): unit tests for impact analysis agent"
```

---

## Task 5: Update pipeline cost tests

The `_FakeImpact` class needs to accept an `llm` param and return the new matrix shape.

**Files:**
- Modify: `backend/tests/test_pipeline_cost.py:67-73`

- [ ] **Step 1: Update `_FakeImpact` class**

Replace the existing `_FakeImpact` in `backend/tests/test_pipeline_cost.py`:

```python
class _FakeImpact:
    def __init__(self, llm):
        self.llm = llm

    def run(self, state):
        result = self.llm.complete("test")
        state["impact_matrix"] = {
            "actions": [],
            "categories": [],
            "cells": [],
            "rag_fallbacks": [],
        }
        state.setdefault("_usage", {})["impact_analysis"] = {
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "model": result.model,
        }
        return state
```

- [ ] **Step 2: Update `test_non_llm_agents_have_zero_cost`**

Since `impact_analysis` is now an LLM agent, remove it from the zero-cost assertion. Replace the test:

```python
def test_non_llm_agents_have_zero_cost():
    parsed = _run_pipeline()
    cost_events = {d["agent"]: d for t, d in parsed if t == "agent_cost"}
    for agent in ("environmental_data", "report_synthesis"):
        assert cost_events[agent]["input_tokens"] == 0
        assert cost_events[agent]["output_tokens"] == 0
        assert cost_events[agent]["cost_usd"] == 0.0
```

- [ ] **Step 3: Add `impact_analysis` to the nonzero cost test or add a new test**

Add a new test to verify impact_analysis now tracks cost:

```python
def test_impact_analysis_has_nonzero_cost():
    parsed = _run_pipeline()
    cost_events = {d["agent"]: d for t, d in parsed if t == "agent_cost"}
    ia = cost_events["impact_analysis"]
    assert ia["input_tokens"] == 100
    assert ia["output_tokens"] == 50
    assert ia["cost_usd"] > 0
```

- [ ] **Step 4: Run all pipeline cost tests**

Run: `cd backend && python -m pytest tests/test_pipeline_cost.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_pipeline_cost.py
git commit -m "test(pipeline): update fake impact agent for new schema and LLM wiring"
```

---

## Task 6: Update frontend ResultsPanel for 2D matrix

Replace the flat table with a proper grid: categories as rows, actions as columns, cells showing significance + confidence.

**Files:**
- Modify: `frontend/src/components/ResultsPanel.jsx`

- [ ] **Step 1: Update the IMPACT MATRIX tab rendering**

In `frontend/src/components/ResultsPanel.jsx`, replace the `activeTab === 0` block (lines 55-92) and update the data extraction (line 30):

Change line 30 from:
```jsx
const impactMatrix = results.impact_matrix || []
```
to:
```jsx
const impactMatrix = results.impact_matrix || {}
const matrixCells = impactMatrix.cells || []
const matrixActions = impactMatrix.actions || []
const matrixCategories = impactMatrix.categories || []
```

Replace the `activeTab === 0` block with:

```jsx
{activeTab === 0 && (
  <div style={styles.tableWrap}>
    {matrixCells.length === 0 ? (
      <p style={styles.noData}>No impact data available</p>
    ) : (
      <table style={styles.table}>
        <thead>
          <tr>
            <th style={styles.th}>Category</th>
            {matrixActions.map((action, i) => (
              <th key={i} style={{...styles.th, minWidth: '140px'}}>
                {action}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrixCategories.map((cat, ri) => (
            <tr
              key={cat}
              style={{
                background: ri % 2 === 0 ? '#161616' : '#111111',
              }}
            >
              <td style={{...styles.td, fontWeight: 600, whiteSpace: 'nowrap'}}>
                {cat.replace(/_/g, ' ')}
              </td>
              {matrixActions.map((action, ci) => {
                const cell = matrixCells.find(
                  c => c.category === cat && c.action === action
                )
                if (!cell) {
                  return (
                    <td key={ci} style={{...styles.td, color: 'var(--text-muted)'}}>
                      —
                    </td>
                  )
                }
                const det = cell.determination || {}
                return (
                  <td key={ci} style={styles.td}>
                    <div style={{
                      color: significanceColor(det.significance),
                      fontWeight: 600,
                      fontSize: '12px',
                    }}>
                      {det.significance}
                      {det.needs_review && (
                        <span style={styles.reviewBadge} title="Flagged for human review">
                          ⚠
                        </span>
                      )}
                    </div>
                    <div style={{
                      fontSize: '10px',
                      color: 'var(--text-muted)',
                      marginTop: '2px',
                    }}>
                      {Math.round((det.confidence || 0) * 100)}% conf
                    </div>
                    {det.mitigation?.length > 0 && (
                      <div style={{
                        fontSize: '9px',
                        color: 'var(--text-secondary)',
                        marginTop: '2px',
                      }}>
                        {det.mitigation.join(', ')}
                      </div>
                    )}
                    <div style={{
                      fontSize: '10px',
                      color: 'var(--text-secondary)',
                      marginTop: '4px',
                      lineHeight: 1.3,
                    }}>
                      {det.reasoning}
                    </div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    )}
  </div>
)}
```

- [ ] **Step 2: Add the `reviewBadge` style**

Add to the `styles` object:

```javascript
reviewBadge: {
  marginLeft: '4px',
  fontSize: '11px',
  cursor: 'help',
},
```

- [ ] **Step 3: Start the dev server and verify the matrix renders**

Run: `cd frontend && npm run dev`

Test cases:
1. Run a pipeline — verify the 2D matrix renders with actions as columns and categories as rows
2. Verify significance colors match (red for significant, yellow for moderate, green for minimal/none)
3. Verify confidence percentages display in each cell
4. Verify the ⚠ badge shows on low-confidence cells
5. Verify mitigation categories show when present
6. Verify "No impact data available" shows when pipeline hasn't run
7. Verify the RAW JSON tab still works and shows the new structure

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ResultsPanel.jsx
git commit -m "feat(ui): render 2D impact matrix with confidence and mitigation indicators"
```

---

## Task 7: Final integration verification

Run the full test suite and verify the pipeline works end-to-end.

**Files:** None (verification only)

- [ ] **Step 1: Run all backend tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Verify import chain**

Run: `cd backend && python -c "from pipeline import stream_eia_pipeline; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit any remaining fixes, then final commit message**

If all tests pass with no changes needed, this step is a no-op.
