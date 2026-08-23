"""Unit tests for extract/methods/coordinate_cells.py's cell_text() --
the coordinate-based cell-reconstruction primitive Method D depends on.
Synthetic pages only: this module operates purely on word-coordinate
dicts, so a real PDF fixture isn't needed to prove the geometry logic.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
from methods.coordinate_cells import cell_text  # noqa: E402


class _FakeCrop:
    def __init__(self, words: list[dict]) -> None:
        self._words = words

    def extract_words(self, extra_attrs=None, use_text_flow=False) -> list[dict]:
        return self._words


class _FakePage:
    """Records the last crop bbox requested and returns pre-seeded words
    for it, ignoring the actual bbox math -- cell_text's own inset
    arithmetic is trivial and not what these tests are checking."""

    def __init__(self, words: list[dict]) -> None:
        self._words = words
        self.last_bbox = None

    def crop(self, bbox, strict=False):
        self.last_bbox = bbox
        return _FakeCrop(self._words)


def _word(text: str, x0: float, top: float, upright: bool = True) -> dict:
    return {"text": text, "x0": x0, "top": top, "upright": upright}


def test_none_bbox_returns_empty_string() -> None:
    assert cell_text(_FakePage([]), None) == ""


def test_empty_cell_returns_empty_string() -> None:
    page = _FakePage([])
    assert cell_text(page, (0, 0, 10, 10)) == ""


def test_upright_cell_reads_left_to_right_top_to_bottom() -> None:
    # Two lines, each two words -- out of coordinate order in the input
    # list to prove sorting, not insertion order, drives the result.
    words = [
        _word("second", x0=20, top=0),
        _word("line", x0=20, top=10),
        _word("word", x0=0, top=10),
        _word("first", x0=0, top=0),
    ]
    page = _FakePage(words)
    assert cell_text(page, (0, 0, 50, 20)) == "first second word line"


def test_rotated_single_line_cell_is_read_bottom_to_top_and_reversed() -> None:
    # Bottom-to-top rotated text: pdfplumber emits each word's characters
    # reversed, and reading order along one visual line runs from LARGER
    # top to SMALLER top -- both must be undone.
    words = [
        # pdfplumber stores a rotated word's characters already reversed --
        # "First"[::-1] is what its own `text` field would hold on a real page.
        _word("First"[::-1], x0=5, top=20, upright=False),  # "First" at the bottom
        _word("Second"[::-1], x0=5, top=10, upright=False),  # "Second" above it
    ]
    page = _FakePage(words)
    assert cell_text(page, (0, 0, 20, 30)) == "First Second"


def test_rotated_multi_line_cell_joins_lines_by_ascending_x0() -> None:
    # Two rotated visual lines side by side (different x0 buckets), each
    # itself bottom-to-top -- the failure mode cell_text exists to fix:
    # table.extract() interleaves these into "Literacy OR Mathematics
    # Mathematical with with 25 26" instead of two clean lines.
    words = [
        _word("25"[::-1], x0=5, top=20, upright=False),   # "25" bottom of line 1
        _word("with"[::-1], x0=5, top=10, upright=False),  # "with" above it
        _word("26"[::-1], x0=15, top=20, upright=False),   # "26" bottom of line 2
        _word("with"[::-1], x0=15, top=10, upright=False),  # "with" above it
    ]
    page = _FakePage(words)
    assert cell_text(page, (0, 0, 30, 30)) == "25 with\n26 with"


def test_insets_bbox_by_half_a_point_before_cropping() -> None:
    page = _FakePage([_word("x", x0=1, top=1)])
    cell_text(page, (10.0, 20.0, 30.0, 40.0))
    assert page.last_bbox == (10.5, 20.5, 29.5, 39.5)
