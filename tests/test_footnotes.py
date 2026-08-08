"""Tests for extract/footnotes.py -- footnote marker detection and legend
resolution. Synthetic-page unit tests first, then the real UJ case this
module exists for: B2M43Q (page 89) publishes Physical Sciences level 5
with a "**" marker; the marker's LEGEND is defined once at the bottom of
page 88 (the previous page) and shared across the whole multi-page
Faculty of Science section -- confirmed by reading the real PDF before
writing this module. footnotes.py must therefore look backward across
pages for the legend, not assume same-page placement.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
from footnotes import detect_footnote_markers, find_legend_text, find_footnotes_for_code  # noqa: E402

_UJ_PROFILE = {
    "layout": {
        "code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}",
        "footnote_markers": ["*", "**", "***"],
    },
}


# --- detect_footnote_markers: pure string matching -----------------------

def test_detects_double_asterisk_marker_in_cell_text() -> None:
    assert detect_footnote_markers("5 (60%+)**", ["*", "**", "***"]) == ["**"]


def test_prefers_longer_marker_over_substring_marker() -> None:
    # "**" contains "*" as a substring -- a cell marked "**" must not also
    # be reported as carrying a bare "*" footnote.
    assert detect_footnote_markers("4 (50%+)**", ["*", "**"]) == ["**"]


def test_no_markers_found_returns_empty_list() -> None:
    assert detect_footnote_markers("5 (60%+)", ["*", "**", "***"]) == []


# --- find_legend_text: synthetic multi-page fake pdf ----------------------

class _FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _FakePdf:
    def __init__(self, page_texts: list[str]) -> None:
        self.pages = [_FakePage(t) for t in page_texts]


def test_find_legend_text_same_page() -> None:
    pdf = _FakePdf(["Some row.\n** A minimum rating of 5 applies."])
    assert find_legend_text(pdf, page_num=1, marker="**") == "A minimum rating of 5 applies."


def test_find_legend_text_looks_back_across_pages() -> None:
    pdf = _FakePdf([
        "** A minimum rating of 5 for Physical Science applies.",  # page 1
        "Some unrelated row with a ** marker on it.",  # page 2
    ])
    assert find_legend_text(pdf, page_num=2, marker="**") == "A minimum rating of 5 for Physical Science applies."


def test_find_legend_text_returns_none_when_never_defined() -> None:
    pdf = _FakePdf(["Nothing relevant here."])
    assert find_legend_text(pdf, page_num=1, marker="**") is None


def test_find_legend_text_respects_lookback_limit() -> None:
    pdf = _FakePdf(["** The real legend.", "page 2", "page 3", "page 4"])
    assert find_legend_text(pdf, page_num=4, marker="**", max_lookback=2) is None
    assert find_legend_text(pdf, page_num=4, marker="**", max_lookback=3) == "The real legend."


# --- real UJ PDF: B2M43Q's Physical Science module-choice footnote -------

def _find_uj_2027_pdf() -> Path | None:
    downloads = ROOT / "data" / "downloads" / "uj_2027.pdf"
    if downloads.exists():
        return downloads
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
def test_b2m43q_footnote_resolves_across_the_page_boundary() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        found = find_footnotes_for_code(pdf, page_num=89, qualification_code="B2M43Q", profile=_UJ_PROFILE)

    assert len(found) == 1
    entry = found[0]
    assert entry["marker"] == "**"
    assert entry["cell_ref"] == "B2M43Q"
    assert "Physical Science" in entry["footnote_text"]
    assert "Chemistry" in entry["footnote_text"]
