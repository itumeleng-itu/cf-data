"""The git-native export path: seeds/ -> programmes.json, no database.

Guards the two things that can silently break it:
  1. the exporter's output must satisfy the API's OWN loader, not just be
     valid JSON -- main.load_data validates against _DataFile and then
     model_dump()s, so a field the model does not declare is DROPPED
     without error. That is exactly how curriculum went missing the first
     time this ran end to end.
  2. it must agree with export_data.py's shape, so the API cannot tell
     which exporter produced the file it is serving.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "api" / "src"))


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    out = tmp_path_factory.mktemp("export") / "programmes.json"
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "export_from_seeds.py"),
         "--years", "2027", "--out", str(out)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return out


def test_the_api_s_own_loader_accepts_it(exported):
    from app.main import load_data
    programmes, institutions = load_data(exported)
    assert programmes and institutions


def test_duration_is_a_float_as_the_numeric_column_would_give(exported):
    payload = json.loads(exported.read_text(encoding="utf-8"))
    durations = [p["duration_years"] for p in payload["programmes"]
                 if p["duration_years"] is not None]
    assert durations and all(isinstance(d, float) for d in durations)


def test_verified_only_withholds_an_unreviewed_record(tmp_path, monkeypatch):
    """The confidence gate must survive the move out of Postgres: a record
    no one has reviewed is 'extracted' in git exactly as it was a column
    in the database, and --verified-only must withhold it.

    WHY A SYNTHETIC SEED RATHER THAN THE REAL ONES
    ----------------------------------------------
    This test used to assert "ships uj, withholds wits", which was true
    the day it was written and stopped being true the day Wits was
    reviewed and promoted -- so it failed for the one reason that is not
    a defect. Asserting on a fixture of its own makes it a test of the
    GATE rather than of today's roster: it keeps failing if the filter
    breaks, and keeps passing however the real records are marked."""
    seeds = tmp_path / "seeds"
    (seeds / "fictional").mkdir(parents=True)
    (seeds / "institutions.json").write_text(json.dumps({"institutions": [
        {"id": "revu", "name": "Reviewed University", "scoring_strategy": "aps_simple",
         "scoring_config": {"subject_count": 6}},
        {"id": "unrevu", "name": "Unreviewed University", "scoring_strategy": "aps_simple",
         "scoring_config": {"subject_count": 6}},
    ]}), encoding="utf-8")

    def record(inst, code, confidence):
        return {"institution_id": inst, "academic_year": 2027,
                "qualification_code": code, "name": f"Bachelor of {code}",
                "faculty": "Testing", "campus": [], "duration_years": 3,
                "extended": False, "requirements": {"all": []},
                "selection_notes": [], "career_text": None,
                "source_doc": "fixture", "source_page": 1,
                "confidence": confidence}

    (seeds / "fictional" / "progs.json").write_text(json.dumps([
        record("revu", "REV1", "verified"),
        record("unrevu", "UNREV1", "extracted"),
        record("unrevu", "UNREV2", "flagged"),
    ]), encoding="utf-8")

    sys.path.insert(0, str(ROOT / "scripts"))
    import export_from_seeds
    monkeypatch.setattr(export_from_seeds, "SEEDS", seeds)

    out = tmp_path / "programmes.json"
    monkeypatch.setattr(sys, "argv", [
        "export_from_seeds.py", "--years", "2027", "--verified-only",
        "--out", str(out)])
    assert export_from_seeds.main() == 0

    payload = json.loads(out.read_text(encoding="utf-8"))
    shipped = {p["qualification_code"] for p in payload["programmes"]}
    assert shipped == {"REV1"}, (
        "--verified-only must ship only confidence='verified' -- 'extracted' "
        "is unreviewed and 'flagged' is known-suspect, and neither may ship")


def test_every_seed_record_states_a_confidence_the_schema_allows(tmp_path):
    """A record with a typo'd or missing confidence would be silently
    withheld forever by --verified-only, shipping nothing and failing
    nothing. So the field is checked for presence and spelling here,
    across the real seeds, rather than only at export time."""
    allowed = {"verified", "extracted", "flagged"}
    bad = []
    for path in sorted((ROOT / "seeds").glob("*/*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            continue
        for p in payload:
            if p.get("confidence") not in allowed:
                bad.append(f"{path.name} {p.get('qualification_code')}: "
                           f"{p.get('confidence')!r}")
    assert not bad, "; ".join(bad)


def test_refuses_to_ship_an_empty_dataset(tmp_path):
    """min-records is the backstop: a filter that matches nothing must
    fail loudly rather than write an empty file over a good one."""
    out = tmp_path / "programmes.json"
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "export_from_seeds.py"),
         "--years", "1999", "--out", str(out)],
        capture_output=True, text=True)
    assert r.returncode == 1
    assert "refusing to export" in r.stdout
    assert not out.exists()
