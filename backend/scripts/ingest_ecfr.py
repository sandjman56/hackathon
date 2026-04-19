"""CLI: ingest one or more CFR parts from the eCFR Versioner API.

Usage:
    python -m scripts.ingest_ecfr --title 36 --part 800
    python -m scripts.ingest_ecfr --from-file parts.yaml
    python -m scripts.ingest_ecfr --title 36 --part 800 --dry-run

Exit codes:
    0 = all ingests succeeded
    1 = argparse / environment error
    2 = one or more ingests failed (batch mode reports per-item)
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Any

# Allow `python backend/scripts/ingest_ecfr.py` from repo root.
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import httpx
import yaml

from api_clients.ecfr import fetch_ecfr_xml, resolve_current_date
from db.vector_store import _get_connection
from llm.provider_factory import get_embedding_provider
from rag.regulatory.chunker import chunk_sections
from rag.regulatory.parser_ecfr import parse_ecfr_xml
from services.ecfr_ingest import ingest_ecfr_source

logger = logging.getLogger("scripts.ingest_ecfr")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Ingest a CFR part (or a batch) via the eCFR Versioner API."
    )
    p.add_argument("--title", type=int, help="CFR title number (e.g. 36)")
    p.add_argument("--part", type=str, help="CFR part identifier (e.g. '800')")
    p.add_argument("--date", type=str, default="current",
                   help="ISO YYYY-MM-DD or 'current' (default)")
    p.add_argument("--from-file", type=str,
                   help="Path to YAML list [{title, part, date?}]")
    p.add_argument("--dry-run", action="store_true",
                   help="Fetch + parse only; do not write DB or embed")
    return p.parse_args(argv)


def _run_dry(title: int, part: str, date: str) -> int:
    cid = uuid.uuid4().hex[:8]
    print(f"[cid={cid}] DRY RUN: fetching title-{title} part {part} @ {date}")
    with httpx.Client() as client:
        resolved = resolve_current_date(title=title, client=client, correlation_id=cid) \
            if date == "current" else date
        xml = fetch_ecfr_xml(title=title, part=part, date=resolved,
                             client=client, correlation_id=cid)
    sections, warnings = parse_ecfr_xml(xml)
    chunks = chunk_sections(sections)
    print(f"  sections: {len(sections)}")
    print(f"  chunks:   {len(chunks)}")
    print(f"  warnings: {len(warnings)}")
    if warnings:
        for w in warnings[:5]:
            print(f"    - {w}")
        if len(warnings) > 5:
            print(f"    (+{len(warnings)-5} more)")
    return 0


def _run_one(
    conn: Any, *, title: int, part: str, date: str,
    embedding_provider: Any,
) -> str:
    return ingest_ecfr_source(
        conn,
        title=title, part=part, date=date,
        embedding_provider=embedding_provider,
        correlation_id=uuid.uuid4().hex[:8],
        trigger="cli",
    )


def _run_batch(
    conn: Any, entries: list[dict], embedding_provider: Any,
) -> tuple[list[tuple[int, str, str]], list[tuple[int, str, str]]]:
    successes: list[tuple[int, str, str]] = []
    failures: list[tuple[int, str, str]] = []
    for idx, entry in enumerate(entries):
        # Best-effort labels in case extraction fails below.
        label_title: Any = entry.get("title", "?") if isinstance(entry, dict) else "?"
        label_part: str = str(entry.get("part", "?")) if isinstance(entry, dict) else "?"
        try:
            if not isinstance(entry, dict):
                raise ValueError(f"entry #{idx} is not a mapping: {entry!r}")
            if "title" not in entry or "part" not in entry:
                raise ValueError(f"entry #{idx} missing title/part: {entry!r}")
            title = int(entry["title"])
            part = str(entry["part"])
            date = str(entry.get("date", "current"))
            t0 = time.time()
            sid = _run_one(conn, title=title, part=part, date=date,
                           embedding_provider=embedding_provider)
            elapsed = time.time() - t0
            print(f"  OK  title-{title} part {part} ({elapsed:.1f}s) -> {sid}")
            successes.append((title, part, sid))
        except Exception as exc:
            try:
                rec_title = int(label_title)
            except (TypeError, ValueError):
                rec_title = -1
            rec_part = str(label_part)
            print(f"  FAIL title-{label_title} part {label_part}: {type(exc).__name__}: {exc}")
            failures.append((rec_title, rec_part, f"{type(exc).__name__}: {exc}"))
    return successes, failures


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse_args(sys.argv[1:])

    if args.from_file and (args.title is not None or args.part is not None):
        print("--from-file is mutually exclusive with --title/--part", file=sys.stderr)
        return 1

    if args.dry_run:
        if not (args.title and args.part):
            print("--dry-run requires --title and --part", file=sys.stderr)
            return 1
        return _run_dry(args.title, args.part, args.date)

    conn = _get_connection()
    try:
        embedding_provider = get_embedding_provider()
        if args.from_file:
            entries = yaml.safe_load(Path(args.from_file).read_text())
            if not isinstance(entries, list):
                print("--from-file must contain a YAML list", file=sys.stderr)
                return 1
            print(f"Batch ingest: {len(entries)} parts")
            successes, failures = _run_batch(conn, entries, embedding_provider)
            print(f"\nDone: {len(successes)} succeeded, {len(failures)} failed")
            return 2 if failures else 0

        if not (args.title and args.part):
            print("must supply --title + --part (or --from-file)", file=sys.stderr)
            return 1
        sid = _run_one(
            conn, title=args.title, part=args.part, date=args.date,
            embedding_provider=embedding_provider,
        )
        print(f"OK -> source_id={sid}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
