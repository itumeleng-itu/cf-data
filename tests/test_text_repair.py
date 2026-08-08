"""Tests for extract/text_repair.py -- repairing pdfplumber's character-
order assembly for rotated text. Unit tests use synthetic fake pages (a
plain object exposing .extract_text()/.chars) so the matrix-driven repair
logic is fully testable without a real PDF. The one test that touches the
real UJ 2027 PDF (@pytest.mark.slow) skips cleanly when it's absent.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
from text_repair import looks_reversed, normalise_page_text  # noqa: E402

_CODE_PATTERN = r"[A-Z]\d[A-Z0-9]{3,4}"


def _char(text: str, f: float, e: float = 136.0, upright: bool = False) -> dict:
    # Matrix (0, 8, -8, 0, e, f) matches the real UJ 2027 rotated-header
    # matrix observed in this document (a 90-degree rotation, advance
    # direction (0, 8) -- advancing along the text runs in +f).
    return {"text": text, "upright": upright, "matrix": (0.0, 8.0, -8.0, 0.0, e, f)}


class _FakePage:
    def __init__(self, extract_text_value: str, chars: list[dict]) -> None:
        self._extract_text_value = extract_text_value
        self.chars = chars

    def extract_text(self) -> str:
        return self._extract_text_value


def _chars_for(word: str, start_f: float = 100.0, step: float = 5.0, e: float = 136.0) -> list[dict]:
    return [_char(ch, start_f + i * step, e=e) for i, ch in enumerate(word)]


# --- looks_reversed ----------------------------------------------------

def test_looks_reversed_detects_reversed_code() -> None:
    # Q3AB8B/B8BA3Q (the actual page-32 example) turns out to be a poor
    # unit-test case, verified by direct computation: "Q3AB8B" itself
    # ALSO fullmatches the generic code_pattern (letter, digit, then 3-4
    # alnum) -- both directions of a letter-digit-letter-letter-digit-
    # letter shape satisfy this pattern, so shape alone can't tell them
    # apart (only the matrix-driven repair in normalise_page_text can,
    # since it never has to guess). Using QSAM6D instead: a real,
    # unambiguous example from page 62's own audit -- its second
    # character is a letter, so it fails forward, while its reverse
    # (D6MASQ) matches cleanly.
    assert looks_reversed("QSAM6D", _CODE_PATTERN) is True


def test_looks_reversed_false_for_forward_code() -> None:
    assert looks_reversed("B8BA3Q", _CODE_PATTERN) is False


def test_looks_reversed_false_for_ordinary_prose() -> None:
    assert looks_reversed("Architecture", _CODE_PATTERN) is False


def test_looks_reversed_detects_reversed_percentage_cell() -> None:
    assert looks_reversed(")+%06(", _CODE_PATTERN) is True


def test_looks_reversed_detects_reversed_not_accepted() -> None:
    assert looks_reversed("detpecca toN", _CODE_PATTERN) is True


def test_looks_reversed_empty_string_does_not_raise() -> None:
    assert looks_reversed("", _CODE_PATTERN) is False


# --- normalise_page_text: synthetic pages, no PDF required -------------
#
# Contract: corrected runs are APPENDED to page.extract_text()'s output,
# not surgically replaced in place -- confirmed on real UJ 2027 data
# (page 38) that guessing where a corrected run belongs in pdfplumber's
# own wrong-order text is unreliable (line-breaking and ligature quirks
# both broke a plain reversal-based find/replace). Tests check that the
# corrected text is PRESENT, not that it replaced anything.

def test_repairs_reversed_qualification_code() -> None:
    chars = _chars_for("B8BA3Q")
    page = _FakePage("DEGREE PROGRAMMES Q3AB8B 30 (60%+)", chars)
    assert "B8BA3Q" in normalise_page_text(page)


def test_repairs_reversed_percentage_cell() -> None:
    chars = _chars_for("(60%+)")
    page = _FakePage("Mathematics )+%06( required", chars)
    assert "(60%+)" in normalise_page_text(page)


def test_repairs_reversed_accept_reject_marker_with_embedded_space() -> None:
    chars = _chars_for("Not accepted")
    page = _FakePage("Technical Mathematics: detpecca toN", chars)
    assert "Not accepted" in normalise_page_text(page)


def test_multi_word_header_with_ligature_glyph_repaired() -> None:
    # Regression for the real page-38 bug: pdfplumber can return a
    # ligature (e.g. 'fi') as a single multi-character entry in
    # page.chars. A plain Python string reversal of the assembled text
    # flips the ligature's internal letter order too ('fi' -> 'if'),
    # which doesn't happen in the run itself since _group_runs reorders
    # whole character ENTRIES, never their internal text.
    chars = [
        _char("Q", 100.0), _char("u", 105.0), _char("a", 110.0), _char("l", 115.0),
        _char("i", 120.0), _char("fi", 125.0), _char("c", 130.0), _char("a", 135.0),
        _char("t", 140.0), _char("i", 145.0), _char("o", 150.0), _char("n", 155.0),
        _char(" ", 160.0), _char("C", 165.0), _char("o", 170.0), _char("d", 175.0),
        _char("e", 180.0),
    ]
    page = _FakePage("some other reversed junk pdfplumber produced", chars)
    assert "Qualification Code" in normalise_page_text(page)


def test_two_occurrences_of_same_column_at_large_gap_both_repaired() -> None:
    # Same rotation and column (same e), but far apart along the advance
    # direction -- simulates two different table rows reusing the same
    # rotated column. Must be treated as separate runs, not merged, and
    # each occurrence repaired independently.
    first = _chars_for("Not accepted", start_f=100.0)
    second = _chars_for("Not accepted", start_f=100.0 + 1000.0)  # far beyond the gap threshold
    page = _FakePage(
        "Row A: detpecca toN | Row B: detpecca toN",
        first + second,
    )
    result = normalise_page_text(page)
    assert result.count("Not accepted") == 2


def test_upright_text_left_untouched() -> None:
    chars = [_char(ch, 100.0 + i * 5.0, upright=True) for i, ch in enumerate("B8BA3Q")]
    page = _FakePage("DEGREE PROGRAMMES B8BA3Q 30", chars)
    assert normalise_page_text(page) == "DEGREE PROGRAMMES B8BA3Q 30"


def test_no_non_upright_chars_returns_text_unchanged() -> None:
    page = _FakePage("plain prose page, nothing rotated here", [])
    assert normalise_page_text(page) == "plain prose page, nothing rotated here"


def test_original_baseline_text_still_present_alongside_correction() -> None:
    # Appending, not replacing: the original (possibly still wrong-order)
    # text from pdfplumber is preserved -- correctness for regex/substring
    # signal extraction only needs the corrected text to be present
    # somewhere, and preserving the baseline is simpler and more robust
    # than trying to remove exactly the right substring.
    chars = _chars_for("B8BA3Q")
    page = _FakePage("DEGREE PROGRAMMES Q3AB8B 30 (60%+)", chars)
    result = normalise_page_text(page)
    assert "Q3AB8B" in result
    assert "B8BA3Q" in result


def test_different_columns_at_same_advance_position_not_merged() -> None:
    # Two distinct rotated columns (different e / perpendicular position)
    # that happen to occupy overlapping f ranges -- must not be
    # interleaved into one nonsensical run.
    column_a = _chars_for("B8BA3Q", e=136.0)
    column_b = _chars_for("D1TA8D", e=200.0)
    page = _FakePage("codes: Q3AB8B and D8AT1D", column_a + column_b)
    result = normalise_page_text(page)
    assert "B8BA3Q" in result
    assert "D1TA8D" in result


# --- real PDF integration: pages 46, 47, 62, 95 -------------------------

def _find_uj_2027_pdf() -> Path | None:
    inbox = ROOT / "data" / "inbox" / "uj" / "2027"
    if inbox.exists():
        candidates = sorted(inbox.glob("*.pdf"))
        if candidates:
            return candidates[0]

    shared = ROOT / "universities" / "2027" / "uj.pdf"
    if shared.exists():
        return shared

    return None


@pytest.mark.slow
def test_rotated_code_pages_yield_code_matches_after_repair() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip(
            "UJ 2027 PDF not present at data/inbox/uj/2027/ or "
            "universities/2027/uj.pdf -- skipping on this clone"
        )

    from classify import classify_pages
    from profiles import get_profile

    _classifications, signal_report = classify_pages(pdf_path, get_profile("uj"))

    for page in (46, 47, 62, 95):
        code_matches = signal_report[page]["signals"]["code_matches"]
        assert code_matches >= 1, f"page {page}: expected code_matches >= 1 after repair, got {code_matches}"
