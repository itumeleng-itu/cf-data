"""Integration tests for extract/methods/geometric.py (Method B) against
the real UJ 2027 PDF. Skips cleanly when the file isn't present.

Codes are asserted EXACTLY, not membership in {code, reversed(code)}:
this method reads char["upright"] directly per table cell (a raw
pdfplumber attribute, independent of Method A's matrix-derived
text_repair.py) and reverses accordingly, so orientation is no longer
ambiguous even for shape-symmetric codes like B6CS0Q/Q0SC6B.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
from methods.geometric import _is_reversed, extract_geometric  # noqa: E402
from profiles import get_profile  # noqa: E402


class _RaisesOnCrop:
    def crop(self, bbox):
        # Real failure mode, found running Method B across all 40 UJ
        # table pages (not just the hand-picked ones used elsewhere in
        # this file): the "text" strategy can propose a cell bbox
        # entirely outside the page's own bounding box.
        raise ValueError("Bounding box is entirely outside parent page bounding box")


def test_is_reversed_false_when_bbox_is_outside_page_bounds() -> None:
    assert _is_reversed(_RaisesOnCrop(), (48.4, -80.5, 124.3, -71.5)) is False


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


def _by_code(records: list[dict], code: str) -> dict | None:
    for r in records:
        if r["qualification_code"] == code:
            return r
    return None


def _tree_subjects(node: dict) -> set[str]:
    if node.get("kind") in ("all", "any"):
        found: set[str] = set()
        for child in node["rules"]:
            found |= _tree_subjects(child)
        return found
    if node.get("kind") == "subject":
        return {node.get("subject") or node.get("language")}
    return set()


def _find_any_node_with(node: dict, subjects: set[str]) -> bool:
    if node.get("kind") == "any" and _tree_subjects(node) == subjects:
        return True
    if node.get("kind") in ("all", "any"):
        return any(_find_any_node_with(child, subjects) for child in node["rules"])
    return False


@pytest.mark.slow
def test_finds_all_eleven_programme_codes_exactly_on_page_60() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    profile = get_profile("uj")
    records = extract_geometric(pdf_path, profile, [60])
    expected = {"B6CS0Q", "B6ES0Q", "B6MS0Q", "B6CE1Q", "B6CV3Q", "B6EL1Q", "B6EXTQ", "B6IN2Q", "B6MC2Q", "B6MINQ", "B6PY2Q"}
    found = {r["qualification_code"] for r in records}
    assert expected <= found


@pytest.mark.slow
def test_b6cs0q_excludes_technical_sciences_and_alternates_maths() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    profile = get_profile("uj")
    records = extract_geometric(pdf_path, profile, [60])
    record = _by_code(records, "B6CS0Q")
    assert record is not None
    assert record["campus"] == ["APK"]
    assert record["requirements"]["nsc"]["score"][0]["min_score"] == 32
    assert record["requirements"]["nsc"]["excluded_subjects"] == ["technical_sciences"]
    assert _find_any_node_with(record["requirements"]["nsc"]["subjects"], {"mathematics", "technical_mathematics"})


@pytest.mark.slow
def test_b6cv3q_accepts_technical_sciences_as_alternative() -> None:
    # The task's flagged highest-risk shape, verified independently from
    # Method A: same subject, opposite encoding, same page.
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    profile = get_profile("uj")
    records = extract_geometric(pdf_path, profile, [60])
    record = _by_code(records, "B6CV3Q")
    assert record is not None
    assert record["requirements"]["nsc"]["excluded_subjects"] == []
    assert _find_any_node_with(record["requirements"]["nsc"]["subjects"], {"physical_sciences", "technical_sciences"})


@pytest.mark.slow
def test_multiline_name_reads_correctly_since_names_are_upright() -> None:
    # Names aren't rotated at all in this document -- pdfplumber's native
    # table cells should read them correctly with no repair needed.
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    profile = get_profile("uj")
    records = extract_geometric(pdf_path, profile, [60])
    record = _by_code(records, "B6ES0Q")
    assert record is not None
    assert "ELECTRICAL" in (record["name"] or "")


# --- page 68: two header blocks, different column counts -----------------
# See tests/test_methods_textlayer.py for the full explanation: page 68
# repeats its header row once per "Bachelor of X" sub-table, and the two
# occurrences don't share column positions (first block: 4 subject
# columns; second: 5, Mathematics Literacy inserted). A single page-wide
# header applied to every row silently applies the wrong block's columns
# to the other block's data. Fixed via a sequential sweep that replaces
# the active column mapping every time a new header row is seen.

@pytest.mark.slow
def test_first_header_block_four_simultaneous_subjects_matches_ground_truth() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    profile = get_profile("uj")
    records = extract_geometric(pdf_path, profile, [68])
    record = _by_code(records, "B9O02Q")
    assert record is not None
    assert record["campus"] == ["DFC"]
    assert record["requirements"]["nsc"]["score"][0]["min_score"] == 34
    levels = {
        (r.get("subject") or r.get("language")): r["min_level"]
        for r in record["requirements"]["nsc"]["subjects"]["rules"]
    }
    assert levels == {"english": 5, "mathematics": 5, "physical_sciences": 5, "life_sciences": 5}


@pytest.mark.slow
def test_second_header_block_gets_its_own_five_column_mapping() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    profile = get_profile("uj")
    records = extract_geometric(pdf_path, profile, [68])
    record = _by_code(records, "B9ENV1")
    assert record is not None
    assert record["requirements"]["nsc"]["excluded_subjects"] == ["mathematical_literacy"]
    levels = {
        (r.get("subject") or r.get("language")): r["min_level"]
        for r in record["requirements"]["nsc"]["subjects"]["rules"]
    }
    assert levels == {"english": 4, "mathematics": 4, "physical_sciences": 4, "life_sciences": 4}
