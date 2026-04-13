"""NEPA Environmental Assessment template.

Defines the 10-section structure of a screening-level EA and provides
per-section data extraction, LLM prompt building, and static rendering.
"""

from agents.templates import BaseTemplate, TemplateRegistry

# ── Section definitions ──────────────────────────────────────────────────────

_SECTIONS = [
    {"id": "1",  "title": "Title Page",                     "requires_llm": False},
    {"id": "2",  "title": "Purpose and Need",               "requires_llm": True},
    {"id": "3a", "title": "Proposed Action",                 "requires_llm": True},
    {"id": "3b", "title": "No-Action Alternative",           "requires_llm": True},
    {"id": "4",  "title": "Affected Environment",           "requires_llm": True},
    {"id": "5",  "title": "Environmental Consequences",     "requires_llm": True},
    {"id": "6",  "title": "Impact Matrix Table",            "requires_llm": False},
    {"id": "7",  "title": "Mitigation Measures",            "requires_llm": True},
    {"id": "8",  "title": "Consultation and Coordination",  "requires_llm": False},
    {"id": "9",  "title": "Confidence Disclaimer",          "requires_llm": False},
    {"id": "10", "title": "Appendices",                     "requires_llm": False},
]

# ── Env-data key → human label mapping (standard EA ordering) ────────────────

_ENV_RESOURCE_ORDER = [
    ("nwi_wetlands",      "Wetlands"),
    ("fema_flood_zones",  "Floodplains"),
    ("usfws_species",     "Threatened and Endangered Species"),
    ("usda_farmland",     "Soils and Farmland"),
    ("ejscreen",          "Environmental Justice"),
]

_SIGNIFICANCE_SYMBOLS = {
    "significant": "X",
    "moderate":    "!",
    "minimal":     "~",
    "none":        "-",
}


# ── Template class ───────────────────────────────────────────────────────────

