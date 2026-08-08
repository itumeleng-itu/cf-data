"""Proves seeds -> Postgres -> export produces the same data that went in.

Every other test reads seeds directly via seed_loader.py and never touches
Postgres, so this is the one seam that actually exercises the round trip:
psycopg's own type coercion (numeric -> Decimal, text[] -> list, jsonb ->
dict) plus export_data.py's re-serialization back to JSON.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from seed_loader import load  # noqa: E402

load_dotenv()

pytestmark = pytest.mark.db


def _export(out_dir: Path, years: str = "2027") -> dict:
    out_file = out_dir / "roundtrip_export.json"
    result = subprocess.run(
        [
            sys.executable, str(ROOT / "scripts" / "export_data.py"),
            "--years", years,
            "--out", str(out_file),
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(out_file.read_text(encoding="utf-8"))


def test_roundtrip_preserves_real_seed_data(tmp_path: Path) -> None:
    seeded = load()
    exported = _export(tmp_path)

    seed_by_code = {p["qualification_code"]: p for p in seeded["programmes"]}
    exported_by_code = {p["qualification_code"]: p for p in exported["programmes"]}
    assert set(seed_by_code) == set(exported_by_code)

    for code, seed_p in seed_by_code.items():
        exp_p = exported_by_code[code]

        assert exp_p["institution_id"] == seed_p["institution_id"]
        assert exp_p["academic_year"] == seed_p["academic_year"]
        assert exp_p["name"] == seed_p["name"]
        assert exp_p["faculty"] == seed_p.get("faculty")
        assert exp_p["source_doc"] == seed_p.get("source_doc")
        assert exp_p["source_page"] == seed_p.get("source_page")
        assert exp_p["career_text"] == seed_p.get("career_text")

        # text[] must round-trip as a Python list, including the empty case.
        assert isinstance(exp_p["campus"], list)
        assert exp_p["campus"] == seed_p.get("campus", [])
        assert isinstance(exp_p["selection_notes"], list)
        assert exp_p["selection_notes"] == seed_p.get("selection_notes", [])

        # numeric comes back from Postgres as Decimal; export_data.py must
        # cast it to float before it ever reaches JSON.
        seed_duration = seed_p.get("duration_years")
        if seed_duration is None:
            assert exp_p["duration_years"] is None
        else:
            assert isinstance(exp_p["duration_years"], float)
            assert exp_p["duration_years"] == float(seed_duration)

        assert exp_p["extended"] == seed_p.get("extended", False)
        assert exp_p["confidence"] == seed_p.get("confidence", "extracted")

        # jsonb key order isn't guaranteed -- compare parsed structures,
        # never raw strings.
        assert exp_p["requirements"] == seed_p["requirements"]


def test_roundtrip_preserves_edge_case_values(tmp_path: Path) -> None:
    """Empty arrays and non-ASCII text don't occur in the 5 real seed
    programmes yet, so exercise them directly against a throwaway row."""
    code = "ZZTEST99"
    name = "BSc Zoölogy — café édition"
    career_text = "Ecologist, field researcher, or wildlife rehabilitator — não apenas um emprego de escritório."
    requirements = {
        "nsc": {
            "score": [{"min_score": 20}],
            "subjects": {"kind": "subject", "subject": "mathematics", "min_level": 3},
            "excluded_subjects": [],
        }
    }

    conn = psycopg.connect(os.environ["DATABASE_URL"])
    try:
        with conn.cursor() as cur:
            cur.execute(
                """insert into programmes (
                     institution_id, academic_year, qualification_code, name, faculty,
                     campus, duration_years, extended, requirements, selection_notes,
                     career_text, confidence)
                   values ('uj', 2027, %s, %s, 'Science', '{}', 3, false, %s, '{}', %s, 'extracted')""",
                (code, name, json.dumps(requirements), career_text),
            )
        conn.commit()

        exported = _export(tmp_path)
        row = next(p for p in exported["programmes"] if p["qualification_code"] == code)

        assert row["name"] == name
        assert row["career_text"] == career_text
        assert row["campus"] == []
        assert row["selection_notes"] == []
        assert row["requirements"] == requirements
    finally:
        with conn.cursor() as cur:
            cur.execute("delete from programmes where qualification_code = %s", (code,))
        conn.commit()
        conn.close()
