from db.evaluations import (
    get_evaluation_by_id,
    init_evaluations_schema,
    insert_evaluation,
    mark_stuck_evaluations_failed,
    update_evaluation_status,
)


def test_sweep_marks_pending_and_embedding_as_failed(db_conn, project_id):
    init_evaluations_schema(db_conn)
    r_pending = insert_evaluation(db_conn, filename="p.pdf", sha256="sp",
                                  size_bytes=5, blob=b"A", project_id=project_id)
    r_embedding = insert_evaluation(db_conn, filename="e.pdf", sha256="se",
                                    size_bytes=5, blob=b"B", project_id=project_id)
    update_evaluation_status(db_conn, r_embedding["id"], status="embedding")
    r_ready = insert_evaluation(db_conn, filename="r.pdf", sha256="sr",
                                size_bytes=5, blob=b"C", project_id=project_id)
    update_evaluation_status(db_conn, r_ready["id"], status="ready")

    n = mark_stuck_evaluations_failed(db_conn)
    assert n == 2

    assert get_evaluation_by_id(db_conn, r_pending["id"])["status"] == "failed"
    assert get_evaluation_by_id(db_conn, r_embedding["id"])["status"] == "failed"
    assert get_evaluation_by_id(db_conn, r_ready["id"])["status"] == "ready"
