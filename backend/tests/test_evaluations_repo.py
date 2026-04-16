from db.evaluations import (
    delete_evaluation,
    get_evaluation_by_id,
    get_evaluation_by_sha,
    get_evaluation_bytes,
    init_evaluations_schema,
    insert_evaluation,
    list_evaluations,
    mark_stuck_evaluations_failed,
    reset_evaluation_for_reingest,
    update_evaluation_progress,
    update_evaluation_status,
)


def test_init_schema_is_idempotent(db_conn):
    init_evaluations_schema(db_conn)
    init_evaluations_schema(db_conn)
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
             WHERE table_schema='public' AND table_name='evaluations'
        """)
        cols = {r[0] for r in cur.fetchall()}
    for expected in {"id", "filename", "sha256", "size_bytes", "blob",
                     "uploaded_at", "status", "status_message",
                     "chunks_total", "chunks_embedded", "sections_count",
                     "embedding_dim", "started_at", "finished_at"}:
        assert expected in cols, f"missing column: {expected}"


def test_insert_get_and_dedupe(db_conn):
    init_evaluations_schema(db_conn)
    row = insert_evaluation(
        db_conn, filename="a.pdf", sha256="sha-1", size_bytes=10, blob=b"X",
    )
    assert row["status"] == "pending"
    again = insert_evaluation(
        db_conn, filename="a.pdf", sha256="sha-1", size_bytes=10, blob=b"X",
    )
    assert again["id"] == row["id"]

    fetched = get_evaluation_by_id(db_conn, row["id"])
    assert fetched["filename"] == "a.pdf"

    by_sha = get_evaluation_by_sha(db_conn, "sha-1")
    assert by_sha["id"] == row["id"]

    blob = get_evaluation_bytes(db_conn, row["id"])
    assert blob == b"X"

    rows = list_evaluations(db_conn)
    assert any(r["id"] == row["id"] for r in rows)


def test_status_and_progress_updates(db_conn):
    init_evaluations_schema(db_conn)
    row = insert_evaluation(db_conn, filename="p.pdf", sha256="sha-p",
                            size_bytes=5, blob=b"Y")
    update_evaluation_status(db_conn, row["id"], status="embedding",
                             chunks_total=10, sections_count=3, embedding_dim=8,
                             started_at_now=True)
    update_evaluation_progress(db_conn, row["id"], chunks_embedded=5)
    update_evaluation_status(db_conn, row["id"], status="ready", finished_at_now=True)
    final = get_evaluation_by_id(db_conn, row["id"])
    assert final["status"] == "ready"
    assert final["chunks_total"] == 10
    assert final["chunks_embedded"] == 5
    assert final["started_at"] is not None
    assert final["finished_at"] is not None


def test_reset_for_reingest(db_conn):
    init_evaluations_schema(db_conn)
    row = insert_evaluation(db_conn, filename="r.pdf", sha256="sha-r",
                            size_bytes=5, blob=b"Z")
    update_evaluation_status(db_conn, row["id"], status="failed",
                             status_message="boom", chunks_total=7,
                             chunks_embedded=3)
    reset_evaluation_for_reingest(db_conn, row["id"])
    reset = get_evaluation_by_id(db_conn, row["id"])
    assert reset["status"] == "pending"
    assert reset["status_message"] is None
    assert reset["chunks_total"] == 0
    assert reset["chunks_embedded"] == 0


def test_mark_stuck(db_conn):
    init_evaluations_schema(db_conn)
    r1 = insert_evaluation(db_conn, filename="s1.pdf", sha256="sha-s1",
                           size_bytes=5, blob=b"A")
    r2 = insert_evaluation(db_conn, filename="s2.pdf", sha256="sha-s2",
                           size_bytes=5, blob=b"B")
    update_evaluation_status(db_conn, r1["id"], status="embedding",
                             chunks_total=5)
    # r2 stays 'pending'

    swept = mark_stuck_evaluations_failed(db_conn)
    assert swept == 2
    r1_after = get_evaluation_by_id(db_conn, r1["id"])
    assert r1_after["status"] == "failed"
    assert "interrupted" in (r1_after["status_message"] or "").lower()
    r2_after = get_evaluation_by_id(db_conn, r2["id"])
    assert r2_after["status"] == "failed"


def test_delete_evaluation_returns_count(db_conn):
    init_evaluations_schema(db_conn)
    row = insert_evaluation(db_conn, filename="d.pdf", sha256="sha-d",
                            size_bytes=5, blob=b"C")
    assert delete_evaluation(db_conn, row["id"]) == 1
    assert delete_evaluation(db_conn, row["id"]) == 0
