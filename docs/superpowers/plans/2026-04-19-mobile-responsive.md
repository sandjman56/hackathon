# Mobile Responsive Design Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the CLEAVER app usable on mobile via a hamburger navbar, stacked single-column layout on the main/evals/metrics pages, and enlarge the desktop globe.

**Architecture:** A single `useIsMobile()` hook (matchMedia-based) returns a boolean; each affected component conditionally applies mobile vs desktop inline style objects — no new CSS files, no Tailwind. Desktop behavior is fully preserved.

**Tech Stack:** React 18, Vitest, @testing-library/react, inline JS style objects

---

## File Map

| File | Action |
|------|--------|
| `frontend/src/hooks/useIsMobile.js` | Create — reactive mobile breakpoint hook |
| `frontend/src/hooks/useIsMobile.test.js` | Create — hook unit tests |
| `frontend/src/App.jsx` | Modify — hamburger navbar, mobile main layout, desktop globe enlargement |
| `frontend/src/components/EvaluationsView.jsx` | Modify — mobile stacked split pane |
| `frontend/src/pages/MetricsView.jsx` | Modify — mobile padding, stacked selects, table scroll |

---

## Task 1: `useIsMobile` Hook

**Files:**
- Create: `frontend/src/hooks/useIsMobile.js`
- Create: `frontend/src/hooks/useIsMobile.test.js`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/hooks/useIsMobile.test.js`:

```js
import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import useIsMobile from './useIsMobile'

