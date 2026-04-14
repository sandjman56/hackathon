/**
 * BrainScanner "/ingest-ecfr <title> <part> [date]" command.
 *
 * Parses args, captures a pre-POST baseline of the matching regulatory_sources
 * row (if any), POSTs to /api/regulations/sources/ecfr, then polls the sources
 * listing every POLL_MS until the row's embedding_started_at differs from the
 * baseline AND status is `ready` or `failed`. The baseline check prevents a
 * stale pre-existing row from being reported as success on re-ingest.
 * All progress is emitted as BrainScanner log entries via the provided
 * `pushLog({ ts, level, logger, msg })` callback.
 */

const apiBase = import.meta.env.VITE_API_URL ?? ''
const LOGGER = 'eia.cli.ecfr'
const POLL_MS = 3000
const POLL_TIMEOUT_MS = 10 * 60 * 1000

// Module-level guard: reject concurrent /ingest-ecfr runs for the same
// (title, part). Two simultaneous runs would race on the same backend row and
// their pollers would interleave log lines in confusing ways.
const activeKeys = new Set()
const keyFor = (title, part) => `${title}/${part}`

const now = () => Date.now() / 1000

async function fetchMatchingSource(title, part) {
  const res = await fetch(`${apiBase}/api/regulations/sources`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const body = await res.json()
  return (
    (body.sources || []).find(
      (s) => s.cfr_title === title && String(s.cfr_part) === String(part),
    ) || null
  )
}

// See EcfrIngestModal.jsx for the reasoning: embedding_started_at is reset on
// upsert_ecfr_source and bumped on every ingest start, so inequality reliably
// signals that a new run has begun.
function isFreshRow(row, baseline) {
  if (!baseline) return true
  return row.embedding_started_at !== baseline.embedding_started_at
}

export async function runEcfrIngestCommand(rawCmd, pushLog) {
  const parsed = parseCommand(rawCmd)
  if (parsed.error) {
    pushLog({ ts: now(), level: 'ERROR', logger: LOGGER, msg: parsed.error })
    return
  }
  const { title, part, date } = parsed

  const key = keyFor(title, part)
  if (activeKeys.has(key)) {
    pushLog({
      ts: now(), level: 'ERROR', logger: LOGGER,
      msg: `ingest already running for title=${title} part=${part} — wait for it to finish`,
    })
    return
  }
  activeKeys.add(key)

  try {
    pushLog({
      ts: now(), level: 'INFO', logger: LOGGER,
      msg: `POST /api/regulations/sources/ecfr title=${title} part=${part}${date ? ` date=${date}` : ''}`,
    })

    let baseline
    try {
      baseline = await fetchMatchingSource(title, part)
    } catch (e) {
      pushLog({
        ts: now(), level: 'ERROR', logger: LOGGER,
        msg: `baseline fetch failed: ${e.message}`,
      })
      return
    }

    let cid
    try {
      const body = { title, part }
      if (date) body.date = date
      const res = await fetch(`${apiBase}/api/regulations/sources/ecfr`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        pushLog({
          ts: now(), level: 'ERROR', logger: LOGGER,
          msg: `HTTP ${res.status}: ${text || res.statusText}`,
        })
        return
      }
      const data = await res.json()
      cid = data.correlation_id
      pushLog({
        ts: now(), level: 'INFO', logger: LOGGER,
        msg: `accepted cid=${cid} — polling every ${POLL_MS / 1000}s`,
      })
    } catch (e) {
      pushLog({ ts: now(), level: 'ERROR', logger: LOGGER, msg: `network error: ${e.message}` })
      return
    }

    const deadline = Date.now() + POLL_TIMEOUT_MS
    let lastStatus = null
    while (Date.now() < deadline) {
      await sleep(POLL_MS)
      let row
      try {
        row = await fetchMatchingSource(title, part)
      } catch {
        continue
      }
      if (!row) continue

      const fresh = isFreshRow(row, baseline)
      if (row.status !== lastStatus) {
        pushLog({
          ts: now(), level: 'INFO', logger: LOGGER,
          msg: fresh
            ? `status=${row.status} chunks=${row.chunk_count ?? 0}`
            : `status=${row.status} (stale) — waiting for re-ingest to begin`,
        })
        lastStatus = row.status
      }

      if (!fresh) continue

      if (row.status === 'ready') {
        pushLog({
          ts: now(), level: 'INFO', logger: LOGGER,
          msg: `✓ ingest complete — ${row.chunk_count ?? 0} chunks, source_id=${row.id}`,
        })
        return
      }
      if (row.status === 'failed') {
        pushLog({
          ts: now(), level: 'ERROR', logger: LOGGER,
          msg: `✗ ingest failed — ${row.error_message || 'see regulatory_ingest_log'}`,
        })
        return
      }
    }

    pushLog({
      ts: now(), level: 'WARNING', logger: LOGGER,
      msg: `poll timed out after ${POLL_TIMEOUT_MS / 1000}s — check regulatory_ingest_log cid=${cid}`,
    })
  } finally {
    activeKeys.delete(key)
  }
}

function parseCommand(raw) {
  // /ingest-ecfr <title> <part> [date]
  const parts = raw.trim().split(/\s+/)
  if (parts[0] !== '/ingest-ecfr') {
    return { error: `not an /ingest-ecfr command: ${raw}` }
  }
  if (parts.length < 3 || parts.length > 4) {
    return { error: 'usage: /ingest-ecfr <title> <part> [date]  (e.g. /ingest-ecfr 36 800)' }
  }
  const title = Number(parts[1])
  if (!Number.isInteger(title) || title < 1 || title > 50) {
    return { error: `bad title: "${parts[1]}" — must be an integer 1-50` }
  }
  const part = parts[2]
  if (!part) return { error: 'bad part: empty' }
  const date = parts[3] // optional; backend accepts "current" or ISO YYYY-MM-DD
  return { title, part, date }
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms))
}
