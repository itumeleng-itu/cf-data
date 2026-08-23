"""Integration tests for extract/methods/coordinate.py (Method D) against
the real UJ 2027 PDF. Skips cleanly when the file isn't present, per this
repo's convention (see tests/test_methods_geometric.py)."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
from ground_truth import UJ_2027_TABLE_PAGES  # noqa: E402
from methods.coordinate import extract_coordinate  # noqa: E402
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


def _by_code(records: list[dict], code: str) -> dict | None:
    for r in records:
        if r["qualification_code"] == code:
            return r
    return None


@pytest.mark.slow
def test_full_document_sanity() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    profile = get_profile("uj")
    records, stats = extract_coordinate(pdf_path, profile, sorted(UJ_2027_TABLE_PAGES))

    # ~180 expected (reference script's verified count); one short (179)
    # is the documented, known DI1401/B9ENV1 code_pattern gap (see
    # registry.json's uj quirks) -- not a regression if it holds exactly.
    assert 179 <= len(records) <= 180
    assert len({r["qualification_code"] for r in records}) == len(records)
    assert stats["validation_problems"] == 0


@pytest.mark.slow
def test_b6cs0q_matches_method_b_on_the_hard_technical_stream_case() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    profile = get_profile("uj")
    records, _stats = extract_coordinate(pdf_path, profile, sorted(UJ_2027_TABLE_PAGES))
    record = _by_code(records, "B6CS0Q")
    assert record is not None
    assert record["campus"] == ["APK"]
    assert record["requirements"]["nsc"]["score"] == [{"min_score": 32}]
    assert "technical_sciences" in record["requirements"]["nsc"]["excluded_subjects"]
