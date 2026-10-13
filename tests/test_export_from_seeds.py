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


def test_wits_is_present_with_its_own_scoring_strategy(exported):
    from app.main import load_data
    _, institutions = load_data(exported)
    assert institutions["wits"]["scoring_strategy"] == "custom_points_with_bonus"


def test_curriculum_survives_api_model_validation(exported):
    """_ProgrammeModel drops any field it does not declare. Without the
    streams field on the model this passes through the exporter and
    vanishes at load, with no error anywhere."""
    from app.main import load_data
    programmes, _ = load_data(exported)
    wits = [p for p in programmes if p["institution_id"] == "wits"]
    with_cur = [p for p in wits
                if any(s.get("curriculum") for s in p.get("streams") or [])]
    assert len(with_cur) == 52, f"expected 52 Wits curricula, got {len(with_cur)}"
    courses = sum(len(v) for p in with_cur for s in p["streams"]
                  for v in s["curriculum"].values())
    assert courses == 1464, f"expected 1464 course requirements, got {courses}"
    streams = sum(len(p["streams"]) for p in programmes
                  if p["institution_id"] == "wits")
    assert streams == 66, f"expected 66 streams, got {streams}"


def test_multi_stream_programmes_stay_separated(exported):
    """Four Wits codes print one prospectus page per major. Collapsing
    them into one list is how SBA11 came to require "Introductory Life
    Sciences" six times."""
    from app.main import load_data
    programmes, _ = load_data(exported)
    by_code = {p["qualification_code"]: p for p in programmes
               if p["institution_id"] == "wits"}
    assert {c: len(by_code[c]["streams"])
            for c in ("EFA03", "MBA05", "SBA11", "SBA12")} == {
        "EFA03": 2, "MBA05": 3, "SBA11": 6, "SBA12": 2}
    names = [s["name"] for s in by_code["SBA11"]["streams"]]
    assert "Microbiology and Biotechnology" in names
    assert len(set(names)) == 6, "every stream of a shared code must be named"


def test_a_curriculum_choice_keeps_both_options(exported):
    from app.main import load_data
    programmes, _ = load_data(exported)
    bcom = next(p for p in programmes
                if p["institution_id"] == "wits" and p["qualification_code"] == "CBA00")
    assert len(bcom["streams"]) == 1
    choices = [c for c in bcom["streams"][0]["curriculum"]["first_year"]
               if c.get("choice")]
    assert choices, "BCom General prints two OR choices in first year"
    assert all(len(c["options"]) >= 2 for c in choices)


def test_shape_matches_what_export_data_produces(exported):
    """Both exporters must emit the same top-level shape and the same
    per-record keys, or swapping one for the other changes the API."""
    payload = json.loads(exported.read_text(encoding="utf-8"))
    assert set(payload) == {"institutions", "programmes"}
    seed_record = json.loads(
        (ROOT / "seeds" / "wits" / "wits_2027.json").read_text(encoding="utf-8"))[0]
    exported_record = next(p for p in payload["programmes"]
                           if p["qualification_code"] == seed_record["qualification_code"])
    assert set(exported_record) == set(seed_record)


def test_duration_is_a_float_as_the_numeric_column_would_give(exported):
    payload = json.loads(exported.read_text(encoding="utf-8"))
    durations = [p["duration_years"] for p in payload["programmes"]
                 if p["duration_years"] is not None]
    assert durations and all(isinstance(d, float) for d in durations)


def test_verified_only_excludes_unreviewed_records(tmp_path):
    """The confidence gate must survive the move out of Postgres.

    UJ's seeds are confidence='verified' (a human reviewed them); Wits'
    are 'extracted' (transcribed here, never reviewed). A --verified-only
    export must therefore ship UJ and withhold every Wits record -- the
    same outcome the database path gives, with the field read from a file
    in git instead of a column."""
    out = tmp_path / "programmes.json"
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "export_from_seeds.py"),
         "--years", "2027", "--verified-only", "--out", str(out)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    shipped = {p["institution_id"] for p in payload["programmes"]}
    assert "uj" in shipped
    assert "wits" not in shipped, (
        "Wits seeds are 'extracted'; --verified-only must withhold them "
        "until a human has reviewed and promoted them")


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
