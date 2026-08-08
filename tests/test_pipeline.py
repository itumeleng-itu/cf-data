"""Tests for extract/pipeline.py's classification stage (sub-phase 8.2).

classify_pages itself is unit-tested in tests/test_classify.py, including
its one real-PDF integration test (skipped when no fixture is present).
Here pipeline.run's own responsibility -- status transitions and
persisting classification/signal data against the ingestions row -- is
tested by monkeypatching classify_pages, so this suite needs no PDF file
at all, only a live DATABASE_URL.
"""

import os
import sys
import uuid
from pathlib import Path

import psycopg
import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
import classify  # noqa: E402
import pipeline  # noqa: E402

load_dotenv()

pytestmark = pytest.mark.db


@pytest.fixture
def conn():
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        yield c


def _cleanup(conn: psycopg.Connection, institution_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("delete from ingestions where institution_id = %s", (institution_id,))
        cur.execute("delete from institutions where id = %s", (institution_id,))
    conn.commit()


def test_run_persists_classification_and_marks_review_ready(
    tmp_path: Path, conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    institution_id = f"zztest{uuid.uuid4().hex[:6]}"
    ingestion_id = str(uuid.uuid4())

    fake_classifications = {
        1: classify.PageClass.ADMIN,
        2: classify.PageClass.PROGRAMME_TABLE,
        3: classify.PageClass.PROGRAMME_TABLE,
    }
    fake_signal_report = {
        page: {"class": cls.value, "signals": {}, "scores": {}}
        for page, cls in fake_classifications.items()
    }
    monkeypatch.setattr(
        classify,
        "classify_pages",
        lambda pdf_path, profile: (fake_classifications, fake_signal_report),
    )

    try:
        with conn.cursor() as cur:
            cur.execute(
                "insert into institutions (id, name, scoring_strategy) values (%s, %s, 'aps_best6_excl_lo')",
                (institution_id, institution_id.upper()),
            )
            cur.execute(
                """insert into ingestions
                     (id, institution_id, academic_year, source_filename, content_sha256, status)
                   values (%s, %s, 2027, 'prospectus.pdf', %s, 'pending')""",
                (ingestion_id, institution_id, uuid.uuid4().hex),
            )
        conn.commit()

        pipeline.run(ingestion_id, tmp_path / "prospectus.pdf", conn)

        with conn.cursor() as cur:
            cur.execute(
                "select status, page_count, table_pages, stats from ingestions where id = %s",
                (ingestion_id,),
            )
            status, page_count, table_pages, stats = cur.fetchone()
            assert status == "review_ready"
            assert page_count == 3
            assert table_pages == [2, 3]
            assert stats["2"]["class"] == "programme_table"
            assert stats["1"]["class"] == "admin"
    finally:
        _cleanup(conn, institution_id)


def test_run_sets_classifying_status_before_completion(
    tmp_path: Path, conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    institution_id = f"zztest{uuid.uuid4().hex[:6]}"
    ingestion_id = str(uuid.uuid4())
    observed_statuses = []

    def _fake_classify_pages(pdf_path: Path, profile: dict) -> tuple[dict, dict]:
        with conn.cursor() as cur:
            cur.execute("select status from ingestions where id = %s", (ingestion_id,))
            observed_statuses.append(cur.fetchone()[0])
        return {1: classify.PageClass.PROGRAMME_TABLE}, {1: {"class": "programme_table"}}

    monkeypatch.setattr(classify, "classify_pages", _fake_classify_pages)

    try:
        with conn.cursor() as cur:
            cur.execute(
                "insert into institutions (id, name, scoring_strategy) values (%s, %s, 'aps_best6_excl_lo')",
                (institution_id, institution_id.upper()),
            )
            cur.execute(
                """insert into ingestions
                     (id, institution_id, academic_year, source_filename, content_sha256, status)
                   values (%s, %s, 2027, 'prospectus.pdf', %s, 'pending')""",
                (ingestion_id, institution_id, uuid.uuid4().hex),
            )
        conn.commit()

        pipeline.run(ingestion_id, tmp_path / "prospectus.pdf", conn)

        assert observed_statuses == ["classifying"]
    finally:
        _cleanup(conn, institution_id)
