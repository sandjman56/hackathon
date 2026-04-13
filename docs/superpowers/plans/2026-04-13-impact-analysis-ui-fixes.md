# Impact Analysis UI Fixes — Model Dropdown & Matrix Display

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two issues with the Impact Analysis agent card: (1) show the AI model dropdown instead of "no LLM" pill, and (2) render the 2D impact matrix in the card dropdown with concise reasoning.

**Architecture:** The backend already treats `impact_analysis` as an LLM agent (removed from `NON_LLM_AGENTS` in `pipeline.py`), but the frontend `ModelDropdown.jsx` still has it in its own `NON_LLM_AGENTS` set. The dropdown renderer `renderImpactMatrix` still expects the old flat array schema (`ImpactRow[]`) instead of the new `ImpactMatrixOutput` object (`{ actions, categories, cells, rag_fallbacks }`). Both are frontend-only fixes.

**Tech Stack:** React, Vitest

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `frontend/src/components/ModelDropdown.jsx` | Modify | Remove `impact_analysis` from `NON_LLM_AGENTS` |
| `frontend/src/components/AgentPipeline.jsx` | Modify | Rewrite `renderImpactMatrix` for new `ImpactMatrixOutput` schema |
| `frontend/src/components/ModelDropdown.test.jsx` | No change | Iterates `NON_LLM_AGENTS` dynamically, auto-adjusts |
| `frontend/src/components/AgentPipeline.test.jsx` | Modify | Update expected LLM/non-LLM agent counts; add impact matrix dropdown test |

---

## Task 1: Enable model dropdown for Impact Analysis agent

**Files:**
- Modify: `frontend/src/components/ModelDropdown.jsx:1-5`
- Modify: `frontend/src/components/AgentPipeline.test.jsx:66-79`

- [ ] **Step 1: Update `NON_LLM_AGENTS` in ModelDropdown.jsx**

Remove `'impact_analysis'` from the set. The backend already treats it as an LLM agent (`backend/pipeline.py:177-180`).

```jsx
const NON_LLM_AGENTS = new Set([
  'environmental_data',
  'report_synthesis',
])
```

- [ ] **Step 2: Update AgentPipeline.test.jsx counts**

In the `AgentPipeline model dropdowns` describe block, update the expected counts. Impact analysis is now an LLM agent, so there are 3 `<select>` dropdowns and 2 "no LLM" pills.

```jsx
it('renders select dropdowns for LLM agents', () => {
  render(<AgentPipeline {...extendedProps} />)
  const selects = screen.getAllByRole('combobox')
  // project_parser, regulatory_screening, and impact_analysis are LLM agents
  expect(selects.length).toBe(3)
})

it('renders "no LLM" pill for non-LLM agents', () => {
  const { container } = render(<AgentPipeline {...extendedProps} />)
  const pills = container.querySelectorAll('span')
  const noLlmPills = Array.from(pills).filter((s) => s.textContent === 'no LLM')
  expect(noLlmPills.length).toBe(2)
})
```

- [ ] **Step 3: Run tests to verify**

Run: `cd frontend && npx vitest run src/components/ModelDropdown.test.jsx src/components/AgentPipeline.test.jsx`

