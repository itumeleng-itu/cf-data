"""Tests for scripts/triage_prospectus.py -- verdict logic against
synthetic page-stat inputs (no PDF needed), plus a real-PDF integration
test against the three known documents in universities/2027/, skipping
cleanly when that directory is absent (fresh clone / sandbox without the
real files, same convention as tests/test_classify.py's slow test).
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from triage_prospectus import (  # noqa: E402
    _MIN_CODE_MATCHES_FOR_TABLE_PAGE,
    _MIN_ESTIMATED_ROWS_FOR_FULL,
    _MIN_PLAUSIBLE_TABLE_PAGES_FOR_FULL,
    _identify,
    _line_looks_like_programme_row,
    _page_code_matches,
    _page_estimated_rows,
    _page_has_header_vocab,
    _verdict,
)


# --- pure signal functions, synthetic text ------------------------------

def test_page_code_matches_uj_style() -> None:
    text = "B2M52Q\nsome prose\nB2I02Q\n"
    assert _page_code_matches(text) >= 2


def test_page_code_matches_cput_style() -> None:
    text = "BPSDGR\nHCDNAS\nD2EMCA\n"
    assert _page_code_matches(text) >= 3


def test_page_code_matches_zero_for_ordinary_prose() -> None:
    assert _page_code_matches("This is ordinary prose about admission.") == 0


def test_page_has_header_vocab_detects_aps() -> None:
    assert _page_has_header_vocab("Minimum APS Score required") is True


def test_page_has_header_vocab_false_for_unrelated_text() -> None:
    assert _page_has_header_vocab("Come visit our beautiful gardens and library") is False


# --- row-density: the correction this file exists to test --------------
# UJ page 32's real programme row (from extract/ground_truth.py's known
# examples) looks like this once text_repair.py has fixed the rotation:
# "B8BA3Q 30 (60%+) 5" -- a code, a plain number, then a bracketed
# achievement cell. Not anchored to any one institution's exact shape,
# since the whole point of this correction is that institutions differ.

def test_line_matches_name_then_numbers_shape() -> None:
    assert _line_looks_like_programme_row("Bachelor of Commerce 28 4 5 6") is True


def test_line_matches_code_plus_aps_number_shape() -> None:
    assert _line_looks_like_programme_row("B2M52Q required at 30 minimum") is True


def test_line_does_not_match_ordinary_prose() -> None:
    assert _line_looks_like_programme_row("Please consult the faculty for more information.") is False


def test_line_does_not_match_blank_line() -> None:
    assert _line_looks_like_programme_row("   ") is False


def test_page_estimated_rows_counts_achievement_level_cells_as_fractional_rows() -> None:
    # UFH's real format (confirmed by hand, 2026-08-08): a digit
    # immediately followed by a parenthetical percentage range, once per
    # subject requirement -- not caught by either line-shape pattern
    # alone, since UFH's own "code" column is a pure-numeric SAQA ID with
    # no letters at all, and real rows wrap across many extracted lines.
    text = "\n".join(["English Language 4 (50%-59%)"] * 8)  # 8 cells / 4 subjects-per-programme = 2 rows
    assert _page_estimated_rows(text) >= 2


def test_page_estimated_rows_zero_for_prose_page() -> None:
    text = "This page discusses general admission philosophy without any table."
    assert _page_estimated_rows(text) == 0


# --- verdict logic, synthetic page-stat inputs --------------------------

def test_verdict_unreadable_for_zero_pages() -> None:
    assert _verdict(page_count=0, plausible_table_pages=0, estimated_programme_rows=0, any_text_extracted=False) == "UNREADABLE"


def test_verdict_unreadable_when_no_text_extractable_even_with_pages() -> None:
    # A scanned-image-only PDF: pages exist, but extract_text() never
    # yields anything -- must not silently fall through to LIKELY_SUMMARY.
    assert _verdict(page_count=10, plausible_table_pages=0, estimated_programme_rows=0, any_text_extracted=False) == "UNREADABLE"


def test_verdict_likely_full_via_plausible_table_pages() -> None:
    assert _verdict(
        page_count=100, plausible_table_pages=_MIN_PLAUSIBLE_TABLE_PAGES_FOR_FULL,
        estimated_programme_rows=0, any_text_extracted=True,
    ) == "LIKELY_FULL"


def test_verdict_likely_full_via_estimated_rows_even_with_few_pages() -> None:
    # The actual bug this correction fixes: a short, dense document (few
    # plausible_table_pages under the old page-count-only rule) must still
    # resolve to LIKELY_FULL once its row estimate clears the threshold.
    assert _verdict(
        page_count=2, plausible_table_pages=0,
        estimated_programme_rows=_MIN_ESTIMATED_ROWS_FOR_FULL, any_text_extracted=True,
    ) == "LIKELY_FULL"


def test_verdict_likely_summary_below_both_thresholds() -> None:
    assert _verdict(
        page_count=15, plausible_table_pages=_MIN_PLAUSIBLE_TABLE_PAGES_FOR_FULL - 1,
        estimated_programme_rows=_MIN_ESTIMATED_ROWS_FOR_FULL - 1, any_text_extracted=True,
    ) == "LIKELY_SUMMARY"


def test_verdict_likely_summary_for_zero_signals() -> None:
    assert _verdict(page_count=20, plausible_table_pages=0, estimated_programme_rows=0, any_text_extracted=True) == "LIKELY_SUMMARY"


# --- _identify: institution_id/year from path conventions --------------

def test_identify_from_fetch_prospectuses_convention() -> None:
    institution_id, year = _identify(Path("data/downloads/uj_2027.pdf"), fallback_year=None)
    assert institution_id == "uj"
    assert year == 2027


def test_identify_from_year_directory_convention() -> None:
    institution_id, year = _identify(Path("universities/2027/uj.pdf"), fallback_year=None)
    assert institution_id == "uj"
    assert year == 2027


def test_identify_falls_back_to_given_year_when_neither_convention_matches() -> None:
    institution_id, year = _identify(Path("somewhere/random.pdf"), fallback_year=2027)
    assert institution_id == "random"
    assert year == 2027


# --- real-PDF integration: the three known documents --------------------

def _universities_2027_dir() -> Path | None:
    candidate = ROOT / "universities" / "2027"
    return candidate if candidate.exists() else None


@pytest.mark.slow
def test_triage_matches_known_verdicts_for_uj_cput_tut() -> None:
    directory = _universities_2027_dir()
    if directory is None:
        pytest.skip("universities/2027/ not present -- skipping on this clone")

    from triage_prospectus import triage_pdf

    expected = {
        "uj.pdf": "LIKELY_FULL",
        "cput.pdf": "LIKELY_SUMMARY",
        "tut.pdf": "LIKELY_SUMMARY",
    }
    for filename, expected_verdict in expected.items():
        pdf_path = directory / filename
        if not pdf_path.exists():
            pytest.skip(f"{pdf_path} not present -- skipping on this clone")
        result = triage_pdf(pdf_path)
        assert result["verdict"] == expected_verdict, (
            f"{filename}: expected {expected_verdict}, got {result['verdict']} "
            f"(pages={result['page_count']}, plausible_tables={result['plausible_table_pages']})"
        )


# --- --repair-rotated: opt-in only, must not change the negative controls

@pytest.mark.slow
def test_repair_rotated_does_not_flip_cput_or_tut_to_likely_full() -> None:
    # The explicit tripwire this flag was built with: if repairing rotated
    # text ever pushes either hand-verified summary over the LIKELY_FULL
    # line, the repair is introducing false signal, not fixing real loss.
    directory = _universities_2027_dir()
    if directory is None:
        pytest.skip("universities/2027/ not present -- skipping on this clone")

    from triage_prospectus import triage_pdf

    for filename in ("cput.pdf", "tut.pdf"):
        pdf_path = directory / filename
        if not pdf_path.exists():
            pytest.skip(f"{pdf_path} not present -- skipping on this clone")
        result = triage_pdf(pdf_path, repair_rotated=True)
        assert result["verdict"] == "LIKELY_SUMMARY", (
            f"{filename}: repair_rotated=True flipped verdict to {result['verdict']} -- "
            f"the heuristic is now too loose (rows={result['estimated_programme_rows']})"
        )


@pytest.mark.slow
def test_repair_rotated_is_off_by_default() -> None:
    # triage_pdf(pdf_path) with no repair_rotated argument must give the
    # exact same result as repair_rotated=False -- the flag is opt-in,
    # never a silent default change to existing behaviour.
    directory = _universities_2027_dir()
    if directory is None:
        pytest.skip("universities/2027/ not present -- skipping on this clone")

    from triage_prospectus import triage_pdf

    pdf_path = directory / "uj.pdf"
    if not pdf_path.exists():
        pytest.skip(f"{pdf_path} not present -- skipping on this clone")

    default_result = triage_pdf(pdf_path)
    explicit_off_result = triage_pdf(pdf_path, repair_rotated=False)
    assert default_result["estimated_programme_rows"] == explicit_off_result["estimated_programme_rows"]
    assert default_result["verdict"] == explicit_off_result["verdict"]
