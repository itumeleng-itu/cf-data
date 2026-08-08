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
    _MIN_PLAUSIBLE_TABLE_PAGES_FOR_FULL,
    _identify,
    _page_code_matches,
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


# --- verdict logic, synthetic page-stat inputs --------------------------

def test_verdict_unreadable_for_zero_pages() -> None:
    assert _verdict(page_count=0, plausible_table_pages=0) == "UNREADABLE"


def test_verdict_likely_full_at_threshold() -> None:
    assert _verdict(page_count=50, plausible_table_pages=_MIN_PLAUSIBLE_TABLE_PAGES_FOR_FULL) == "LIKELY_FULL"


def test_verdict_likely_full_above_threshold() -> None:
    assert _verdict(page_count=100, plausible_table_pages=38) == "LIKELY_FULL"


def test_verdict_likely_summary_below_threshold() -> None:
    assert _verdict(page_count=15, plausible_table_pages=_MIN_PLAUSIBLE_TABLE_PAGES_FOR_FULL - 1) == "LIKELY_SUMMARY"


def test_verdict_likely_summary_for_zero_plausible_tables() -> None:
    assert _verdict(page_count=20, plausible_table_pages=0) == "LIKELY_SUMMARY"


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
