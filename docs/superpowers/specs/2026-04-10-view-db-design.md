# View DB Feature — Design Spec

**Date:** 2026-04-10
**Status:** Approved

## Overview

Add a "VIEW DB" button to the EIA Agent header bar (left of "Gemini") that navigates to a database browser view. Users can see all tables in their Render Postgres database as cards with metadata, drill into any table to see paginated rows/columns, and clear all data from a table.

## Navigation

Simple state toggle in `App.jsx` — no router library. A `view` state switches between `"main"` (pipeline) and `"db"` (database browser).

```
Main App → [VIEW DB button] → DatabaseView (table cards grid)
                               → [click card] → TableDetail (paginated rows + clear)
                               → [back] → DatabaseView
         ← [back] ← DatabaseView
```

## Backend

Three new endpoints added to `backend/main.py`, using the existing `_get_connection()` pattern from `db/vector_store.py`.

### `GET /api/db/tables`

Returns all user tables with metadata.

**Response:**
```json
[
  { "name": "projects", "row_count": 12, "column_count": 5 },
  { "name": "documents", "row_count": 340, "column_count": 4 }
]
```

**Implementation:** Query `information_schema.tables` for table names (filtered to `public` schema, excluding system tables), then for each table get column count from `information_schema.columns` and row count via `SELECT count(*)`.

### `GET /api/db/tables/{table_name}?page=1&per_page=25`

Returns paginated rows and column info for a specific table.

**Response:**
```json
{
  "table_name": "projects",
  "columns": [
    { "name": "id", "type": "uuid" },
    { "name": "name", "type": "text" },
    { "name": "coordinates", "type": "text" },
    { "name": "description", "type": "text" },
    { "name": "saved_at", "type": "timestamp with time zone" }
  ],
  "rows": [
    ["abc-123", "My Project", "40.44,-79.99", "Description", "2026-04-10T..."],
    ["def-456", "Other Project", "38.90,-77.03", "Desc 2", "2026-04-09T..."]
  ],
  "total_rows": 12,
  "page": 1,
  "per_page": 25,
  "total_pages": 1
}
```

**Implementation:** Validate `table_name` against actual table names from `information_schema.tables` (whitelist — prevents SQL injection). Query columns from `information_schema.columns`. Fetch rows with `LIMIT/OFFSET`. Serialize all values to strings for JSON safety (UUIDs, timestamps, bytea, etc.).

### `DELETE /api/db/tables/{table_name}/rows`

Truncates all rows from the table, preserving the schema.

**Response:**
```json
{ "table_name": "projects", "deleted_count": 12 }
```

**Implementation:** Validate table name against whitelist. Get row count first, then execute `TRUNCATE {table_name} CASCADE`. CASCADE handles foreign key references.

### SQL injection prevention

All three endpoints validate the `table_name` parameter against the actual list of tables from `information_schema.tables` before using it in any query. Table names are never interpolated from user input without this validation.

## Frontend

### App.jsx changes

- Add `view` state: `useState('main')`
- Add "VIEW DB" button in header, to the left of "Gemini" badge
- Button styled like the existing "VIEW SOURCES" button (outlined, green border, monospace)
- When `view === 'db'`, render `<DatabaseView onBack={() => setView('main')} />` instead of the 3-column layout

### DatabaseView.jsx

Grid of table cards with a back button.

**State:**
- `tables` — array of table objects from `/api/db/tables`
- `loading` — boolean
- `selectedTable` — string or null (when set, renders TableDetail instead of grid)

**Layout:**
- Top bar: back arrow button + "DATABASE" title
- Grid of cards (CSS grid, responsive columns)
- Each card shows:
  - Table name (monospace, green)
  - Row count
  - Column count

**On mount:** Fetch `GET /api/db/tables`, populate cards.

**On card click:** Set `selectedTable` to table name, render `TableDetail`.

### TableDetail.jsx

Paginated table view with clear functionality.

**State:**
- `data` — response from `/api/db/tables/{name}`
- `loading` — boolean
- `page` — current page number
- `confirmClear` — boolean for confirmation step

**Layout:**
- Top bar: back arrow + table name + row count badge
- Scrollable table container with horizontal scroll for wide tables
- Column headers showing name and type
- Data rows with alternating tint for readability
- All values displayed as strings
- Long values truncated with ellipsis (max ~100 chars in cell)

**Pagination controls (bottom):**
- Previous / Next buttons
- "Page X of Y" indicator
- 25 rows per page

**Clear button:**
- Red-styled "CLEAR TABLE" button
- First click: button changes to "ARE YOU SURE? DELETE ALL X ROWS" (confirmation)
- Second click: sends `DELETE /api/db/tables/{name}/rows`, refreshes view
- Click elsewhere or wait 3s: reverts to normal state

**On mount / page change:** Fetch `GET /api/db/tables/{name}?page={page}&per_page=25`.

## Styling

All components use inline styles with CSS custom variables, matching the existing codebase pattern.

- Cards: `--bg-card` background, `--border` border, hover glow effect
- Table headers: `--bg-secondary` background, `--text-secondary` color
- Table rows: alternating between `--bg-card` and slightly lighter
- Buttons: green outlined (VIEW DB, pagination), red outlined (CLEAR TABLE)
- Monospace font (`--font-mono`) for table data and names
- Back button: simple arrow with hover effect

## Error handling

- Network errors show inline error message (red text, retry button)
- Empty tables show "No rows" message
- Clear confirmation prevents accidental data loss

## Files changed

| File | Change |
|------|--------|
| `backend/main.py` | Add 3 new endpoints |
| `frontend/src/App.jsx` | Add view state, VIEW DB button, conditional rendering |
| `frontend/src/components/DatabaseView.jsx` | New file — table cards grid |
| `frontend/src/components/TableDetail.jsx` | New file — paginated rows + clear |
