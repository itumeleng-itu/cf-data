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