@TemplateRegistry.register("EA")
class NepaEATemplate(BaseTemplate):
    document_type = "EA"

    @property
    def sections(self) -> list[dict]:
        return list(_SECTIONS)

    # ── Data extraction ──────────────────────────────────────────────────

    def get_section_data(self, section_id: str, state: dict) -> dict:
        extractors = {
            "1":  self._data_title_page,
            "2":  self._data_purpose_and_need,
            "3a": self._data_proposed_action,
            "3b": self._data_no_action,
            "4":  self._data_affected_env,
            "5":  self._data_consequences,
            "6":  self._data_matrix_table,
            "7":  self._data_mitigation,
            "8":  self._data_consultation,
            "9":  self._data_disclaimer,
            "10": self._data_appendices,
        }
        extractor = extractors.get(section_id)
        if extractor is None:
            return {}
        return extractor(state)

    def _data_title_page(self, state: dict) -> dict:
        parsed = state.get("parsed_project") or {}
        return {
            "project_name": state.get("project_name", "Untitled Project"),
            "project_type": parsed.get("project_type", ""),
            "location": parsed.get("location", ""),
            "coordinates": state.get("coordinates", ""),
        }

    def _data_purpose_and_need(self, state: dict) -> dict:
        parsed = state.get("parsed_project") or {}
        return {
            "description": state.get("description", ""),
            "project_type": parsed.get("project_type", ""),
            "location": parsed.get("location", ""),
        }

    def _data_proposed_action(self, state: dict) -> dict:
        parsed = state.get("parsed_project") or {}
        return {
            "project_type": parsed.get("project_type", ""),
            "scale": parsed.get("scale", ""),
            "location": parsed.get("location", ""),
            "actions": parsed.get("actions", []),
            "description": state.get("description", ""),
        }

    def _data_no_action(self, state: dict) -> dict:
        parsed = state.get("parsed_project") or {}
        return {
            "project_type": parsed.get("project_type", ""),
            "location": parsed.get("location", ""),
        }

    def _data_affected_env(self, state: dict) -> dict:
        env = state.get("environmental_data") or {}
        resources = {}
        for key, label in _ENV_RESOURCE_ORDER:
            data = env.get(key)
            if data:
                resources[label] = data
        errors = env.get("errors") or {}
        return {"resources": resources, "errors": errors}

    def _data_consequences(self, state: dict) -> dict:
        matrix = state.get("impact_matrix") or {}
        cells = matrix.get("cells", [])
        regs = state.get("regulations") or []
        # Group cells by category
        by_category: dict[str, list[dict]] = {}
        for cell in cells:
            cat = cell.get("category", "unknown")
            by_category.setdefault(cat, []).append(cell)
        return {
            "categories": by_category,
            "regulations": regs,
        }

    def _data_matrix_table(self, state: dict) -> dict:
        matrix = state.get("impact_matrix") or {}
        return {
            "actions": matrix.get("actions", []),
            "categories": matrix.get("categories", []),
            "cells": matrix.get("cells", []),
        }

    def _data_mitigation(self, state: dict) -> dict:
        matrix = state.get("impact_matrix") or {}
        cells_with_mitigation = [
            c for c in matrix.get("cells", [])
            if c.get("determination", {}).get("mitigation")
        ]
        # Group by mitigation type
        by_type: dict[str, list[dict]] = {}
        for cell in cells_with_mitigation:
            for mit in cell["determination"]["mitigation"]:
                by_type.setdefault(mit, []).append(cell)
        return {"by_type": by_type}

    def _data_consultation(self, state: dict) -> dict:
        env = state.get("environmental_data") or {}
        sources = []
        for key, label in _ENV_RESOURCE_ORDER:
            data = env.get(key)
            sources.append({
                "api": label,
                "key": key,
                "success": data is not None and bool(data),
            })
        errors = env.get("errors") or {}
        return {"sources": sources, "errors": errors}

    def _data_disclaimer(self, state: dict) -> dict:
        matrix = state.get("impact_matrix") or {}
        cells = matrix.get("cells", [])
        return {"cells": cells, "rag_fallbacks": matrix.get("rag_fallbacks", [])}

    def _data_appendices(self, state: dict) -> dict:
        return {
            "environmental_data": state.get("environmental_data") or {},
            "impact_matrix": state.get("impact_matrix") or {},
            "regulations": state.get("regulations") or [],
        }

    # ── LLM prompt building ──────────────────────────────────────────────

    def get_section_prompt(self, section_id: str, section_data: dict) -> str:
        builders = {
            "2":  self._prompt_purpose_and_need,
            "3a": self._prompt_proposed_action,
            "3b": self._prompt_no_action,
            "4":  self._prompt_affected_env,
            "5":  self._prompt_consequences,
            "7":  self._prompt_mitigation,
        }
        builder = builders.get(section_id)
        if builder is None:
            return ""
        return builder(section_data)

    def _prompt_purpose_and_need(self, data: dict) -> str:
        return (
            f"Write the 'Purpose and Need' section (1-2 paragraphs) for a NEPA "
            f"Environmental Assessment.\n\n"
            f"Project type: {data.get('project_type', 'unknown')}\n"
            f"Location: {data.get('location', 'unknown')}\n"
            f"Project description: {data.get('description', 'No description provided')}\n\n"
            f"Explain why this project is being proposed and what need it addresses. "
            f"Include location context."
        )

    def _prompt_proposed_action(self, data: dict) -> str:
        actions_list = "\n".join(
            f"  - {a}" for a in data.get("actions", [])
        ) or "  (no specific actions identified)"
        return (
            f"Write the 'Proposed Action' section (2-3 paragraphs) for a NEPA EA.\n\n"
            f"Project type: {data.get('project_type', 'unknown')}\n"
            f"Scale: {data.get('scale', 'unknown')}\n"
            f"Location: {data.get('location', 'unknown')}\n"
            f"Project description: {data.get('description', '')}\n"
            f"Discrete project actions:\n{actions_list}\n\n"
            f"Describe what the project involves, referencing each action."
        )

    def _prompt_no_action(self, data: dict) -> str:
        return (
            f"Write a brief 'No-Action Alternative' section (1 paragraph) for a "
            f"NEPA EA.\n\n"
            f"Project type: {data.get('project_type', 'unknown')}\n"
            f"Location: {data.get('location', 'unknown')}\n\n"
            f"Describe what would happen if the project does not proceed. "
            f"Keep it project-specific, not generic boilerplate."
        )

    def _prompt_affected_env(self, data: dict) -> str:
        resources = data.get("resources", {})
        errors = data.get("errors", {})
        parts = []
        for label, resource_data in resources.items():
            parts.append(f"### {label}\n{_format_resource(label, resource_data)}")
        if errors:
            parts.append(
                f"### Data Gaps\nThe following APIs returned errors: "
                f"{', '.join(errors.keys())}"
            )
        resource_text = "\n\n".join(parts) if parts else "No environmental data available."
        return (
            f"Write the 'Affected Environment' section for a NEPA EA. "
            f"One subsection per resource category.\n\n"
            f"Environmental data from federal APIs:\n\n{resource_text}\n\n"
            f"Convert this raw data into readable narrative. For each resource, "
            f"describe existing conditions. If data is missing, note it. "
            f"Do NOT invent data beyond what is provided."
        )

    def _prompt_consequences(self, data: dict) -> str:
        categories = data.get("categories", {})
        regs = data.get("regulations", [])
        parts = []
        for cat_name, cells in categories.items():
            cell_descriptions = []
            for c in cells:
                det = c.get("determination", {})
                cell_descriptions.append(
                    f"  Action: {c.get('action', '?')} | "
                    f"Significance: {det.get('significance', '?')} | "
                    f"Confidence: {det.get('confidence', '?')} | "
                    f"Reasoning: {det.get('reasoning', '')}"
                )
            parts.append(
                f"### {cat_name}\n" + "\n".join(cell_descriptions)
            )
        reg_text = "\n".join(
            f"  - {r.get('name', '?')} ({r.get('jurisdiction', '?')}): "
            f"{r.get('description', '')}"
            for r in regs
        ) or "  No regulations identified."
        return (
            f"Write the 'Environmental Consequences' section for a NEPA EA. "
            f"One subsection per impact category.\n\n"
            f"Impact determinations from analysis:\n\n"
            + "\n\n".join(parts)
            + f"\n\nApplicable regulations:\n{reg_text}\n\n"
            f"For each category, describe the impacts, which actions cause them, "
            f"the determination level, and regulatory basis. Do NOT re-evaluate "
            f"the determinations — explain them as given."
        )

    def _prompt_mitigation(self, data: dict) -> str:
        by_type = data.get("by_type", {})
        if not by_type:
            return ""
        parts = []
        for mit_type, cells in by_type.items():
            entries = []
            for c in cells:
                det = c.get("determination", {})
                entries.append(
                    f"  - {c.get('category', '?')} / {c.get('action', '?')}: "
                    f"{det.get('significance', '?')} impact"
                )
            parts.append(f"### {mit_type.title()}\n" + "\n".join(entries))
        return (
            f"Write the 'Mitigation Measures' section for a NEPA EA. "
            f"Group by mitigation type.\n\n"
            + "\n\n".join(parts)
            + f"\n\nFor each entry, describe the general mitigation approach "
            f"appropriate for that impact category and action."
        )

    # ── Static rendering ─────────────────────────────────────────────────

    def render_static_section(self, section_id: str, section_data: dict) -> str:
        renderers = {
            "1":  self._render_title_page,
            "6":  self._render_matrix_table,
            "8":  self._render_consultation,
            "9":  self._render_disclaimer,
            "10": self._render_appendices,
        }
        renderer = renderers.get(section_id)
        if renderer is None:
            return ""
        return renderer(section_data)

    def _render_title_page(self, data: dict) -> str:
        return (
            f"# Environmental Assessment\n\n"
            f"**Project:** {data.get('project_name', 'Untitled')}\n\n"
            f"**Project Type:** {data.get('project_type', 'N/A')}\n\n"
            f"**Location:** {data.get('location', 'N/A')}\n\n"
            f"**Coordinates:** {data.get('coordinates', 'N/A')}\n\n"
            f"**Prepared by:** Automated EIA Screening System\n\n"
            f"**Document Type:** NEPA Environmental Assessment (Screening Level)"
        )

    def _render_matrix_table(self, data: dict) -> str:
        actions = data.get("actions", [])
        categories = data.get("categories", [])
        cells = data.get("cells", [])

        if not actions or not categories:
            return "*No impact matrix data available.*"

        # Build lookup: (action, category) -> determination
        lookup: dict[tuple[str, str], dict] = {}
        for cell in cells:
            key = (cell.get("action", ""), cell.get("category", ""))
            lookup[key] = cell.get("determination", {})

        # Header row
        header = "| Category | " + " | ".join(actions) + " |"
        separator = "|---|" + "|".join("---" for _ in actions) + "|"

        rows = []
        for cat in categories:
            cells_str = []
            for act in actions:
                det = lookup.get((act, cat), {})
                sig = det.get("significance", "")
                conf = det.get("confidence", 0)
                symbol = _SIGNIFICANCE_SYMBOLS.get(sig, "?")
                cells_str.append(f"{symbol} ({conf:.0%})")
            rows.append(f"| {cat} | " + " | ".join(cells_str) + " |")

        legend = (
            "\n\n**Legend:** "
            "X = significant, ! = moderate, ~ = minimal, - = none. "
            "Percentages indicate confidence level."
        )
        return "\n".join([header, separator] + rows) + legend

    def _render_consultation(self, data: dict) -> str:
        sources = data.get("sources", [])
        errors = data.get("errors", {})
        lines = ["| Data Source | Status |", "|---|---|"]
        for src in sources:
            status = "Retrieved" if src["success"] else "No data / Error"
            lines.append(f"| {src['api']} | {status} |")
        if errors:
            lines.append("")
            lines.append("**API Errors:**")
            for key, msg in errors.items():
                lines.append(f"- **{key}:** {msg}")
        return "\n".join(lines)

    def _render_disclaimer(self, data: dict) -> str:
        cells = data.get("cells", [])
        rag_fallbacks = data.get("rag_fallbacks", [])

        header = (
            "> **Disclaimer:** This report was generated by an automated "
            "environmental screening system. All determinations should be "
            "reviewed by a qualified environmental professional before use in "
            "regulatory submissions. The following areas were identified as "
            "requiring particular attention due to data limitations or "
            "analytical uncertainty:"
        )

        flagged = [
            c for c in cells
            if c.get("determination", {}).get("needs_review")
        ]
        if not flagged and not rag_fallbacks:
            return header + "\n\n*No items flagged for additional review.*"

        items = []
        for c in flagged:
            det = c["determination"]
            items.append(
                f"- **{c.get('category', '?')}** ({c.get('action', '?')}): "
                f"determination = {det.get('significance', '?')}, "
                f"confidence = {det.get('confidence', 0):.0%}. "
                f"Reasoning: {det.get('reasoning', 'N/A')}"
            )

        if rag_fallbacks:
            items.append(
                f"\n*Note: The Impact Analysis agent required "
                f"{len(rag_fallbacks)} supplementary RAG queries, indicating "
                f"potential gaps in the Regulatory Screening agent's output.*"
            )

        return header + "\n\n" + "\n".join(items)

    def _render_appendices(self, data: dict) -> str:
        parts = []

        # Appendix A: Environmental data summary
        env = data.get("environmental_data", {})
        parts.append("## Appendix A: Environmental Data Summary\n")
        for key, label in _ENV_RESOURCE_ORDER:
            resource = env.get(key)
            if resource:
                parts.append(f"**{label}:** {_truncate_json(resource)}\n")
            else:
                parts.append(f"**{label}:** No data retrieved\n")
        errors = env.get("errors", {})
        if errors:
            parts.append(f"**Errors:** {errors}\n")

        # Appendix B: Full impact matrix
        matrix = data.get("impact_matrix", {})
        parts.append("\n## Appendix B: Full Impact Matrix\n")
        for cell in matrix.get("cells", [])[:50]:  # Cap at 50 for readability
            det = cell.get("determination", {})
            parts.append(
                f"- {cell.get('action', '?')} x {cell.get('category', '?')} "
                f"({cell.get('framework', '?')}): "
                f"{det.get('significance', '?')} "
                f"[confidence: {det.get('confidence', 0):.0%}]"
            )

        # Appendix C: Regulatory references
        regs = data.get("regulations", [])
        parts.append("\n\n## Appendix C: Regulatory References\n")
        for r in regs:
            parts.append(
                f"- **{r.get('name', '?')}** ({r.get('jurisdiction', '?')}): "
                f"{r.get('citation', 'N/A')}"
            )

        return "\n".join(parts)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _format_resource(label: str, data: dict) -> str:
    """Format a single environmental resource for the LLM prompt."""
    if label == "Wetlands":
        count = data.get("count", 0)
        types = [w.get("type", "?") for w in data.get("wetlands", [])]
        return f"Count: {count}. Types: {', '.join(types) or 'none'}"
    if label == "Floodplains":
        in_sfha = data.get("in_sfha", False)
        zones = [z.get("flood_zone", "?") for z in data.get("flood_zones", [])]
        return f"In SFHA: {in_sfha}. Zones: {', '.join(zones) or 'none'}"
    if label == "Threatened and Endangered Species":
        count = data.get("count", 0)
        species = [
            f"{s.get('name', '?')} ({s.get('status', '?')})"
            for s in data.get("species", [])
        ]
        return f"Count: {count}. Species: {', '.join(species) or 'none'}"
    if label == "Soils and Farmland":
        cls = data.get("farmland_class", "?")
        prime = data.get("is_prime", False)
        return f"Class: {cls}. Prime farmland: {prime}"
    if label == "Environmental Justice":
        return (
            f"Minority %: {data.get('minority_pct', '?')}, "
            f"Low-income %: {data.get('low_income_pct', '?')}, "
            f"PM2.5 percentile: {data.get('percentile_pm25', '?')}"
        )
    return str(data)


def _truncate_json(data: dict, max_len: int = 300) -> str:
    """Stringify a dict, truncating if too long."""
    import json
    text = json.dumps(data, default=str)
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text
