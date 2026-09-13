"""Tests for scripts/ingest_bundle.py -- the zip-in, Postgres-out entrance
to the pipeline.

Every test here uses a real, known institution_id (see
extract/institution_map.py) that is NOT 'uj' -- 'uj' carries real
hand-verified seed data other tests and gates (the canonical fixture,
export_data.py --years 2027 -> 29 programmes) depend on, and this file's
job is to hammer on ingestion mechanics (idempotency, rejection, the
confidence downgrade), not to touch that data. 'cput' is used throughout:
a real id, with no seeds/ data of its own to collide with.

Invoked via subprocess throughout (matching tests/test_roundtrip.py's own
convention for scripts that write to the shared local Postgres) rather
than importing and calling functions directly -- this exercises the
actual CLI contract (argv, exit codes, report file) an operator uses.
"""

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import psycopg
import pytest
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "api" / "src"))

load_dotenv()

pytestmark = pytest.mark.db

TEST_INSTITUTION = "cput"


@pytest.fixture
def conn():
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean_test_institution(conn: psycopg.Connection):
    """Runs before AND after every test in this file, so a failed run
    never poisons the next one, and this file never depends on
    left-over state from a previous run."""
    def _clean() -> None:
        conn.execute("delete from programmes where institution_id = %s", (TEST_INSTITUTION,))
        conn.execute("delete from institutions where id = %s", (TEST_INSTITUTION,))
        conn.commit()
    _clean()
    yield
    _clean()


def _programme(**overrides) -> dict:
    base = {
        "qualification_code": "ZZ001",
        "programme": "Test Programme",
        "duration_years": 3,
        "minimum_aps": 26,
        "requirements": {"english": 4, "mathematics": 4},
    }
    base.update(overrides)
    return base


def _bundle(programmes: list[dict], *, institution: dict | None = None, academic_year: int = 2027) -> dict:
    inst = {
        "id": TEST_INSTITUTION, "name": "Cape Peninsula University of Technology",
        "scoring_strategy": "percentage_sum_div_10", "scoring_config": {},
    }
    if institution:
        inst.update(institution)
    return {
        "institution": inst,
        "academic_year": academic_year,
        "source": {"document": f"{TEST_INSTITUTION}_{academic_year}.pdf"},
        "programmes": programmes,
    }


def _write_zip(path: Path, files: dict[str, dict]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, json.dumps(content))
    return path


def _ingest(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "ingest_bundle.py"), str(path), *args],
        capture_output=True, text=True, encoding="utf-8",
    )


def _row(conn: psycopg.Connection, code: str) -> dict | None:
    return conn.execute(
        "select * from programmes where institution_id = %s and qualification_code = %s",
        (TEST_INSTITUTION, code),
    ).fetchone()


def _count(conn: psycopg.Connection) -> int:
    return conn.execute(
        "select count(*) as n from programmes where institution_id = %s", (TEST_INSTITUTION,)
    ).fetchone()["n"]


# --- happy path: load, idempotency, corrections --------------------------

