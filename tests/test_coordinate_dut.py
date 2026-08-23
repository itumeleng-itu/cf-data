"""Unit tests for extract/methods/coordinate_dut.py -- DUT's page-prose
extraction, a separate method from Method D (coordinate.py) because
DUT's document shape defeats Method D's code-in-cell, column-per-subject
model entirely (see registry.json's dut quirks, phase 8.5 step 8)."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
from methods.coordinate_dut import (  # noqa: E402
    _find_compulsory_subjects_cell,
    _location,
    _parse_code_block,
    _programme_name,
    _score_notes,
)
from profiles import get_profile  # noqa: E402

_DUT = get_profile("dut")
_CODE_PATTERN = re.compile(_DUT["layout"]["code_pattern"])


# --- _parse_code_block ---------------------------------------------------

def test_single_code_no_duration_annotation() -> None:
    lines = ["Qualification Code: BBCST1", "Location: Steve Biko Campus"]
    assert _parse_code_block(lines, 0, _CODE_PATTERN) == [("BBCST1", None, False)]


def test_two_codes_with_mainstream_and_extended_durations() -> None:
    lines = [
        "Qualification Code: BCHNSG (4-YRS MAINSTREAM)",
        "BCHNSE (5-YRS EXTENDED CURRICULUM)",
        "Location: Indumiso Site",
    ]
    result = _parse_code_block(lines, 0, _CODE_PATTERN)
    assert result == [("BCHNSG", 4, False), ("BCHNSE", 5, True)]


def test_code_block_stops_at_next_recognised_label() -> None:
    lines = ["Qualification Code: BBCST1", "Location: X", "Description of the Programme"]
    result = _parse_code_block(lines, 0, _CODE_PATTERN)
    assert result == [("BBCST1", None, False)]


def test_four_codes_with_campus_parentheticals_not_mistaken_for_duration() -> None:
    lines = [
        "Qualification Code: DIACC1 (DBN)",
        "DIACTI (PMB)",
        "DIACCF (DBN -4 Year Extended Curriculum Programme)",
        "DIACCP (PMB -4 Year Extended Curriculum Programme)",
        "Location: Ritson Campus",
    ]
    result = _parse_code_block(lines, 0, _CODE_PATTERN)
    codes = [c for c, _d, _e in result]
    assert codes == ["DIACC1", "DIACTI", "DIACCF", "DIACCP"]
    # "(DBN)"/"(PMB)" must not be misread as a duration annotation.
    assert all(duration is None for _c, duration, _e in result)


# --- _programme_name / _location ------------------------------------------

def test_programme_name_is_the_line_before_nqf_level() -> None:
    lines = [
        "Contact the Department of Architecture",
        "Bachelor of the Built Environment in Construction Studies (BBE Construction Studies)",
        "NQF Level: 7",
        "SAQA ID: 101515",
    ]
    assert _programme_name(lines) == "Bachelor of the Built Environment in Construction Studies (BBE Construction Studies)"


def test_programme_name_none_when_no_nqf_level_anchor() -> None:
    assert _programme_name(["Some prose", "with no anchor at all"]) is None


def test_location_extracted_from_label_line() -> None:
    lines = ["Qualification Code: BBCST1", "Location: Steve Biko Campus (S3 Level 2)", "Description"]
    assert _location(lines) == "Steve Biko Campus (S3 Level 2)"


def test_location_none_when_absent() -> None:
    assert _location(["no location label here"]) is None


# --- _find_compulsory_subjects_cell (position-independent) ---------------

def test_compulsory_subjects_at_column_zero() -> None:
    row = ["Compulsory Subjects", "NSC Rating Code", "Compulsory Subjects"]
    assert _find_compulsory_subjects_cell(row) == 0


def test_compulsory_subjects_at_a_later_column_with_empty_spacers() -> None:
    # Real case, p.117: a sparsely-split lattice table pushes the cell to
    # column 1 with an empty spacer column before it -- must not assume
    # column 0.
    row = ["", "Compulsory Subjects", "", "", "NSC Rating Code"]
    assert _find_compulsory_subjects_cell(row) == 1


def test_compulsory_subjects_absent_returns_none() -> None:
    row = ["English", "4", "English"]
    assert _find_compulsory_subjects_cell(row) is None


# --- _score_notes ----------------------------------------------------------

def test_score_notes_captures_numbered_scoring_rule() -> None:
    text = (
        "NB:\n"
        "1. NSC Mathematical Literacy will not be accepted as a substitute for the subject NSC Mathematics\n"
        "3. Applicants with a NSC will be ranked according to the sum of their scores for Mathematics and "
        "Physical Science, subject to a minimum combined score of 100%.\n"
    )
    notes = _score_notes(text)
    assert len(notes) == 1
    assert "combined score of 100%" in notes[0]


def test_score_notes_empty_when_no_numbered_notes() -> None:
    assert _score_notes("Just ordinary prose with no numbered notes.") == []
