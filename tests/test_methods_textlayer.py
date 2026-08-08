"""Integration tests for extract/methods/textlayer.py (Method A) against
the real UJ 2027 PDF. Skips cleanly when the file isn't present on this
clone. Spot-checks specific hand-verified ground-truth records
(seeds/uj/*.json) rather than asserting full-page parity -- the formal
completeness/false-agreement gate needs all three extraction methods and
is explicitly out of scope for this checkpoint (see the 8.4 plan).
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
from methods.textlayer import extract_textlayer  # noqa: E402
from profiles import get_profile  # noqa: E402


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


def _records_by_code(pdf_path: Path, pages: list[int]) -> dict[str, dict]:
    profile = get_profile("uj")
    records = extract_textlayer(pdf_path, profile, pages)
    return {r["qualification_code"]: r for r in records}


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


# --- page 60: FEBE engineering table -------------------------------------

@pytest.mark.slow
def test_finds_all_eleven_programmes_on_page_60() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    records = _records_by_code(pdf_path, [60])
    expected_codes = {
        "B6CS0Q", "B6ES0Q", "B6MS0Q", "B6CE1Q", "B6CV3Q",
        "B6EL1Q", "B6EXTQ", "B6IN2Q", "B6MC2Q", "B6MINQ", "B6PY2Q",
    }
    assert expected_codes <= set(records.keys())


@pytest.mark.slow
def test_conditional_aps_code_b6cs0q_matches_ground_truth_structure() -> None:
    # Ground truth (seeds/uj/febe.json): APS 32, English HL/FAL level 5,
    # Mathematics-or-Technical-Mathematics level 5 (an `any` node),
    # Physical Sciences level 5, Technical Sciences excluded. The ground
    # truth ALSO splits APS 32 into two requires_subject-conditional
    # entries (Maths vs Technical Maths) -- a single visible APS cell
    # can't distinguish that, so this method's simpler single-threshold
    # score is a known, accepted limitation, not asserted here.
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    record = _records_by_code(pdf_path, [60])["B6CS0Q"]
    assert record["requirements"]["nsc"]["score"][0]["min_score"] == 32
    assert record["campus"] == ["APK"]
    assert record["requirements"]["nsc"]["excluded_subjects"] == ["technical_sciences"]
    tree = record["requirements"]["nsc"]["subjects"]
    assert _find_any_node_with(tree, {"mathematics", "technical_mathematics"})
    assert "technical_sciences" not in _tree_subjects(tree)


@pytest.mark.slow
def test_two_sibling_any_nodes_b6cv3q_matches_ground_truth() -> None:
    # The task's explicitly flagged highest-risk shape: the SAME subject
    # (Technical Mathematics, Technical Science) is excluded in one
    # programme (B6CS0Q above) and an accepted `any` alternative in
    # another (this one) -- both from the same page, same method run.
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    record = _records_by_code(pdf_path, [60])["B6CV3Q"]
    assert record["requirements"]["nsc"]["score"][0]["min_score"] == 28
    assert record["campus"] == ["DFC"]
    assert record["requirements"]["nsc"]["excluded_subjects"] == []
    tree = record["requirements"]["nsc"]["subjects"]
    assert _find_any_node_with(tree, {"mathematics", "technical_mathematics"})
    assert _find_any_node_with(tree, {"physical_sciences", "technical_sciences"})


@pytest.mark.slow
def test_aps_thresholds_match_ground_truth_across_page_60() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    records = _records_by_code(pdf_path, [60])
    expected_aps = {
        "B6CS0Q": 32, "B6ES0Q": 32, "B6MS0Q": 32, "B6CE1Q": 30, "B6CV3Q": 28,
        "B6EL1Q": 30, "B6EXTQ": 30, "B6IN2Q": 30, "B6MC2Q": 30, "B6MINQ": 23, "B6PY2Q": 30,
    }
    for code, expected in expected_aps.items():
        assert records[code]["requirements"]["nsc"]["score"][0]["min_score"] == expected, code


# --- page 68: Health Sciences, four simultaneous subjects, TWO header blocks
#
# Page 68 repeats its full header row once per "Bachelor of X" sub-table,
# and the two occurrences don't share column positions -- the FIRST block
# (Nursing, Optometry) has 4 subject columns (English/Mathematics/
# Physical Science/Life Science); the SECOND block (Environmental Health)
# has 5, with Mathematics Literacy inserted, compressing every column
# after it leftward. Fixed generally via per-section column association
# (see module docstring point 3), not a page-specific patch.
#
# Ground truth's excluded_subjects for B9N02Q/B9O02Q also lists
# mathematical_literacy/technical_mathematics/technical_sciences -- a
# blanket exclusion stated in surrounding PROSE (the same pattern as the
# Faculty of Science's "PLEASE NOTE" text), not a table cell. Neither
# method reads prose for exclusions; that's a separate, known gap, not
# what this fix addresses. It doesn't change this row's qualify outcome
# either way: the tree only ever looks up "mathematics", so a learner
# without that specific mark fails regardless of what's excluded.

@pytest.mark.slow
def test_first_header_block_four_simultaneous_subjects_matches_ground_truth() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    records = _records_by_code(pdf_path, [68])
    assert "B9O02Q" in records
    record = records["B9O02Q"]
    assert record["campus"] == ["DFC"]
    assert record["requirements"]["nsc"]["score"][0]["min_score"] == 34
    tree_subjects = {
        r.get("subject") or r.get("language")
        for r in record["requirements"]["nsc"]["subjects"]["rules"]
    }
    assert tree_subjects == {"english", "mathematics", "physical_sciences", "life_sciences"}
    levels = {
        (r.get("subject") or r.get("language")): r["min_level"]
        for r in record["requirements"]["nsc"]["subjects"]["rules"]
    }
    assert levels == {"english": 5, "mathematics": 5, "physical_sciences": 5, "life_sciences": 5}


@pytest.mark.slow
def test_second_header_block_gets_its_own_five_column_mapping() -> None:
    # Environmental Health (not in seeds/uj -- verified directly against
    # the real page text instead): NSC REQUIREMENTS shows English/
    # Mathematics/Physical Science/Life Science all at level 4, with
    # Mathematics Literacy explicitly "Not accepted" for this specific
    # programme -- a real per-row exclusion from the SECOND block's own
    # Mathematics Literacy column, only detectable if that block's
    # columns are associated independently of the first block's.
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    records = _records_by_code(pdf_path, [68])
    assert "B9ENV1" in records
    record = records["B9ENV1"]
    assert record["requirements"]["nsc"]["excluded_subjects"] == ["mathematical_literacy"]
    levels = {
        (r.get("subject") or r.get("language")): r["min_level"]
        for r in record["requirements"]["nsc"]["subjects"]["rules"]
    }
    assert levels == {"english": 4, "mathematics": 4, "physical_sciences": 4, "life_sciences": 4}


# --- non-rotated profile: out of scope this pass --------------------------

def test_non_rotated_profile_returns_empty_result() -> None:
    profile = {"layout": {"code_pattern": r"[A-Z]{6}", "rotated_headers": False}}
    assert extract_textlayer(Path("does-not-matter.pdf"), profile, [1]) == []
