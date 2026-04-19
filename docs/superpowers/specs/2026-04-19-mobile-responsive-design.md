# Mobile Responsive Design

**Date:** 2026-04-19  
**Scope:** `App.jsx`, `EvaluationsView.jsx`, `MetricsView.jsx`, new `useIsMobile` hook  
**Breakpoint:** 768px (mobile = max-width 768px)  
**Also includes:** Desktop globe enlargement

---

## Problem

On mobile the app is unusable: the navbar overflows the screen, the 3-column main layout renders in a tiny horizontal scroll, and the split panes in Evaluations are inaccessible.

---

## Approach

Use a `useIsMobile()` hook (Option A). Each affected component calls the hook and switches between two sets of inline style objects — no new CSS files, no class names, no Tailwind. Stays 100% within the existing inline-style pattern.

---

## 1. `useIsMobile` Hook

**File:** `frontend/src/hooks/useIsMobile.js`

- Uses `window.matchMedia('(max-width: 768px)')` 
- Attaches a `change` event listener to stay reactive on resize
- Returns a single `boolean`

---

## 2. Navbar (App.jsx header)

**Desktop:** unchanged.

**Mobile:**
- Left side: logo SVG icon + "CLEAVER" text. Subtitle (`Customized Environmental Impact Reports`) hidden.
- Right side: single hamburger button (≡ icon, same monospace/green style as existing buttons)
- Clicking hamburger toggles `mobileMenuOpen` state
- Dropdown renders below header (full width, `position: absolute`, `z-index: 100`) containing:
  - Status chip (full display)
  - PIPELINE EVALS → sets `view = 'evaluations'`, closes menu
  - COST → sets `view = 'cost'`, closes menu
  - LATENCY → sets `view = 'latency'`, closes menu
  - VIEW DB → sets `view = 'db'`, closes menu
- Clicking outside closes the menu (reuse existing `handleOutside` pattern with a new ref)

---

## 3. Main Page Layout (App.jsx)

**Desktop:** unchanged (3 columns, horizontal flex).

**Mobile:** `styles.main` becomes `flexDirection: 'column'`, `overflowY: 'auto'`, `height: 'auto'`.

Three stacked sections separated by horizontal dividers (`height: 1px, background: var(--border)`):

### Section 1 — Input Row (top)
- `display: flex`, `flexDirection: 'row'`, `height: ~60vh`
- Left (60%): ProjectForm with `overflowY: auto`
- Right (40%): Globe stacked above BrainScanner, each `flex: 1`, `overflowY: hidden`
- No separator between left and right — columns are visually distinct by content

### Section 2 — Pipeline Status
- Full width, `padding: 16px`
- AgentPipeline component, `overflowY: auto`

### Section 3 — Output
- Full width, `padding: 16px`
- ResultsPanel + Save button, `overflowY: auto`

The vertical separators (`styles.separator`) are hidden on mobile; replaced by horizontal dividers between the three sections.

---

## 3b. Desktop Globe Enlargement (App.jsx)

The right column currently splits `globeWrapper` and `brainScannerWrapper` at `flex: 1` each (50/50). The globe size is computed as `Math.min(containerWidth, containerHeight)` — so giving the globe more vertical space directly increases its rendered size.

**Change:** `globeWrapper` → `flex: 3`, `brainScannerWrapper` → `flex: 2`. This gives the globe 60% of the right column height instead of 50%, producing a noticeably larger rendered globe while keeping the BrainScanner visible below.

Also change `globeWrapper` alignment from `justifyContent: flex-end, alignItems: flex-start` to `justifyContent: center, alignItems: center` so the larger globe is centered in its space rather than tucked to the top-right corner.

Desktop only — mobile layout handles the right column separately.

---

## 4. Evaluations Page (EvaluationsView.jsx)

**Desktop:** unchanged (horizontal drag split pane).

**Mobile:**
- Upload zone + doc table at top (unchanged, full width)
- `splitContainer` becomes `flexDirection: 'column'` instead of `'row'`
- `splitLeft` (RunPreviewPanel): full width, `maxHeight: 50vh`, `overflowY: auto`
- Horizontal divider (1px)
- `splitRight` (EvaluatePanel): full width, `maxHeight: 50vh`, `overflowY: auto`
- `splitHandle` (drag bar) hidden on mobile (`display: 'none'`)
- Mouse drag listeners still mount but have no visual affordance (harmless)

---

## 5. Metrics Page (MetricsView.jsx)

**Desktop:** unchanged.

**Mobile:**
- Outer padding reduced: `24px 32px` → `16px`
- Stats row already has `flexWrap: wrap` — no change needed
- Chart container already has `overflowX: auto` — no change needed
- Model breakdown table (`<table>`) wrapped in a `div` with `overflowX: auto`
- Run drill-down selects: container switches to `flexDirection: 'column'`, `gap: 8px` so the two `<select>` elements stack vertically

---

## Files Changed

| File | Change |
|------|--------|
| `frontend/src/hooks/useIsMobile.js` | New file |
| `frontend/src/App.jsx` | Mobile navbar (hamburger) + mobile main layout + desktop globe enlargement |
| `frontend/src/components/EvaluationsView.jsx` | Mobile stacked split pane |
| `frontend/src/pages/MetricsView.jsx` | Mobile padding + table scroll + stacked selects |

---

## Out of Scope

- Touch-optimized drag-to-resize in Evaluations (removed on mobile, not replaced)
- Tablet breakpoints (768px is the only breakpoint)
- Other pages (DatabaseView, EvaluationChunksView, ProjectForm internals)