describe('useIsMobile', () => {
  let changeListeners

  const mockMatchMedia = (matches) => {
    changeListeners = []
    window.matchMedia = vi.fn(() => ({
      matches,
      addEventListener: (_evt, fn) => changeListeners.push(fn),
      removeEventListener: (_evt, fn) => {
        changeListeners = changeListeners.filter((l) => l !== fn)
      },
    }))
  }

  beforeEach(() => mockMatchMedia(false))

  it('returns false on wide viewport', () => {
    mockMatchMedia(false)
    const { result } = renderHook(() => useIsMobile())
    expect(result.current).toBe(false)
  })

  it('returns true on narrow viewport', () => {
    mockMatchMedia(true)
    const { result } = renderHook(() => useIsMobile())
    expect(result.current).toBe(true)
  })

  it('updates when matchMedia fires change event', () => {
    mockMatchMedia(false)
    const { result } = renderHook(() => useIsMobile())
    expect(result.current).toBe(false)
    act(() => changeListeners.forEach((fn) => fn({ matches: true })))
    expect(result.current).toBe(true)
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd frontend && npm test -- src/hooks/useIsMobile.test.js
```

Expected: 3 failures — `useIsMobile` does not exist yet.

- [ ] **Step 3: Implement the hook**

Create `frontend/src/hooks/useIsMobile.js`:

```js
import { useEffect, useState } from 'react'

export default function useIsMobile(breakpoint = 768) {
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(`(max-width: ${breakpoint}px)`).matches
  )
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${breakpoint}px)`)
    const handler = (e) => setIsMobile(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [breakpoint])
  return isMobile
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd frontend && npm test -- src/hooks/useIsMobile.test.js
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useIsMobile.js frontend/src/hooks/useIsMobile.test.js
git commit -m "feat: add useIsMobile hook with tests"
```

---

## Task 2: Desktop Globe Enlargement

**Files:**
- Modify: `frontend/src/App.jsx` — `styles.globeWrapper` and `styles.brainScannerWrapper`

No automated test needed — this is a pure visual layout adjustment. Verify by running the dev server.

- [ ] **Step 1: Update globe and brain scanner flex ratios**

In `frontend/src/App.jsx`, find the `styles` object at the bottom. Replace `globeWrapper` and `brainScannerWrapper`:

```js
// BEFORE
globeWrapper: {
  flex: 1,
  overflow: 'hidden',
  display: 'flex',
  justifyContent: 'flex-end',
  alignItems: 'flex-start',
},
brainScannerWrapper: {
  flex: 1,
  padding: '0 20px 20px 20px',
  overflow: 'hidden',
  display: 'flex',
  flexDirection: 'column',
},

// AFTER
globeWrapper: {
  flex: 3,
  overflow: 'hidden',
  display: 'flex',
  justifyContent: 'center',
  alignItems: 'center',
},
brainScannerWrapper: {
  flex: 2,
  padding: '0 20px 20px 20px',
  overflow: 'hidden',
  display: 'flex',
  flexDirection: 'column',
},
```

- [ ] **Step 2: Verify visually**

```bash
cd frontend && npm run dev
```

Open `http://localhost:5173` in a browser. The globe in the top-right should be noticeably larger and centered in its panel. The BrainScanner remains visible below it.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.jsx
git commit -m "feat: enlarge desktop globe (flex 3/2 split, centered)"
```

---

## Task 3: Mobile Navbar (Hamburger Menu)

**Files:**
- Modify: `frontend/src/App.jsx`

- [ ] **Step 1: Import `useIsMobile` and add mobile menu state**

At the top of `frontend/src/App.jsx`, add the import after the existing imports:

```js
import useIsMobile from './hooks/useIsMobile.js'
```

Inside `function App()`, after the existing state declarations, add:

```js
const isMobile = useIsMobile()
const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
const mobileMenuRef = useRef(null)
```

- [ ] **Step 2: Add useEffect to close mobile menu on outside click**

Add this effect inside `function App()`, alongside the existing `evalMenuOpen` effect:

```js
useEffect(() => {
  if (!mobileMenuOpen) return
  const handleOutside = (e) => {
    if (mobileMenuRef.current && !mobileMenuRef.current.contains(e.target)) {
      setMobileMenuOpen(false)
    }
  }
  document.addEventListener('mousedown', handleOutside)
  return () => document.removeEventListener('mousedown', handleOutside)
}, [mobileMenuOpen])
```

- [ ] **Step 3: Update the header JSX**

Find the `<header style={styles.header}>` block. Replace the `<div style={styles.headerLeft}>` contents and the `<div style={styles.headerRight}>` with:

```jsx
<header style={styles.header}>
  <div style={styles.headerLeft}>
    <svg width="36" height="50" viewBox="0 0 100 140" fill="none" style={{ filter: 'drop-shadow(0 0 8px #00ff87)', flexShrink: 0 }}>
      <g fill="#00ff87">
        <path d="M 50 4 L 52 80 L 50 90 L 48 80 Z"/>
        <path d="M 22 44 C 16 60, 24 80, 50 86 C 76 80, 84 60, 78 44 C 80 52, 72 68, 50 76 C 28 68, 20 52, 22 44 Z"/>
      </g>
    </svg>
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
      <span style={styles.title}>CLEAVER</span>
      {!isMobile && <span style={styles.subtitle}>Customized Environmental Impact Reports</span>}
    </div>
  </div>

  {isMobile ? (
    <div ref={mobileMenuRef} style={{ position: 'relative' }}>
      <button
        style={styles.hamburgerBtn}
        onClick={() => setMobileMenuOpen((o) => !o)}
        aria-label="Menu"
      >
        ☰
      </button>
      {mobileMenuOpen && (
        <div style={styles.mobileMenu}>
          <span style={{
            ...styles.statusChip,
            color: STATUS_CONFIG[systemStatus].color,
            borderColor: STATUS_CONFIG[systemStatus].color,
            background: STATUS_CONFIG[systemStatus].bg,
            margin: '8px 12px',
            display: 'block',
            textAlign: 'center',
          }}>
            {STATUS_CONFIG[systemStatus].label}
          </span>
          {[
            { label: 'PIPELINE EVALS', v: 'evaluations' },
            { label: 'COST', v: 'cost' },
            { label: 'LATENCY', v: 'latency' },
            { label: 'VIEW DB', v: 'db' },
          ].map(({ label, v }) => (
            <button
              key={v}
              style={{ ...styles.mobileMenuItem, ...(view === v ? styles.mobileMenuItemActive : {}) }}
              onClick={() => { setView(v); setMobileMenuOpen(false) }}
            >
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  ) : (
    <div style={styles.headerRight}>
      <div ref={evalMenuRef} style={{ position: 'relative' }}>
        <button
          style={['evaluations', 'evaluation-chunks', 'cost', 'latency'].includes(view) ? { ...styles.dbBtn, background: 'var(--green-dim)' } : styles.dbBtn}
          onClick={() => setEvalMenuOpen((o) => !o)}
        >
          EVALUATIONS ▾
        </button>
        {evalMenuOpen && (
          <div style={styles.evalDropdown}>
            {[
              { label: 'PIPELINE EVALS', v: 'evaluations' },
              { label: 'COST', v: 'cost' },
              { label: 'LATENCY', v: 'latency' },
            ].map(({ label, v }) => (
              <button
                key={v}
                style={{ ...styles.evalDropdownItem, ...(view === v ? styles.evalDropdownItemActive : {}) }}
                onClick={() => { setView(v); setEvalMenuOpen(false) }}
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </div>
      <button
        style={view === 'db' ? { ...styles.dbBtn, background: 'var(--green-dim)' } : styles.dbBtn}
        onClick={() => setView(view === 'db' ? 'main' : 'db')}
      >
        VIEW DB
      </button>
      <span style={{
        ...styles.statusChip,
        color: STATUS_CONFIG[systemStatus].color,
        borderColor: STATUS_CONFIG[systemStatus].color,
        background: STATUS_CONFIG[systemStatus].bg,
      }}>
        {STATUS_CONFIG[systemStatus].label}
      </span>
    </div>
  )}
</header>
```

- [ ] **Step 4: Add hamburger and mobile menu styles**

In the `styles` object at the bottom of `App.jsx`, add these entries:

```js
hamburgerBtn: {
  fontFamily: 'var(--font-mono)',
  fontSize: '18px',
  color: 'var(--green-primary)',
  background: 'transparent',
  border: '1px solid var(--green-primary)',
  borderRadius: '4px',
  padding: '2px 10px',
  cursor: 'pointer',
  lineHeight: 1,
},
mobileMenu: {
  position: 'absolute',
  top: 'calc(100% + 8px)',
  right: 0,
  background: 'var(--bg-secondary)',
  border: '1px solid var(--border)',
  borderRadius: '4px',
  zIndex: 200,
  minWidth: '180px',
  display: 'flex',
  flexDirection: 'column',
},
mobileMenuItem: {
  fontFamily: 'var(--font-mono)',
  fontSize: '10px',
  letterSpacing: '1px',
  color: 'var(--text-secondary)',
  background: 'transparent',
  border: 'none',
  borderBottom: '1px solid var(--border)',
  padding: '10px 14px',
  cursor: 'pointer',
  textAlign: 'left',
},
mobileMenuItemActive: {
  color: 'var(--green-primary)',
  background: 'var(--green-dim)',
},
```

- [ ] **Step 5: Verify**

```bash
cd frontend && npm run dev
```

Open DevTools → toggle device toolbar to a mobile viewport (e.g. iPhone 12, 390px wide). Confirm:
- Subtitle is hidden
- Hamburger ☰ button appears on the right
- Clicking hamburger opens a dropdown with status + 4 nav items
- Clicking an item navigates and closes the menu
- Clicking outside closes the menu

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.jsx
git commit -m "feat: mobile hamburger navbar"
```

---

## Task 4: Mobile Main Page Layout

**Files:**
- Modify: `frontend/src/App.jsx`

- [ ] **Step 1: Replace the main content section with conditional mobile/desktop render**

In `frontend/src/App.jsx`, find the closing `} : (` before `<div style={styles.main}>` (around line 279). Replace the entire `(` ... `)` block that renders the 3-column layout (the final branch in the view chain) with:

```jsx
) : (
  <>
    {isMobile ? (
      <div style={styles.mobileMain}>
        {/* Section 1: top row — form left, globe+brain right */}
        <div style={styles.mobileTopRow}>
          <div style={styles.mobileFormCol}>
            <ProjectForm
              projectId={currentProjectId}
              onResult={handleResult}
              onPipelineUpdate={handlePipelineUpdate}
              onStepsUpdate={handleStepsUpdate}
              onLog={handleLog}
              onRunningChange={handleRunningChange}
              modelSelections={selections}
              onCostUpdate={handleCostUpdate}
              onDurationUpdate={handleDurationUpdate}
              onPipelineStartedAt={handlePipelineStartedAt}
              onProjectIdChange={(id) => { setCurrentProjectId(id); setPendingOverwrite(null) }}
              onProjectInfoChange={setProjectInfo}
              onLoadOutputs={(outputs, costs, pipelineStatus) => {
                setAgentOutputs(outputs)
                setAgentCosts(costs)
                setPipelineState(pipelineStatus)
                const hasAnyOutput = Object.values(outputs).some(v => v !== null)
                if (hasAnyOutput) {
                  setResults({
                    impact_matrix: outputs.impact_analysis || {},
                    regulations: outputs.regulatory_screening || [],
                    report: outputs.report_synthesis || {},
                  })
                } else {
                  setResults(null)
                }
              }}
            />
          </div>
          <div style={styles.mobileRightCol}>
            <div ref={globeContainerRef} style={styles.mobileGlobeWrapper}>
              <Globe
                projectName={projectInfo.projectName}
                coordinates={projectInfo.coordinates}
                size={globeSize}
              />
            </div>
            <div style={styles.mobileBrainWrapper}>
              <BrainScanner
                logs={logs}
                running={running}
                onCommand={handleCommand}
              />
            </div>
          </div>
        </div>

        <div style={styles.mobileDivider} />

        {/* Section 2: pipeline status */}
        <div style={styles.mobilePipelineSection}>
          <AgentPipeline
            pipelineState={pipelineState}
            agentOutputs={agentOutputs}
            selections={selections}
            setSelection={setSelection}
            availableProviders={availableProviders}
            modelCatalog={modelCatalog}
            agentCosts={agentCosts}
            agentDurations={agentDurations}
            pipelineRunKey={pipelineRunKey}
          />
        </div>

        <div style={styles.mobileDivider} />

        {/* Section 3: output */}
        <div style={styles.mobileOutputSection}>
          <ResultsPanel results={results} />
          {!running && Object.keys(agentOutputs).length > 0 && (
            <div style={{ marginTop: '12px' }}>
              <button
                onClick={() => handleSaveResults(false)}
                disabled={saveResultsFlash === 'saving'}
                style={{
                  ...styles.saveResultsBtn,
                  ...(saveResultsFlash === 'saved' ? styles.saveResultsBtnSaved : {}),
                  ...(saveResultsFlash === 'error' ? styles.saveResultsBtnError : {}),
                }}
              >
                {saveResultsFlash === 'saving' ? 'SAVING...'
                  : saveResultsFlash === 'saved' ? 'SAVED ✓'
                  : saveResultsFlash === 'error' ? 'ERROR — TRY AGAIN'
                  : 'SAVE RESULTS'}
              </button>
              {pendingOverwrite && (
                <div style={styles.overwriteWarning}>
                  <span>Results saved {new Date(pendingOverwrite.saved_at).toLocaleString()} already exist.</span>
                  <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
                    <button style={styles.overwriteConfirmBtn} onClick={() => handleSaveResults(true)}>
                      CONFIRM OVERWRITE
                    </button>
                    <button style={styles.overwriteCancelBtn} onClick={() => setPendingOverwrite(null)}>
                      CANCEL
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    ) : (
      <div style={styles.main}>
        {/* Left: project form */}
        <div style={styles.colLeft}>
          <ProjectForm
            projectId={currentProjectId}
            onResult={handleResult}
            onPipelineUpdate={handlePipelineUpdate}
            onStepsUpdate={handleStepsUpdate}
            onLog={handleLog}
            onRunningChange={handleRunningChange}
            modelSelections={selections}
            onCostUpdate={handleCostUpdate}
            onDurationUpdate={handleDurationUpdate}
            onPipelineStartedAt={handlePipelineStartedAt}
            onProjectIdChange={(id) => { setCurrentProjectId(id); setPendingOverwrite(null) }}
            onProjectInfoChange={setProjectInfo}
            onLoadOutputs={(outputs, costs, pipelineStatus) => {
              setAgentOutputs(outputs)
              setAgentCosts(costs)
              setPipelineState(pipelineStatus)
              const hasAnyOutput = Object.values(outputs).some(v => v !== null)
              if (hasAnyOutput) {
                setResults({
                  impact_matrix: outputs.impact_analysis || {},
                  regulations: outputs.regulatory_screening || [],
                  report: outputs.report_synthesis || {},
                })
              } else {
                setResults(null)
              }
            }}
          />
        </div>

        <div style={styles.separator} />

        {/* Middle: pipeline status + results */}
        <div style={styles.colMiddle}>
          <div style={styles.colMiddleTop}>
            <AgentPipeline
              pipelineState={pipelineState}
              agentOutputs={agentOutputs}
              selections={selections}
              setSelection={setSelection}
              availableProviders={availableProviders}
              modelCatalog={modelCatalog}
              agentCosts={agentCosts}
              agentDurations={agentDurations}
              pipelineRunKey={pipelineRunKey}
            />
          </div>
          <div style={styles.colMiddleBottom}>
            <ResultsPanel results={results} />
            {!running && Object.keys(agentOutputs).length > 0 && (
              <div style={{ marginTop: '12px' }}>
                <button
                  onClick={() => handleSaveResults(false)}
                  disabled={saveResultsFlash === 'saving'}
                  style={{
                    ...styles.saveResultsBtn,
                    ...(saveResultsFlash === 'saved' ? styles.saveResultsBtnSaved : {}),
                    ...(saveResultsFlash === 'error' ? styles.saveResultsBtnError : {}),
                  }}
                >
                  {saveResultsFlash === 'saving' ? 'SAVING...'
                    : saveResultsFlash === 'saved' ? 'SAVED ✓'
                    : saveResultsFlash === 'error' ? 'ERROR — TRY AGAIN'
                    : 'SAVE RESULTS'}
                </button>
                {pendingOverwrite && (
                  <div style={styles.overwriteWarning}>
                    <span>Results saved {new Date(pendingOverwrite.saved_at).toLocaleString()} already exist.</span>
                    <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
                      <button style={styles.overwriteConfirmBtn} onClick={() => handleSaveResults(true)}>
                        CONFIRM OVERWRITE
                      </button>
                      <button style={styles.overwriteCancelBtn} onClick={() => setPendingOverwrite(null)}>
                        CANCEL
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        <div style={styles.separator} />

        {/* Right: globe + brain scanner */}
        <div style={styles.colRight}>
          <div ref={globeContainerRef} style={styles.globeWrapper}>
            <Globe
              projectName={projectInfo.projectName}
              coordinates={projectInfo.coordinates}
              size={globeSize}
            />
          </div>
          <div style={styles.brainScannerWrapper}>
            <BrainScanner
              logs={logs}
              running={running}
              onCommand={handleCommand}
            />
          </div>
        </div>
      </div>
    )}
  </>
)}
```

- [ ] **Step 2: Add mobile layout styles**

In the `styles` object at the bottom of `App.jsx`, add:

```js
mobileMain: {
  display: 'flex',
  flexDirection: 'column',
  flex: 1,
  overflowY: 'auto',
},
mobileTopRow: {
  display: 'flex',
  flexDirection: 'row',
  height: '60vh',
  flexShrink: 0,
},
mobileFormCol: {
  width: '60%',
  padding: '12px',
  overflowY: 'auto',
  borderRight: '1px solid var(--border)',
},
mobileRightCol: {
  width: '40%',
  display: 'flex',
  flexDirection: 'column',
  overflow: 'hidden',
},
mobileGlobeWrapper: {
  flex: 1,
  overflow: 'hidden',
  display: 'flex',
  justifyContent: 'center',
  alignItems: 'center',
},
mobileBrainWrapper: {
  flex: 1,
  padding: '0 8px 8px',
  overflow: 'hidden',
  display: 'flex',
  flexDirection: 'column',
},
mobileDivider: {
  height: '1px',
  background: 'var(--border)',
  flexShrink: 0,
},
mobilePipelineSection: {
  padding: '12px',
  overflowY: 'auto',
  flexShrink: 0,
},
mobileOutputSection: {
  padding: '12px',
  overflowY: 'auto',
},
```

- [ ] **Step 2b: Fix ResizeObserver dependency**

The existing `useLayoutEffect` in `App.jsx` has a `[]` dependency, meaning the ResizeObserver only attaches once. When the viewport crosses the 768px breakpoint and the rendered container changes, the observer must re-attach. Change the dependency to `[isMobile]`:

```js
// find this line at the end of the useLayoutEffect block:
}, [])
// change to:
}, [isMobile])
```

- [ ] **Step 3: Verify**

```bash
cd frontend && npm run dev
```

In DevTools mobile viewport (390px wide):
- Top 60% of screen: form on left, globe + brain stacked on right
- Scroll down: pipeline status section (full width)
- Scroll further: output/results section (full width)

In desktop viewport: layout is unchanged from before this task.

- [ ] **Step 4: Run existing tests to check for regressions**

```bash
cd frontend && npm test
```

Expected: all previously passing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.jsx
git commit -m "feat: mobile main page layout (60/40 top row, stacked pipeline + output)"
```

---

## Task 5: Evaluations Page Mobile Layout

**Files:**
- Modify: `frontend/src/components/EvaluationsView.jsx`

- [ ] **Step 1: Import `useIsMobile` and call it**

At the top of `frontend/src/components/EvaluationsView.jsx`, add the import after the existing imports:

```js
import useIsMobile from '../hooks/useIsMobile.js'
```

Inside `export default function EvaluationsView(...)`, add after the existing state declarations:

```js
const isMobile = useIsMobile()
```

- [ ] **Step 2: Update the split pane JSX**

Find the split pane section (starts around `{/* ── Evaluation split pane */}`). Replace it with:

```jsx
{/* ── Evaluation split pane ──────────────────────────────── */}
<div style={styles.splitDividerH} />
<div ref={splitContainerRef} style={isMobile ? { ...styles.splitContainer, flexDirection: 'column' } : styles.splitContainer}>
  <div style={isMobile
    ? { width: '100%', maxHeight: '50vh', overflowY: 'auto', padding: '16px' }
    : { ...styles.splitLeft, width: `${splitPct}%` }
  }>
    <RunPreviewPanel onProjectSelect={setSelectedProject} />
  </div>
  <div
    style={isMobile ? { display: 'none' } : styles.splitHandle}
    onMouseDown={() => { draggingRef.current = true }}
    onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--green-primary)' }}
    onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--border)' }}
  />
  <div style={isMobile
    ? { width: '100%', maxHeight: '50vh', overflowY: 'auto', padding: '16px', borderTop: '1px solid var(--border)' }
    : { ...styles.splitRight, width: `${100 - splitPct}%` }
  }>
    <EvaluatePanel selectedProject={selectedProject} />
  </div>
</div>
```

- [ ] **Step 3: Verify**

```bash
cd frontend && npm run dev
```

Navigate to Evaluations via hamburger menu on mobile viewport:
- Upload zone and doc list appear at top (full width)
- RunPreviewPanel appears below (full width, scrollable up to 50vh)
- EvaluatePanel appears below that (full width, scrollable up to 50vh)
- Drag handle is hidden

On desktop: split pane works as before with drag-to-resize.

- [ ] **Step 4: Run existing tests**

```bash
cd frontend && npm test -- src/components/EvaluationsView.test.jsx
```

Expected: all previously passing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/EvaluationsView.jsx
git commit -m "feat: mobile evaluations page — vertical stacked split pane"
```

---

## Task 6: MetricsView Mobile Layout

**Files:**
- Modify: `frontend/src/pages/MetricsView.jsx`

- [ ] **Step 1: Import `useIsMobile` and call it**

At the top of `frontend/src/pages/MetricsView.jsx`, add after the existing import:

```js
import useIsMobile from '../hooks/useIsMobile.js'
```

Inside `export default function MetricsView(...)`, add after the existing state declarations:

```js
const isMobile = useIsMobile()
```

- [ ] **Step 2: Update the `s` style object to use `isMobile`**

The `s` object is declared inside the component. Update `s.wrap` and add a `selectRow` entry:

```js
const s = {
  wrap: { padding: isMobile ? '16px' : '24px 32px', fontFamily: 'var(--font-mono)', color: 'var(--text)', maxWidth: '1100px', margin: '0 auto' },
  // ... rest unchanged ...
  selectRow: {
    marginBottom: '16px',
    display: 'flex',
    flexDirection: isMobile ? 'column' : 'row',
    gap: isMobile ? '8px' : '0',
    flexWrap: 'wrap',
  },
}
```

- [ ] **Step 3: Apply `s.selectRow` to the select container and wrap the model table**

Find the run drill-down `<div style={{ marginBottom: '16px' }}>` that contains the two `<select>` elements. Replace `style={{ marginBottom: '16px' }}` with `style={s.selectRow}`.

Find the model breakdown `<table style={s.table}>` (inside the `isCost && perModel.length > 0` block). Wrap it in a scroll container:

```jsx
<div style={{ overflowX: 'auto' }}>
  <table style={s.table}>
    {/* unchanged contents */}
  </table>
</div>
```

- [ ] **Step 4: Verify**

```bash
cd frontend && npm run dev
```

Navigate to Cost or Latency on mobile:
- Outer padding is 16px (tighter than desktop)
- Project and run selects stack vertically
- Model breakdown table scrolls horizontally if wider than viewport
- Stats row wraps naturally (already had `flexWrap: wrap`)

On desktop: layout unchanged.

- [ ] **Step 5: Run existing tests**

```bash
cd frontend && npm test
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/MetricsView.jsx
git commit -m "feat: mobile MetricsView — tighter padding, stacked selects, table scroll"
```

---

## Final Verification

- [ ] Run full test suite

```bash
cd frontend && npm test
```

Expected: all tests pass with no regressions.

- [ ] Test all views on mobile (390px DevTools viewport):
  - Main page: form + globe side-by-side at top, pipeline below, output below that
  - Hamburger opens with all nav items, status chip visible
  - Evaluations: RunPreviewPanel on top, EvaluatePanel below
  - Cost page: tighter layout, selects stack, table scrolls
  - Latency page: same as Cost

- [ ] Test desktop at full width: all layouts unchanged from before this feature
