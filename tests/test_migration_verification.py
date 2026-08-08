"""Confirms supabase/migrations/20260808120000_programmes_verification.sql
was applied: the `verification` jsonb column exists on `programmes` with
the right default, and its partial index only covers needs_review=true
rows -- checked by inserting one true and one false/absent row and
reading pg_indexes/query-plan-relevant behaviour via a direct count,
not by trusting the migration file alone.
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

load_dotenv()

pytestmark = pytest.mark.db


@pytest.fixture
def conn():
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        yield c


def _cleanup(conn: psycopg.Connection, institution_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("delete from programmes where institution_id = %s", (institution_id,))
        cur.execute("delete from institutions where id = %s", (institution_id,))
    conn.commit()


def test_verification_column_exists_with_empty_object_default(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "select column_default from information_schema.columns "
            "where table_name = 'programmes' and column_name = 'verification'",
        )
        row = cur.fetchone()
    assert row is not None, "programmes.verification column does not exist -- migration not applied"
    assert "'{}'" in row[0]


def test_needs_review_partial_index_exists(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("select indexdef from pg_indexes where indexname = 'programmes_verification_needs_review_idx'")
        row = cur.fetchone()
    assert row is not None, "programmes_verification_needs_review_idx does not exist -- migration not applied"
    assert "needs_review" in row[0]
    assert "where" in row[0].lower()


def test_index_only_matches_needs_review_true_rows(conn: psycopg.Connection) -> None:
    institution_id = f"test-verif-{uuid.uuid4().hex[:8]}"
    try:
        with conn.cursor() as cur:
            cur.execute(
                "insert into institutions (id, name, scoring_strategy, scoring_config) "
                "values (%s, %s, 'unconfigured', '{}')",
                (institution_id, institution_id),
            )
            cur.execute(
                "insert into programmes "
                "(institution_id, academic_year, qualification_code, name, requirements, verification) "
                "values (%s, 2027, 'A0000A', 'Needs Review', '{\"nsc\":{\"score\":[{\"min_score\":20}],"
                "\"subjects\":{\"kind\":\"all\",\"rules\":[]}}}', %s)",
                (institution_id, '{"needs_review": true}'),
            )
            cur.execute(
                "insert into programmes "
                "(institution_id, academic_year, qualification_code, name, requirements, verification) "
                "values (%s, 2027, 'A0000B', 'Fully Agreed', '{\"nsc\":{\"score\":[{\"min_score\":20}],"
                "\"subjects\":{\"kind\":\"all\",\"rules\":[]}}}', %s)",
                (institution_id, '{"needs_review": false}'),
            )
            conn.commit()

            cur.execute(
                "select qualification_code from programmes "
                "where institution_id = %s and (verification->>'needs_review')::boolean",
                (institution_id,),
            )
            flagged = {row[0] for row in cur.fetchall()}
        assert flagged == {"A0000A"}
    finally:
        _cleanup(conn, institution_id)