def test_valid_zip_loads_with_correct_row_counts(tmp_path: Path, conn: psycopg.Connection) -> None:
    zpath = _write_zip(tmp_path / "b.zip", {
        f"{TEST_INSTITUTION}_2027.json": _bundle([_programme(), _programme(qualification_code="ZZ002")]),
    })
    result = _ingest(zpath, "--report", str(tmp_path / "report.md"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert _count(conn) == 2
    assert "new 2" in result.stdout
    assert (tmp_path / "report.md").exists()


def test_a_directory_of_bundle_files_is_also_accepted(tmp_path: Path, conn: psycopg.Connection) -> None:
    bundle_dir = tmp_path / "bundles"
    bundle_dir.mkdir()
    (bundle_dir / f"{TEST_INSTITUTION}_2027.json").write_text(
        json.dumps(_bundle([_programme()])), encoding="utf-8"
    )
    result = _ingest(bundle_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _count(conn) == 1


def test_reingesting_the_same_zip_is_a_true_noop(tmp_path: Path, conn: psycopg.Connection) -> None:
    zpath = _write_zip(tmp_path / "b.zip", {"a.json": _bundle([_programme()])})
    first = _ingest(zpath)
    assert first.returncode == 0, first.stdout
    row_before = _row(conn, "ZZ001")

    second = _ingest(zpath)
    assert second.returncode == 0, second.stdout
    assert "unchanged 1" in second.stdout
    assert "new 1" not in second.stdout

    row_after = _row(conn, "ZZ001")
    assert row_after["updated_at"] == row_before["updated_at"]


def test_corrected_zip_updates_only_the_changed_record_and_reports_it(
    tmp_path: Path, conn: psycopg.Connection,
) -> None:
    original = _bundle([_programme(qualification_code="ZZ001"), _programme(qualification_code="ZZ002")])
    _ingest(_write_zip(tmp_path / "first.zip", {"a.json": original}))
    zz002_before = _row(conn, "ZZ002")

    corrected = _bundle([
        _programme(qualification_code="ZZ001", programme="Corrected Name"),
        _programme(qualification_code="ZZ002"),
    ])
    result = _ingest(_write_zip(tmp_path / "second.zip", {"a.json": corrected}))
    assert result.returncode == 0, result.stdout
    assert "changed 1" in result.stdout
    assert "ZZ001" in result.stdout

    zz001_after = _row(conn, "ZZ001")
    assert zz001_after["name"] == "Corrected Name"
    zz002_after = _row(conn, "ZZ002")
    assert zz002_after["updated_at"] == zz002_before["updated_at"]  # untouched


def test_verified_record_that_changes_drops_to_extracted_and_is_named_in_the_report(
    tmp_path: Path, conn: psycopg.Connection,
) -> None:
    _ingest(_write_zip(tmp_path / "first.zip", {"a.json": _bundle([_programme()])}))
    conn.execute(
        "update programmes set confidence = 'verified' where institution_id = %s and qualification_code = %s",
        (TEST_INSTITUTION, "ZZ001"),
    )
    conn.commit()

    corrected = _bundle([_programme(programme="Renamed After Verification")])
    result = _ingest(_write_zip(tmp_path / "second.zip", {"a.json": corrected}))
    assert result.returncode == 0, result.stdout
    assert "previously-verified" in result.stdout
    assert "ZZ001" in result.stdout

    row = _row(conn, "ZZ001")
    assert row["confidence"] == "extracted"
    assert row["name"] == "Renamed After Verification"


def test_unchanged_record_keeps_its_existing_confidence_even_if_verified(
    tmp_path: Path, conn: psycopg.Connection,
) -> None:
    # The other half of the idempotency guarantee: re-ingesting a bundle
    # that changes NOTHING must never touch confidence, verified or not.
    _ingest(_write_zip(tmp_path / "first.zip", {"a.json": _bundle([_programme()])}))
    conn.execute(
        "update programmes set confidence = 'verified' where institution_id = %s and qualification_code = %s",
        (TEST_INSTITUTION, "ZZ001"),
    )
    conn.commit()

    result = _ingest(_write_zip(tmp_path / "second.zip", {"a.json": _bundle([_programme()])}))
    assert result.returncode == 0, result.stdout
    assert "unchanged 1" in result.stdout

    row = _row(conn, "ZZ001")
    assert row["confidence"] == "verified"


def test_removed_programme_is_reported_but_not_deleted(tmp_path: Path, conn: psycopg.Connection) -> None:
    _ingest(_write_zip(tmp_path / "first.zip", {
        "a.json": _bundle([_programme(qualification_code="ZZ001"), _programme(qualification_code="ZZ002")]),
    }))
    result = _ingest(_write_zip(tmp_path / "second.zip", {
        "a.json": _bundle([_programme(qualification_code="ZZ001")]),
    }))
    assert result.returncode == 0, result.stdout
    assert "removed 1" in result.stdout
    assert "ZZ002" in result.stdout
    # NOT deleted -- a human decides, ingestion never does this silently.
    assert _row(conn, "ZZ002") is not None


def test_dry_run_writes_nothing_at_all(tmp_path: Path, conn: psycopg.Connection) -> None:
    zpath = _write_zip(tmp_path / "b.zip", {"a.json": _bundle([_programme()])})
    result = _ingest(zpath, "--dry-run")
    assert result.returncode == 0, result.stdout
    assert "new 1" in result.stdout
    assert _count(conn) == 0


# --- rejection: whole-bundle, never partial ------------------------------

def test_semantically_invalid_bundle_is_rejected_whole_zero_rows_written(
    tmp_path: Path, conn: psycopg.Connection,
) -> None:
    good = _programme(qualification_code="ZZGOOD")
    swapped_columns = _programme(
        qualification_code="ZZBAD", programme="Swapped columns",
        requirements={"english": 4, "mathematics": 5, "mathematical_literacy": 3},
    )
    result = _ingest(_write_zip(tmp_path / "b.zip", {"a.json": _bundle([good, swapped_columns])}))
    assert result.returncode == 1
    assert "columns likely swapped" in result.stdout
    assert _count(conn) == 0  # ZZGOOD did NOT sneak in even though it was individually fine


def test_unknown_institution_id_rejected_with_the_known_id_list(tmp_path: Path) -> None:
    bundle = _bundle([_programme()], institution={"id": "not_a_real_university", "name": "Fake U"})
    result = _ingest(_write_zip(tmp_path / "b.zip", {"a.json": bundle}))
    assert result.returncode == 1
    assert "unknown institution" in result.stdout.lower()
    assert "uj" in result.stdout  # part of the printed known-id list


def test_path_traversal_entry_rejects_the_whole_zip(tmp_path: Path, conn: psycopg.Connection) -> None:
    zpath = tmp_path / "evil.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr(f"{TEST_INSTITUTION}_2027.json", json.dumps(_bundle([_programme()])))
        zf.writestr("../../evil.json", "{}")
    result = _ingest(zpath)
    assert result.returncode == 1
    assert "traversal" in result.stdout.lower() or "unsafe" in result.stdout.lower()
    assert _count(conn) == 0  # the otherwise-valid sibling entry never loaded either


def test_absolute_path_entry_is_rejected(tmp_path: Path) -> None:
    zpath = tmp_path / "evil2.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("/etc/evil.json", "{}")
    result = _ingest(zpath)
    assert result.returncode == 1
    assert "unsafe" in result.stdout.lower()


def test_non_json_entry_in_zip_is_rejected(tmp_path: Path, conn: psycopg.Connection) -> None:
    zpath = tmp_path / "mixed.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr(f"{TEST_INSTITUTION}_2027.json", json.dumps(_bundle([_programme()])))
        zf.writestr("readme.txt", "not json")
    result = _ingest(zpath)
    assert result.returncode == 1
    assert "readme.txt" in result.stdout
    assert _count(conn) == 0


# --- the three shapes the flat format must get right, end to end --------

def test_not_accepted_produces_excluded_subjects_end_to_end(tmp_path: Path, conn: psycopg.Connection) -> None:
    # B34CAQ's real shape: Mathematical Literacy / Technical Mathematics
    # explicitly "Not accepted" alongside Mathematics required.
    b34caq = _programme(
        qualification_code="B34CAQ", programme="Bachelor of Accounting",
        minimum_aps={"with_mathematics": 33},
        requirements={
            "english": 4, "mathematics": 5,
            "mathematical_literacy": "not_accepted", "technical_mathematics": "not_accepted",
        },
    )
    result = _ingest(_write_zip(tmp_path / "b.zip", {"a.json": _bundle([b34caq])}))
    assert result.returncode == 0, result.stdout
    row = _row(conn, "B34CAQ")
    excluded = row["requirements"]["nsc"]["excluded_subjects"]
    assert set(excluded) == {"mathematical_literacy", "technical_mathematics"}


def test_null_produces_no_exclusion_end_to_end(tmp_path: Path, conn: psycopg.Connection) -> None:
    # B2I02Q's real shape: Physical Science "Not applicable" (null) must
    # produce NOTHING, in direct contrast to the "not_accepted" case above.
    b2i02q = _programme(
        qualification_code="B2I02Q", programme="BSc Information Technology", minimum_aps=30,
        requirements={
            "english": 5, "mathematics": 6,
            "technical_mathematics": "not_accepted", "technical_science": "not_accepted",
            "physical_science": None,
        },
    )
    result = _ingest(_write_zip(tmp_path / "b.zip", {"a.json": _bundle([b2i02q])}))
    assert result.returncode == 0, result.stdout
    row = _row(conn, "B2I02Q")
    excluded = row["requirements"]["nsc"]["excluded_subjects"]
    assert "physical_sciences" not in excluded
    assert set(excluded) == {"technical_mathematics", "technical_sciences"}


def test_any_of_produces_two_sibling_any_nodes_end_to_end(tmp_path: Path, conn: psycopg.Connection) -> None:
    # The B6CV3Q shape: an automatic any (Maths/Tech Maths, no special
    # syntax) and a manual any_of (Physical/Technical Science) as two
    # sibling `any` nodes inside one `all`.
    b6cv3q = _programme(
        qualification_code="B6CV3Q", programme="BEngTech Civil Engineering",
        minimum_aps={"with_mathematics": 28, "with_technical_mathematics": 28},
        requirements={
            "english": 4, "mathematics": 5, "technical_mathematics": 5,
            "any_of": [{"physical_science": 5}, {"technical_science": 5}],
        },
    )
    result = _ingest(_write_zip(tmp_path / "b.zip", {"a.json": _bundle([b6cv3q])}))
    assert result.returncode == 0, result.stdout
    row = _row(conn, "B6CV3Q")
    rules = row["requirements"]["nsc"]["subjects"]["rules"]
    any_nodes = [r for r in rules if r["kind"] == "any"]
    assert len(any_nodes) == 2
    groups = [{c["subject"] for c in n["rules"]} for n in any_nodes]
    assert {"mathematics", "technical_mathematics"} in groups
    assert {"physical_sciences", "technical_sciences"} in groups


def test_language_band_produces_min_level_and_min_level_fal_end_to_end(
    tmp_path: Path, conn: psycopg.Connection,
) -> None:
    b5bfpq = _programme(
        qualification_code="B5BFPQ", programme="BEd Foundation Phase",
        minimum_aps=28,
        requirements={
            "english": {"home_language": 5, "first_additional_language": 6},
            "mathematics": 3, "mathematical_literacy": 5,
        },
    )
    result = _ingest(_write_zip(tmp_path / "b.zip", {"a.json": _bundle([b5bfpq])}))
    assert result.returncode == 0, result.stdout
    row = _row(conn, "B5BFPQ")
    rules = row["requirements"]["nsc"]["subjects"]["rules"]
    english = next(r for r in rules if r.get("language") == "english")
    assert english["min_level"] == 5
    assert english["min_level_fal"] == 6


# --- scoreable:false, all the way to /v1/qualify -------------------------

def test_scoreable_false_reaches_requires_additional_assessment_via_the_real_api(
    tmp_path: Path, conn: psycopg.Connection,
) -> None:
    """The full chain: ingest -> Postgres -> export_data.py -> the real
    api.main._run_qualify -- proving scoreable actually survives
    export_data.py's SELECT (it is a real column added alongside
    scoring_override/scoring_strategy_override), not just the ingest
    step. api/ itself is not modified anywhere in this test."""
    composite_index_programme = _programme(
        qualification_code="ZZCOMPOSITE", programme="Composite Index Programme",
        scoreable=False, selection_notes=["Composite Index includes NBT results."],
    )
    result = _ingest(_write_zip(tmp_path / "b.zip", {"a.json": _bundle([composite_index_programme])}))
    assert result.returncode == 0, result.stdout

    export_path = tmp_path / "programmes.json"
    export_result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "export_data.py"),
         "--years", "2027", "--out", str(export_path)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert export_result.returncode == 0, export_result.stdout + export_result.stderr

    exported = json.loads(export_path.read_text(encoding="utf-8"))
    programme = next(p for p in exported["programmes"] if p["qualification_code"] == "ZZCOMPOSITE")
    assert programme["scoreable"] is False

    import app.main as main_module

    saved = (main_module.PROGRAMMES, main_module.INSTITUTIONS)
    try:
        for p in exported["programmes"]:
            if p.get("duration_years") is not None:
                p["duration_years"] = float(p["duration_years"])
        main_module.PROGRAMMES = exported["programmes"]
        main_module.INSTITUTIONS = {i["id"]: i for i in exported["institutions"]}

        request = main_module.QualifyRequest(subjects=[
            {"subject": "english_hl", "percentage": 87},
            {"subject": "mathematics", "percentage": 88},
            {"subject": "life_orientation", "percentage": 88},
            {"subject": "geography", "percentage": 92},
            {"subject": "life_sciences", "percentage": 87},
            {"subject": "physical_sciences", "percentage": 73},
        ], institutions=[TEST_INSTITUTION])
        response = main_module._run_qualify(request)

        codes = {r["qualification_code"] for r in response["requires_additional_assessment"]}
        assert "ZZCOMPOSITE" in codes
        assert not any(r["qualification_code"] == "ZZCOMPOSITE" for r in response["qualified"])
        assert not any(r["qualification_code"] == "ZZCOMPOSITE" for r in response["near_misses"])
        entry = next(r for r in response["requires_additional_assessment"] if r["qualification_code"] == "ZZCOMPOSITE")
        assert entry["selection_notes"] == ["Composite Index includes NBT results."]
    finally:
        main_module.PROGRAMMES, main_module.INSTITUTIONS = saved


# --- scoring_strategy checks ----------------------------------------------

def test_unregistered_scoring_strategy_is_rejected(tmp_path: Path, conn: psycopg.Connection) -> None:
    bundle = _bundle([_programme()], institution={"scoring_strategy": "not_a_real_algorithm"})
    result = _ingest(_write_zip(tmp_path / "b.zip", {"a.json": bundle}))
    assert result.returncode == 1
    assert "unknown scoring_strategy" in result.stdout.lower()
    assert _count(conn) == 0


def test_unverified_scoring_strategy_warns_loudly_and_still_loads(
    tmp_path: Path, conn: psycopg.Connection,
) -> None:
    # weighted_levels is registered in SCORERS but has no worked-example
    # test yet (docs/scoring/weighted_levels.md records it UNVERIFIED).
    bundle = _bundle([_programme()], institution={"scoring_strategy": "weighted_levels"})
    result = _ingest(_write_zip(tmp_path / "b.zip", {"a.json": bundle}))
    assert result.returncode == 0, result.stdout
    assert "UNVERIFIED" in (ROOT / "docs" / "scoring" / "weighted_levels.md").read_text(encoding="utf-8")
    assert "weighted_levels" in result.stdout
    assert "loading anyway" in result.stdout
    assert _count(conn) == 1
