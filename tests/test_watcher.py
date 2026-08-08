import os
import sys
import uuid
from pathlib import Path

import psycopg
import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
import pipeline  # noqa: E402
from watcher import MalformedInboxPath, ingest_file, parse_inbox_path, run_once  # noqa: E402

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


def test_dropping_same_file_twice_ingests_once(tmp_path: Path, conn: psycopg.Connection) -> None:
    institution_id = f"zztest{uuid.uuid4().hex[:6]}"
    try:
        with conn.cursor() as cur:
            cur.execute(
                "insert into institutions (id, name, scoring_strategy) values (%s, %s, 'aps_best6_excl_lo')",
                (institution_id, institution_id.upper()),
            )
        conn.commit()

        inbox = tmp_path / institution_id / "2027"
        inbox.mkdir(parents=True)
        pdf = inbox / "prospectus.pdf"
        pdf.write_bytes(b"%PDF-1.4 first version")

        run_once(tmp_path, conn)
        run_once(tmp_path, conn)

        with conn.cursor() as cur:
            cur.execute("select count(*) from ingestions where institution_id = %s", (institution_id,))
            assert cur.fetchone()[0] == 1
    finally:
        _cleanup(conn, institution_id)


def test_dropping_modified_file_with_same_name_reingests(tmp_path: Path, conn: psycopg.Connection) -> None:
    institution_id = f"zztest{uuid.uuid4().hex[:6]}"
    try:
        with conn.cursor() as cur:
            cur.execute(
                "insert into institutions (id, name, scoring_strategy) values (%s, %s, 'aps_best6_excl_lo')",
                (institution_id, institution_id.upper()),
            )
        conn.commit()

        inbox = tmp_path / institution_id / "2027"
        inbox.mkdir(parents=True)
        pdf = inbox / "prospectus.pdf"

        pdf.write_bytes(b"%PDF-1.4 first version")
        run_once(tmp_path, conn)

        pdf.write_bytes(b"%PDF-1.4 second, different, version")
        run_once(tmp_path, conn)

        with conn.cursor() as cur:
            cur.execute(
                "select count(distinct content_sha256) from ingestions where institution_id = %s",
                (institution_id,),
            )
            assert cur.fetchone()[0] == 2
    finally:
        _cleanup(conn, institution_id)


def test_unknown_institution_produces_needs_profile_and_no_extraction(
    tmp_path: Path, conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    institution_id = f"zztest{uuid.uuid4().hex[:6]}"
    calls = []
    monkeypatch.setattr(pipeline, "run", lambda ingestion_id: calls.append(ingestion_id))

    try:
        inbox = tmp_path / institution_id / "2027"
        inbox.mkdir(parents=True)
        pdf = inbox / "prospectus.pdf"
        pdf.write_bytes(b"%PDF-1.4 unknown institution")

        ingest_file(pdf, tmp_path, conn)

        with conn.cursor() as cur:
            cur.execute("select scoring_strategy from institutions where id = %s", (institution_id,))
            row = cur.fetchone()
            assert row is not None
            assert row[0] == "unconfigured"

            cur.execute(
                "select status, r2_key from ingestions where institution_id = %s", (institution_id,),
            )
            status, r2_key = cur.fetchone()
            assert status == "needs_profile"
            assert r2_key is None

        assert calls == []
    finally:
        _cleanup(conn, institution_id)


def test_malformed_path_missing_year_fails_cleanly(tmp_path: Path) -> None:
    inbox = tmp_path / "uj"
    inbox.mkdir(parents=True)
    pdf = inbox / "prospectus.pdf"
    pdf.write_bytes(b"%PDF-1.4 no year segment")

    with pytest.raises(MalformedInboxPath, match="uj/prospectus.pdf|expected"):
        parse_inbox_path(pdf, tmp_path)


def test_run_once_skips_malformed_paths_without_raising(tmp_path: Path, conn: psycopg.Connection) -> None:
    inbox = tmp_path / "uj"
    inbox.mkdir(parents=True)
    (inbox / "prospectus.pdf").write_bytes(b"%PDF-1.4 no year segment")

    run_once(tmp_path, conn)  # must not raise -- the malformed path is skipped, not fatal
