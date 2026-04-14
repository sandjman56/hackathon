# eCFR Ingest — Operator Guide

This document covers how to ingest CFR parts from the [eCFR Versioner API](https://www.ecfr.gov/developers/documentation/api/v1) into the regulatory RAG store.

## Prerequisites

- `DATABASE_URL` set to a Postgres connection string with `CREATE EXTENSION` privileges (pgvector required)
- `init_db()` applied (happens automatically on backend startup)
- An embedding provider configured — the backend picks one up via `get_embedding_provider()`
- Python env from `backend/requirements.txt` installed; `pyyaml` required for batch mode

## CLI usage

```bash
cd backend
python -m scripts.ingest_ecfr --title 36 --part 800
python -m scripts.ingest_ecfr --title 23 --part 771 --date 2024-06-15
python -m scripts.ingest_ecfr --title 36 --part 800 --dry-run
python -m scripts.ingest_ecfr --from-file parts.yaml
```

### Flags

| Flag | Required | Description |
|---|---|---|
| `--title N` | with `--part` | CFR title number (1–50) |
| `--part P` | with `--title` | CFR part identifier (string — suffixes allowed) |
| `--date D` | no | `current` (default) or ISO `YYYY-MM-DD` snapshot |
| `--from-file PATH` | either/or | YAML list of `{title, part, date?}` objects |
| `--dry-run` | no | fetch + parse only, no DB writes, no embedding |

### Batch YAML format

```yaml
- title: 23
  part: "771"
- title: 36
  part: "800"
- title: 33
  part: "323"
```

Batch failures do not halt the run. Per-item results print at the end.

### Exit codes

- `0` — all ingests succeeded
- `1` — argparse / environment error
- `2` — one or more ingests failed

## HTTP endpoint usage

```bash
curl -sS -XPOST http://localhost:8000/api/regulations/sources/ecfr \
  -H 'content-type: application/json' \
  -d '{"title":36,"part":"800"}'
```

Response (HTTP 202):

```json
{
  "source_id": null,
  "correlation_id": "a1b2c3d4",
  "status": "pending",
  "message": "eCFR ingest started for title 36 part 800; poll GET /api/regulations/sources and match on cfr_title=36, cfr_part='800' to see status transition to 'ready' or 'failed'."
}
```

Poll:

```bash
curl -sS http://localhost:8000/api/regulations/sources \
  | jq '.sources[] | select(.cfr_title==36 and .cfr_part=="800")'
```

Interactive docs: <http://localhost:8000/docs> (Swagger UI).

### HTTP error responses

| Status | Cause |
|---|---|
| 422 | Pydantic validation (bad `title`, `part`, or `date` format) |
| 502 | eCFR API unreachable after retries |
| 500 | DB error during upsert |

## How to verify an ingest succeeded

1. Check `GET /api/regulations/sources` — the row's `status` becomes `ready`, `chunk_count` > 0
2. Check `regulatory_ingest_log` for a matching `correlation_id` — should have a `started` row and a `ready` row

   ```bash
   psql $DATABASE_URL -c "SELECT ts, correlation_id, trigger, cfr_title, cfr_part, status, chunks_count FROM regulatory_ingest_log WHERE source_type='ecfr' ORDER BY ts DESC LIMIT 10;"
   ```
3. Open the Database viewer UI → `regulatory_chunks` → filter by source → content renders

## Re-ingestion semantics

Re-running with the same `(title, part, date)` tuple **updates the existing row in place**. The row id stays stable; old chunks are cascade-deleted and replaced with freshly embedded ones. No orphaned data.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| 404 from eCFR on a `current` fetch | The date-resolution spike returned an invalid date, or `content_versions` is empty | Run `resolve_current_date` manually in a Python shell; check the Versioner API response |
| `unexpected content-type` RuntimeError | eCFR returned HTML (maintenance page or rate limit) | Retry after a minute; the client already retries 2× automatically |
| Sections count = 0 | Part number doesn't exist in that title at that date | Verify with `curl https://www.ecfr.gov/api/versioner/v1/titles.json` |
| FK violation on `regulatory_chunks.source_id` | Pre-Phase-1 row in `regulatory_chunks` with no typed `source_id` | Re-run `init_db()`; the backfill is idempotent |

## Adding a new source type (Phase 2+)

Follow the established layout (see `docs/superpowers/specs/2026-04-14-phase-1-ecfr-pipeline-design.md` §Agent-Friendliness):

1. Create `backend/api_clients/{source}.py` with a `fetch_{source}_...` function (mirror `api_clients/ecfr.py`)
2. Create `backend/rag/regulatory/parser_{source}.py` returning `tuple[list[RawSection], list[str]]`
3. Create `backend/services/{source}_ingest.py` with `ingest_{source}_source(...)`
4. Add a new branch in `detect_parser` keyed on the appropriate `content_type`
5. Add a new branch in `ingest_source_sync` dispatching to the new parser
6. Add a CLI `backend/scripts/ingest_{source}.py`
7. Add a route `POST /api/regulations/sources/{source}`
8. Golden-file tests + HTTP client tests + orchestrator tests

When two or more source types share >40% of the client/parser code, extract a shared helper.
