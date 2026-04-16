from rag.evaluation.chunker import EisChunk
from rag.evaluation.parser import RawEisSection
from rag.evaluation.store import (
    build_eis_metadata,
    init_evaluation_chunks_table,
    search_evaluation_chunks,
    upsert_evaluation_chunks,
)


def _make_eval_row(conn, filename="test.pdf", sha="abc"):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO evaluations (filename, sha256, size_bytes, blob) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (filename, sha, 10, b"dummy"),
        )
        return cur.fetchone()[0]


def _make_chunk(section_number="4.1", body="body text") -> EisChunk:
    section = RawEisSection(
        chapter="4",
        section_number=section_number,
        section_title="Water",
        breadcrumb=f"Chapter 4 > {section_number} Water",
        body=body, page_start=1, page_end=2,
    )
    return EisChunk(source=section, body=body, chunk_index=0,
                    total_chunks_in_section=1, token_count=2)


def _ensure_evaluations_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS evaluations (
                id SERIAL PRIMARY KEY,
                filename TEXT,
                sha256 TEXT UNIQUE,
                size_bytes INTEGER,
                blob BYTEA,
                uploaded_at TIMESTAMPTZ DEFAULT now()
            )
        """)


def test_init_table_creates_schema(db_conn):
    _ensure_evaluations_table(db_conn)
    init_evaluation_chunks_table(db_conn, embedding_dim=8)
    with db_conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.evaluation_chunks')")
        assert cur.fetchone()[0] == "evaluation_chunks"


def test_upsert_and_search_scoped_to_evaluation(db_conn):
    _ensure_evaluations_table(db_conn)
    init_evaluation_chunks_table(db_conn, embedding_dim=4)

    eid_a = _make_eval_row(db_conn, filename="a.pdf", sha="sha-a")
    eid_b = _make_eval_row(db_conn, filename="b.pdf", sha="sha-b")

    c = _make_chunk()
    meta = build_eis_metadata(
        c, breadcrumb=c.source.breadcrumb,
        evaluation_id=eid_a, filename="a.pdf", sha256="sha-a",
        chunk_label="a §4.1 [p.1-2] (1/1)",
    )
    rows = [(c, c.source.breadcrumb, [0.1, 0.2, 0.3, 0.4], meta)]
    written = upsert_evaluation_chunks(db_conn, rows, evaluation_id=eid_a)
    assert written == 1

    c2 = _make_chunk(body="body text B")
    meta2 = build_eis_metadata(
        c2, breadcrumb=c2.source.breadcrumb,
        evaluation_id=eid_b, filename="b.pdf", sha256="sha-b",
        chunk_label="a §4.1 [p.1-2] (1/1)",
    )
    upsert_evaluation_chunks(
        db_conn,
        [(c2, c2.source.breadcrumb, [0.5, 0.5, 0.5, 0.5], meta2)],
        evaluation_id=eid_b,
    )

    results = search_evaluation_chunks(db_conn, [0.1, 0.2, 0.3, 0.4],
                                       evaluation_id=eid_a, top_k=5)
    assert len(results) == 1
    assert results[0]["metadata"]["evaluation_id"] == eid_a

    results_b = search_evaluation_chunks(db_conn, [0.5, 0.5, 0.5, 0.5],
                                         evaluation_id=eid_b, top_k=5)
    assert len(results_b) == 1
    assert results_b[0]["metadata"]["evaluation_id"] == eid_b


def test_cascade_delete_removes_chunks(db_conn):
    _ensure_evaluations_table(db_conn)
    init_evaluation_chunks_table(db_conn, embedding_dim=4)
    eid = _make_eval_row(db_conn, sha="sha-x")

    c = _make_chunk()
    meta = build_eis_metadata(
        c, breadcrumb=c.source.breadcrumb,
        evaluation_id=eid, filename="t.pdf", sha256="sha-x",
        chunk_label="L1",
    )
    upsert_evaluation_chunks(
        db_conn,
        [(c, c.source.breadcrumb, [0.0, 0.0, 0.0, 0.0], meta)],
        evaluation_id=eid,
    )

    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM evaluations WHERE id = %s", (eid,))
        cur.execute("SELECT COUNT(*) FROM evaluation_chunks WHERE evaluation_id = %s",
                    (eid,))
        assert cur.fetchone()[0] == 0
