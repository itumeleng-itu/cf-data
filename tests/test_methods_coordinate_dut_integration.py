"""Integration tests for extract/methods/coordinate_dut.py against the
real DUT 2027 PDF. Skips cleanly when the file isn't present."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
from methods.coordinate_dut import extract_dut  # noqa: E402
from profiles import get_profile  # noqa: E402


def _find_dut_2027_pdf() -> Path | None:
    path = ROOT / "data" / "downloads" / "dut_2027.pdf"
    return path if path.exists() else None


def _by_code(records: list[dict], code: str) -> dict | None:
    for r in records:
        if r["qualification_code"] == code:
            return r
    return None


@pytest.mark.slow
def test_full_document_sanity() -> None:
    pdf_path = _find_dut_2027_pdf()
    if pdf_path is None:
        pytest.skip("DUT 2027 PDF not present -- skipping on this clone")

    profile = get_profile("dut")
    records, stats = extract_dut(pdf_path, profile, [])

    assert len({r["qualification_code"] for r in records}) == len(records)
    # No coincidental-word false positives from the fee/module table (the
    # exact failure mode Method D hit on this document, see registry.json) --
    # every code found here comes from a "Qualification Code:" prose label.
    assert "TOTAL" not in {r["qualification_code"] for r in records}
    # Most records should carry a real, non-empty subjects tree.
    with_subjects = sum(1 for r in records if r["requirements"]["nsc"]["subjects"]["rules"])
    assert with_subjects / len(records) > 0.85


@pytest.mark.slow
def test_split_code_two_year_variants_p133() -> None:
    pdf_path = _find_dut_2027_pdf()
    if pdf_path is None:
        pytest.skip("DUT 2027 PDF not present -- skipping on this clone")

    profile = get_profile("dut")
    records, _stats = extract_dut(pdf_path, profile, [])
    mainstream = _by_code(records, "BCHNSG")
    extended = _by_code(records, "BCHNSE")
    assert mainstream is not None and extended is not None
    assert mainstream["duration_years"] == 4 and mainstream["extended"] is False
    assert extended["duration_years"] == 5 and extended["extended"] is True
    assert mainstream["name"] == extended["name"] == "Bachelor of Nursing"


@pytest.mark.slow
def test_bbcst1_matches_hand_verified_page_100() -> None:
    pdf_path = _find_dut_2027_pdf()
    if pdf_path is None:
        pytest.skip("DUT 2027 PDF not present -- skipping on this clone")

    profile = get_profile("dut")
    records, _stats = extract_dut(pdf_path, profile, [])
    record = _by_code(records, "BBCST1")
    assert record is not None
    assert "Construction Studies" in (record["name"] or "")
    tree = record["requirements"]["nsc"]["subjects"]
    levels = {}
    for node in tree["rules"]:
        if node["kind"] == "subject":
            levels[node.get("subject") or node.get("language")] = node["min_level"]
        elif node["kind"] == "any":
            for child in node["rules"]:
                levels[child.get("subject")] = child["min_level"]
    assert levels.get("english") == 4
    assert levels.get("mathematics") == 4
    assert levels.get("technical_mathematics") == 5
    assert levels.get("physical_sciences") == 4
    assert levels.get("technical_sciences") == 5