Expected: All tests pass. The `ModelDropdown.test.jsx` "no LLM" test iterates the set dynamically so it auto-adjusts.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ModelDropdown.jsx frontend/src/components/AgentPipeline.test.jsx
git commit -m "fix(ui): enable model dropdown for impact analysis agent"
```

---

## Task 2: Render impact matrix in agent card dropdown

**Files:**
- Modify: `frontend/src/components/AgentPipeline.jsx:184-207` (rewrite `renderImpactMatrix`)
- Modify: `frontend/src/components/AgentPipeline.test.jsx` (add dropdown render test)

The output from the impact analysis agent is an `ImpactMatrixOutput` object:
```json
{
  "actions": ["land clearing", "construction"],
  "categories": ["wetlands", "endangered_species"],
  "cells": [
    {
      "action": "land clearing",
      "category": "wetlands",
      "framework": "Clean Water Act",
      "determination": {
        "significance": "significant",
        "confidence": 0.85,
        "reasoning": "Direct fill of 3.2 acres ...",
        "mitigation": ["avoidance", "compensatory"],
        "needs_review": false
      }
    }
  ],
  "rag_fallbacks": []
}
```

- [ ] **Step 1: Write the failing test**

Add a new test in `AgentPipeline.test.jsx` that verifies the impact matrix renders when the card is clicked:

```jsx
describe('AgentPipeline impact matrix dropdown', () => {
  it('renders impact cells when impact_analysis card is clicked', () => {
    const impactMatrix = {
      actions: ['land clearing', 'construction'],
      categories: ['wetlands'],
      cells: [
        {
          action: 'land clearing',
          category: 'wetlands',
          framework: 'Clean Water Act',
          determination: {
            significance: 'significant',
            confidence: 0.85,
            reasoning: 'Direct wetland fill impact',
            mitigation: ['avoidance', 'compensatory'],
            needs_review: false,
          },
        },
        {
          action: 'construction',
          category: 'wetlands',
          framework: 'Clean Water Act',
          determination: {
            significance: 'moderate',
            confidence: 0.72,
            reasoning: 'Runoff during construction phase',
            mitigation: ['minimization'],
            needs_review: false,
          },
        },
      ],
      rag_fallbacks: [],
    }

    const props = {
      ...extendedProps,
      pipelineState: { ...extendedProps.pipelineState, impact_analysis: 'complete' },
      agentOutputs: { impact_analysis: impactMatrix },
    }
    render(<AgentPipeline {...props} />)

    // Click the impact analysis card to open dropdown
    fireEvent.click(screen.getByText('IMPACT ANALYSIS'))

    // Verify cell data renders
    expect(screen.getByText('wetlands')).toBeInTheDocument()
    expect(screen.getByText('significant')).toBeInTheDocument()
    expect(screen.getByText('85%')).toBeInTheDocument()
    expect(screen.getByText('Direct wetland fill impact')).toBeInTheDocument()
  })

  it('shows empty message when impact matrix has no cells', () => {
    const props = {
      ...extendedProps,
      pipelineState: { ...extendedProps.pipelineState, impact_analysis: 'complete' },
      agentOutputs: { impact_analysis: { actions: [], categories: [], cells: [], rag_fallbacks: [] } },
    }
    render(<AgentPipeline {...props} />)
    fireEvent.click(screen.getByText('IMPACT ANALYSIS'))
    expect(screen.getByText('No impact data')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/AgentPipeline.test.jsx`

Expected: FAIL — `renderImpactMatrix` treats the object as not-an-array and shows "No impact matrix generated (LLM stub)".

- [ ] **Step 3: Rewrite `renderImpactMatrix` in AgentPipeline.jsx**

Replace lines 184-207 with a renderer that handles the `ImpactMatrixOutput` object. Group cells by category and show each cell as a compact row with action, significance badge, confidence %, and truncated reasoning.

```jsx
function renderImpactMatrix(matrix) {
  const cells = matrix?.cells
  if (!Array.isArray(cells) || cells.length === 0) {
    return <Empty msg="No impact data" />
  }
  const sigColor = {
    significant: 'var(--red-alert)',
    moderate: 'var(--yellow-warn)',
    minimal: 'var(--green-primary)',
    none: 'var(--text-muted)',
  }
  // Group cells by category for readability
  const byCategory = {}
  for (const cell of cells) {
    if (!byCategory[cell.category]) byCategory[cell.category] = []
    byCategory[cell.category].push(cell)
  }
  return (
    <div style={s.outputBody}>
      {Object.entries(byCategory).map(([category, catCells]) => (
        <div key={category}>
          <SectionTitle>{category.replace(/_/g, ' ')}</SectionTitle>
          {catCells.map((cell, i) => {
            const det = cell.determination || {}
            return (
              <div key={i} style={s.impactCell}>
                <div style={s.impactCellHeader}>
                  <span style={s.impactAction}>{cell.action}</span>
                  <span style={{ ...s.matrixSig, color: sigColor[det.significance] || 'var(--text-muted)' }}>
                    {det.significance}
                  </span>
                  <span style={s.impactConf}>
                    {Math.round((det.confidence || 0) * 100)}%
                  </span>
                  {det.needs_review && (
                    <span style={s.reviewFlag} title="Flagged for human review">⚠</span>
                  )}
                </div>
                {det.mitigation?.length > 0 && (
                  <div style={s.impactMitigation}>{det.mitigation.join(', ')}</div>
                )}
                {det.reasoning && (
                  <div style={s.impactReasoning}>{det.reasoning}</div>
                )}
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 4: Add styles for impact cell rendering**

Add these styles to the `s` object (after the existing `matrixNotes` entry around line 553):

```jsx
  impactCell: {
    padding: '4px 0',
    borderBottom: '1px solid var(--border)',
  },
  impactCellHeader: {
    display: 'flex',
    alignItems: 'baseline',
    gap: '8px',
  },
  impactAction: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-secondary)',
    flex: 1,
  },
  impactConf: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-muted)',
    flexShrink: 0,
  },
  reviewFlag: {
    fontSize: '11px',
    flexShrink: 0,
  },
  impactMitigation: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    color: 'var(--text-muted)',
    paddingLeft: '8px',
    marginTop: '2px',
  },
  impactReasoning: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-secondary)',
    paddingLeft: '8px',
    marginTop: '2px',
    lineHeight: 1.4,
  },
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/AgentPipeline.test.jsx`

Expected: All tests pass including the new impact matrix dropdown tests.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/AgentPipeline.jsx frontend/src/components/AgentPipeline.test.jsx
git commit -m "fix(ui): render impact matrix in agent card dropdown with new schema"
```

---

## Task 3: Manual verification

- [ ] **Step 1: Run the full frontend test suite**

Run: `cd frontend && npx vitest run`

Expected: All tests pass with no regressions.

- [ ] **Step 2: Visual check in browser**

Start the dev server and run a pipeline. Verify:
1. Impact Analysis card shows a model dropdown (not "no LLM" pill)
2. After pipeline completes, clicking the Impact Analysis card opens a dropdown
3. The dropdown shows cells grouped by category with significance, confidence %, mitigation, and reasoning
4. The dropdown scrolls if the matrix is large (max-height 320px is already set)
