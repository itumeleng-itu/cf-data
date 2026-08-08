"""Unit tests for extract/classify.py's signal functions against synthetic
primitives -- no PDF file needed, since signal logic is deliberately kept
separate from PDF I/O (see classify.py's module docstring). The one test
that touches a real PDF (@pytest.mark.slow) skips cleanly when the UJ
2027 prospectus isn't present at data/inbox/uj/2027/, e.g. on a fresh
clone or in this sandbox, which has never had that file.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
from classify import (  # noqa: E402
    PageClass,
    PagePrimitives,
    PageSignals,
    classify_page,
    classify_pages,
    code_pattern_matches,
    keyword_hits,
    numeric_alpha_ratio,
    scoring_phrase_hits,
    text_density,
)
from ground_truth import UJ_2027_TABLE_PAGES  # noqa: E402
from profiles import get_profile  # noqa: E402

_CODE_PATTERN = r"^[A-Z]\d[A-Z0-9]{3,4}$"
_UJ_PROFILE = get_profile("uj")
_UJ_CLASSIFICATION = _UJ_PROFILE["classification"]


# --- individual signal functions, synthetic inputs --------------------------

def test_text_density_chars_per_area() -> None:
    p = PagePrimitives(text="", char_count=100, width=10, height=10, line_count=0, image_area_ratio=0.0)
    assert text_density(p) == pytest.approx(1.0)


def test_text_density_zero_area_does_not_raise() -> None:
    p = PagePrimitives(text="", char_count=100, width=0, height=0, line_count=0, image_area_ratio=0.0)
    assert text_density(p) == 0.0


def test_code_pattern_matches_counts_matching_lines() -> None:
    text = "B2M52Q\nsome prose about admission here\nB2I02Q\n"
    assert code_pattern_matches(text, _CODE_PATTERN) == 2


def test_code_pattern_matches_ignores_non_matching_lines() -> None:
    text = "this is not a code\nnor is this one 12345\n"
    assert code_pattern_matches(text, _CODE_PATTERN) == 0


def test_keyword_hits_case_insensitive() -> None:
    text = "the minimum aps required is 30 points"
    assert keyword_hits(text, ["Minimum APS", "Qualification Code"]) == 1


def test_keyword_hits_counts_each_keyword_once() -> None:
    text = "Minimum APS and Qualification Code both appear here"
    assert keyword_hits(text, ["Minimum APS", "Qualification Code", "Not Present"]) == 2


def test_numeric_alpha_ratio_all_digits() -> None:
    assert numeric_alpha_ratio("12345") == 1.0


def test_numeric_alpha_ratio_all_alpha() -> None:
    assert numeric_alpha_ratio("hello world") == 0.0


def test_numeric_alpha_ratio_empty_text_does_not_raise() -> None:
    assert numeric_alpha_ratio("!!! ... ---") == 0.0


def test_scoring_phrase_hits_detects_known_phrase() -> None:
    text = "The Admission Point Score is calculated using your best six subjects."
    assert scoring_phrase_hits(text) >= 1


def test_scoring_phrase_hits_zero_when_absent() -> None:
    assert scoring_phrase_hits("BSc Computer Science and Informatics") == 0


# --- classify_page: weighted combination + over-inclusion bias -------------

def test_clear_programme_table_signals_classify_as_table() -> None:
    signals = PageSignals(
        text_density=0.015, code_matches=6, keyword_hits=4,
        numeric_ratio=0.4, ruled_line_count=80, image_coverage=0.0, scoring_phrase_hits=0, alt_admission_phrase_hits=0,
    )
    page_class, scores = classify_page(signals, _UJ_CLASSIFICATION)
    assert page_class == PageClass.PROGRAMME_TABLE
    assert scores[PageClass.PROGRAMME_TABLE] == max(scores.values())


def test_clear_prose_signals_do_not_classify_as_table() -> None:
    signals = PageSignals(
        text_density=0.018, code_matches=0, keyword_hits=0,
        numeric_ratio=0.0, ruled_line_count=0, image_coverage=0.0, scoring_phrase_hits=0, alt_admission_phrase_hits=0,
    )
    page_class, _scores = classify_page(signals, _UJ_CLASSIFICATION)
    assert page_class != PageClass.PROGRAMME_TABLE


def test_clear_scoring_methodology_signals_classify_correctly() -> None:
    signals = PageSignals(
        text_density=0.015, code_matches=0, keyword_hits=0,
        numeric_ratio=0.0, ruled_line_count=0, image_coverage=0.0, scoring_phrase_hits=3, alt_admission_phrase_hits=0,
    )
    page_class, _scores = classify_page(signals, _UJ_CLASSIFICATION)
    assert page_class == PageClass.SCORING_METHODOLOGY


def test_clear_decorative_signals_classify_correctly() -> None:
    signals = PageSignals(
        text_density=0.0001, code_matches=0, keyword_hits=0,
        numeric_ratio=0.0, ruled_line_count=0, image_coverage=0.9, scoring_phrase_hits=0, alt_admission_phrase_hits=0,
    )
    page_class, _scores = classify_page(signals, _UJ_CLASSIFICATION)
    assert page_class == PageClass.DECORATIVE


def test_near_empty_page_classifies_as_admin() -> None:
    signals = PageSignals(
        text_density=0.0, code_matches=0, keyword_hits=0,
        numeric_ratio=0.0, ruled_line_count=0, image_coverage=0.0, scoring_phrase_hits=0, alt_admission_phrase_hits=0,
    )
    page_class, _scores = classify_page(signals, _UJ_CLASSIFICATION)
    assert page_class == PageClass.ADMIN


def test_borderline_table_vs_scoring_resolves_to_table() -> None:
    # Constructed so SCORING_METHODOLOGY narrowly outscores PROGRAMME_TABLE
    # (9.0 vs 8.8, a 0.2 gap) before the over-inclusion bias is applied --
    # verified by hand-computing both raw scores. Table-vs-prose borderline
    # cases are not usable here: with these weights, requirements_prose can
    # only close to within 0.5 of programme_table's score at a text_density
    # low enough that ADMIN's baseline already dominates both, so the bias
    # never actually decides a table-vs-prose race. Scoring_methodology is
    # where a real close call happens, and this test exists to prove the
    # override branch (classify_page's `best_class != PROGRAMME_TABLE`
    # path) actually executes rather than always being satisfied by the
    # unadjusted max().
    signals = PageSignals(
        text_density=0.005, code_matches=1, keyword_hits=1,
        numeric_ratio=0.1, ruled_line_count=10, image_coverage=0.0, scoring_phrase_hits=1, alt_admission_phrase_hits=0,
    )
    page_class, scores = classify_page(signals, _UJ_CLASSIFICATION)
    # Confirm the raw (pre-bias) leader really was scoring_methodology, not
    # programme_table, so this test can't silently degrade into re-testing
    # the "table wins outright" case if the weights change later.
    assert scores[PageClass.SCORING_METHODOLOGY] > scores[PageClass.PROGRAMME_TABLE]
    assert scores[PageClass.SCORING_METHODOLOGY] - scores[PageClass.PROGRAMME_TABLE] <= 0.5
    assert page_class == PageClass.PROGRAMME_TABLE


def test_signal_values_returned_alongside_classification() -> None:
    _page_class, scores = classify_page(PageSignals(
        text_density=0.01, code_matches=1, keyword_hits=1,
        numeric_ratio=0.2, ruled_line_count=10, image_coverage=0.0, scoring_phrase_hits=0, alt_admission_phrase_hits=0,
    ), _UJ_CLASSIFICATION)
    assert set(scores.keys()) == set(PageClass)


# --- classify_pages: real PDF, skipped cleanly if absent --------------------

def _find_uj_2027_pdf() -> Path | None:
    # Preferred: a real ingestion drop, any filename -- data/inbox/{institution}/{year}/
    # is institution-scoped by directory, so any PDF found there is UJ's.
    inbox = ROOT / "data" / "inbox" / "uj" / "2027"
    if inbox.exists():
        candidates = sorted(inbox.glob("*.pdf"))
        if candidates:
            return candidates[0]

    # Fallback: universities/2027/ holds multiple institutions' prospectuses
    # side by side (not one-per-directory), so only the exact filename
    # confirmed to be UJ's 2027 undergraduate prospectus is used here --
    # never a glob, since cput.pdf/tut.pdf also live in this directory.
    shared = ROOT / "universities" / "2027" / "uj.pdf"
    if shared.exists():
        return shared

    return None


@pytest.mark.slow
def test_classify_uj_2027_recall_exceeds_95_percent() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip(
            "UJ 2027 PDF not present at data/inbox/uj/2027/ or "
            "universities/2027/uj.pdf -- skipping on this clone"
        )

    classifications, _signal_report = classify_pages(pdf_path, _UJ_PROFILE)
    predicted = {page for page, cls in classifications.items() if cls == PageClass.PROGRAMME_TABLE}
    found = UJ_2027_TABLE_PAGES & predicted
    recall = len(found) / len(UJ_2027_TABLE_PAGES)
    missed = sorted(UJ_2027_TABLE_PAGES - predicted)
    assert recall > 0.95, f"recall {recall:.1%} -- missed pages: {missed}"
