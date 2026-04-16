# Evaluation UI Panel — Design Spec

> Date: 2026-04-15
> Branch: `feat/ecfr-phase-1`

## Goal

Add an evaluation UI panel to the evaluations page that lets users import a past agent pipeline run, view all 5 agent outputs in an elegant collapsible preview, and (in future) trigger an evaluation workflow.

## Layout

The evaluations page (`EvaluationsView`) gains a new bottom section beneath the existing upload zone + documents table. The bottom section is a horizontal split with a draggable divider:

- **Left panel (70% default)**: "IMPORT RUN" button, then once a project is selected, 5 collapsible agent output sections
- **Right panel (30% default)**: "EVALUATE" button (stub — no logic this session)
- **Vertical divider**: drag to resize left/right panels. Min-width 200px on each side.

## Data Source

Pipeline outputs are stored in 5 per-agent tables, all sharing an identical schema:

| Table | Agent |
|-------|-------|
| `project_parser_outputs` | Project Parser |
| `environmental_data_outputs` | Environmental Data |
| `regulatory_screening_outputs` | Regulatory Screening |
| `impact_analysis_outputs` | Impact Analysis |
| `report_synthesis_outputs` | Report Synthesis |

Each has: `id`, `project_id` (FK → `projects.id`), `output` (JSONB), `model`, `input_tokens`, `output_tokens`, `cost_usd`, `saved_at`.

## Backend

### New endpoint: `GET /api/projects/{project_id}/outputs`

Queries each of the 5 `*_outputs` tables filtered by `project_id`, returns the most recent row per agent (`ORDER BY saved_at DESC LIMIT 1`).

Response shape:
```json
{
  "project": { "id": 1, "name": "...", "coordinates": "...", "description": "...", "saved_at": "..." },
  "project_parser": { "output": {}, "model": "...", "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "saved_at": "..." },
  "environmental_data": { "output": {}, "model": "...", ... },
  "regulatory_screening": { "output": {}, ... },
  "impact_analysis": { "output": {}, ... },
  "report_synthesis": { "output": {}, ... }
}
```

If a table has no row for the given project, that key is `null`.

Returns 404 if project_id does not exist in `projects`.

## Frontend

### Modified: `EvaluationsView.jsx`

- Existing upload zone + documents table stays at the top
- New bottom section added below, separated by a horizontal border
- Bottom section contains the split-pane layout (left: RunPreviewPanel, right: EvaluatePanel)

### New: `RunPreviewPanel.jsx`

- "IMPORT RUN" button at top
- Clicking opens a dropdown listing projects from `GET /api/projects` (name, coordinates, date)
- On selection, fetches `GET /api/projects/{id}/outputs`
- Renders 5 collapsible sections:

| Section | Header | Content |
|---------|--------|---------|
| PROJECT PARSE | model, tokens, cost | Parsed project JSONB rendered as key-value pairs |
| API CALLS & RESULTS | model, tokens, cost | Environmental data JSONB — each API source as a sub-section |
| REGULATORY SCREENING | model, tokens, cost | List of regulations with name, description, jurisdiction |
| IMPACT MATRIX | model, tokens, cost | Actions x categories grid with significance/confidence |
| REPORT SYNTHESIS | model, tokens, cost | Full report (collapsed by default) |

- All sections expanded by default except Report Synthesis
- Each section header shows: agent label, model badge, token count, cost

### New: `EvaluatePanel.jsx`

- Centered "EVALUATE" button styled in the existing green-on-dark theme
- Button is a stub — onClick shows a placeholder message or does nothing
- Panel also shows a brief label: "Run evaluation against imported pipeline data"

### Resizable Split Pane

- Pure CSS + mouse event handlers (mousedown on divider, mousemove to resize, mouseup to stop)
- No new library
- Left panel starts at 70%, right at 30%
- Min-width 200px on each side
- Divider styled as a 4px wide handle with hover highlight

## Styling

All new components use the existing design system:
- `var(--font-mono)` for all text
- `var(--green-primary)` for accents, active states, section headers
- `var(--bg-card)` / `var(--bg-secondary)` for card backgrounds
- `var(--border)` for dividers
- `var(--text-secondary)` / `var(--text-muted)` for body/meta text
- Inline `styles` object pattern matching existing components

## Scope Exclusions

- EVALUATE button logic (future session)
- Editing or re-running pipeline outputs
- Saving evaluation results
