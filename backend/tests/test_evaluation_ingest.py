import pytest

from db.evaluations import (
    get_evaluation_by_id,
    init_evaluations_schema,
    insert_evaluation,
)
from rag.evaluation.store import (
    count_chunks_for_evaluation,
    init_evaluation_chunks_table,
)
from services.evaluation_ingest import ingest_evaluation_sync
from tests.fixtures.eis.build_sample import build_sample_eis_bytes


class _StubProvider:
    provider_name = "stub"

    def __init__(self, dim=8):
        self.dim = dim
        self.calls = []

    def embed(self, text):
        self.calls.append(text)
        h = abs(hash(text)) % 1000
        return [(h + i) / 1000.0 for i in range(self.dim)]


@pytest.fixture
def prepared_db(db_conn):
    init_evaluations_schema(db_conn)
    init_evaluation_chunks_table(db_conn, embedding_dim=8)
    return db_conn


def test_ingest_end_to_end_happy_path(prepared_db, project_id):
    conn = prepared_db
    blob = build_sample_eis_bytes()
    row = insert_evaluation(conn, filename="sample.pdf", sha256="sha-ok",
                            size_bytes=len(blob), blob=blob, project_id=project_id)
    provider = _StubProvider(dim=8)

    ingest_evaluation_sync(conn, evaluation_id=row["id"],
                           embedding_provider=provider)

    final = get_evaluation_by_id(conn, row["id"])
    assert final["status"] == "ready"
    assert final["chunks_total"] > 0
    assert final["chunks_embedded"] == final["chunks_total"]
    assert final["sections_count"] > 0

    n_chunks = count_chunks_for_evaluation(conn, row["id"])
    assert n_chunks == final["chunks_total"]


def test_ingest_marks_failed_on_empty_pdf(prepared_db, project_id):
    import pymupdf
    conn = prepared_db
    doc = pymupdf.open()
    doc.new_page()
    blob = bytes(doc.write())
    doc.close()
    row = insert_evaluation(conn, filename="empty.pdf", sha256="sha-empty",
                            size_bytes=len(blob), blob=blob, project_id=project_id)

    provider = _StubProvider()
    ingest_evaluation_sync(conn, evaluation_id=row["id"],
                           embedding_provider=provider)

    final = get_evaluation_by_id(conn, row["id"])
    assert final["status"] == "failed"
    assert final["status_message"] is not None


def test_ingest_is_idempotent(prepared_db, project_id):
    conn = prepared_db
    blob = build_sample_eis_bytes()
    row = insert_evaluation(conn, filename="idem.pdf", sha256="sha-idem",
                            size_bytes=len(blob), blob=blob, project_id=project_id)
    provider = _StubProvider()

    ingest_evaluation_sync(conn, evaluation_id=row["id"],
                           embedding_provider=provider)
    first_count = count_chunks_for_evaluation(conn, row["id"])
    assert first_count > 0

    ingest_evaluation_sync(conn, evaluation_id=row["id"],
                           embedding_provider=provider)
    assert count_chunks_for_evaluation(conn, row["id"]) == first_count
