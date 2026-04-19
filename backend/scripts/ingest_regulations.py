"""CLI: parse a regulatory PDF, chunk it, embed each chunk, store in pgvector.

Usage::

    python backend/scripts/ingest_regulations.py \\
        --pdf backend/NEPA-40CFR1500_1508.pdf \\
        --embedding-provider gemini \\
        --db-url $DATABASE_URL

    # Inspect the chunking output without touching the DB:
    python backend/scripts/ingest_regulations.py \\
        --pdf backend/NEPA-40CFR1500_1508.pdf --dry-run

The ``--source-id`` flag tags every chunk so the same DB can hold multiple
corpora (40 CFR, NEPA statute, future state docs) without collisions.
"""
from __future__ import annotations

import asyncio
import logging
import os
import statistics
import sys
from collections import Counter
from pathlib import Path

# Allow `python backend/scripts/ingest_regulations.py` from repo root.
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import click  # noqa: E402
import psycopg2  # noqa: E402

from rag.regulatory.chunker import chunk_sections, MAX_TOKENS, MIN_TOKENS  # noqa: E402
from rag.regulatory.embedder import (  # noqa: E402
    detect_embedding_dimension,
    embed_chunks,
)
from rag.regulatory.parser import DocumentType, parse_pdf  # noqa: E402
from rag.regulatory.store import (  # noqa: E402
    build_metadata,
    init_regulatory_table,
    upsert_chunks,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
)
logger = logging.getLogger("eia.scripts.ingest_regulations")


@click.command()
@click.option(
    "--pdf",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to the regulatory PDF.",
)
@click.option(
    "--source-id",
    default="40_CFR_1500-1508",
    show_default=True,
    help="Logical document identifier stored in metadata.source.",
)
@click.option(
    "--embedding-provider",
    type=click.Choice(["gemini", "openai", "ollama"]),
    default=None,
    help="Override EMBEDDING_PROVIDER env var. Defaults to gemini.",
)
@click.option(
    "--db-url",
    envvar="DATABASE_URL",
    help="PostgreSQL connection string. Required unless --dry-run.",
)
@click.option(
    "--is-current/--not-current",
    default=True,
    show_default=True,
    help=(
        "Mark this corpus as current authoritative law. Pass --not-current "
        "for superseded or historical versions (e.g. the 2005 reprint of "
        "the 1978 NEPA regs)."
    ),
)
@click.option(
    "--concurrency",
    default=4,
    show_default=True,
    type=int,
    help="Max in-flight embedding requests.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Parse + chunk + summarize, but skip embedding and DB writes.",
)
def main(
    pdf: Path,
    source_id: str,
    embedding_provider: str | None,
    db_url: str | None,
    is_current: bool,
    concurrency: int,
    dry_run: bool,
) -> None:
    """Ingest a regulatory PDF into the regulatory_chunks pgvector table."""
    logger.info("Parsing %s", pdf)
    sections, parser_warnings = parse_pdf(str(pdf))
    if parser_warnings:
        logger.warning("Parser produced %d warnings:", len(parser_warnings))
        for w in parser_warnings[:25]:
            logger.warning("  %s", w)

    chunks = chunk_sections(sections)
    _print_summary(sections, chunks, parser_warnings)

    if dry_run:
        click.echo("\n[dry-run] Skipping embedding and DB write.")
        return

    if not db_url:
        raise click.UsageError(
            "--db-url is required (or set DATABASE_URL) unless --dry-run."
        )

    if embedding_provider:
        os.environ["EMBEDDING_PROVIDER"] = embedding_provider

    # Imported lazily so --dry-run doesn't require Google API credentials.
    from llm.provider_factory import get_embedding_provider

    provider = get_embedding_provider()
    logger.info("Using embedding provider: %s", provider.provider_name)

    dim = detect_embedding_dimension(provider)
    logger.info("Detected embedding dimension: %d", dim)

    conn = psycopg2.connect(db_url)
    try:
        init_regulatory_table(conn, embedding_dim=dim)

        logger.info(
            "Embedding %d chunks (concurrency=%d)…", len(chunks), concurrency
        )
        embeddings = asyncio.run(
            embed_chunks(chunks, provider, concurrency=concurrency)
        )

        rows = []
        for chunk, (breadcrumb, vec) in zip(chunks, embeddings):
            meta = build_metadata(
                chunk,
                breadcrumb,
                source=source_id,
                source_file=pdf.name,
                is_current=is_current,
            )
            rows.append((chunk, breadcrumb, vec, meta))

        written = upsert_chunks(conn, rows)
        click.echo(f"\nWrote {written} chunks to regulatory_chunks.")
    finally:
        conn.close()


def _print_summary(sections, chunks, warnings) -> None:
    """Emit the size-distribution and per-Part counts the spec asks for."""
    cfr = [c for c in chunks if c.sources[0].document_type == DocumentType.CFR_REGULATION]
    statute = [c for c in chunks if c.sources[0].document_type == DocumentType.STATUTE]
    eo = [c for c in chunks if c.sources[0].document_type == DocumentType.EXECUTIVE_ORDER]

    by_part = Counter(c.sources[0].part for c in cfr if c.sources[0].part)
    splits = sum(1 for c in chunks if c.total_chunks_in_section > 1)
    merges = sum(1 for c in chunks if c.is_merged_siblings)
    defs = sum(1 for c in chunks if c.is_definition)

    toks = [c.token_count for c in chunks]
    quantiles = statistics.quantiles(toks, n=20) if len(toks) >= 20 else None
    p95 = int(quantiles[-1]) if quantiles else max(toks)

    click.echo("")
    click.echo("=" * 60)
    click.echo(f"Sections parsed: {len(sections)}")
    click.echo(f"Chunks emitted:  {len(chunks)}")
    click.echo(
        f"  CFR regulation: {len(cfr)}   "
        f"Statute: {len(statute)}   "
        f"Executive order: {len(eo)}"
    )
    click.echo(
        f"  split chunks: {splits}   "
        f"sibling-merged: {merges}   "
        f"definitions: {defs}"
    )
    click.echo("")
    click.echo("Chunks per CFR Part:")
    for part in sorted(by_part):
        click.echo(f"  Part {part}: {by_part[part]}")
    click.echo("")
    click.echo(
        f"Token distribution: "
        f"min={min(toks)} max={max(toks)} mean={int(statistics.mean(toks))} "
        f"median={int(statistics.median(toks))} p95={p95}"
    )
    over = [c for c in chunks if c.token_count > MAX_TOKENS]
    under = [
        c for c in chunks
        if c.token_count < MIN_TOKENS and not c.is_definition
    ]
    if over:
        click.echo(
            f"  ⚠ {len(over)} chunks > MAX_TOKENS ({MAX_TOKENS}): "
            + ", ".join(c.sources[0].citation for c in over[:5])
        )
    if under:
        click.echo(
            f"  ⚠ {len(under)} chunks < MIN_TOKENS ({MIN_TOKENS}) (non-def): "
            + ", ".join(c.sources[0].citation for c in under[:5])
        )
    click.echo(f"Parser warnings: {len(warnings)}")
    click.echo("=" * 60)


if __name__ == "__main__":
    main()
