"""Tests for extract/institution_map.py -- the explicit, hand-written
name -> institution_id mapping. No network; pure logic tests."""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
from institution_map import (  # noqa: E402
    INSTITUTIONS,
    MULTI_INSTITUTION_DOCUMENTS,
    find_multi_institution_document,
    resolve_institution_id,
)


def test_covers_all_26_sa_public_universities() -> None:
    assert len(INSTITUTIONS) == 26


def test_resolves_every_institution_by_its_canonical_name() -> None:
    for institution_id, canonical_name in INSTITUTIONS.items():
        assert resolve_institution_id(canonical_name) == institution_id


def test_resolves_common_abbreviations() -> None:
    assert resolve_institution_id("UJ") == "uj"
    assert resolve_institution_id("CPUT") == "cput"
    assert resolve_institution_id("Wits") == "wits"


def test_resolves_real_observed_variant_with_parenthetical_abbreviation() -> None:
    assert resolve_institution_id("Cape Peninsula University of Technology (CPUT)") == "cput"
    assert resolve_institution_id("University Of Venda (Univen)") == "univen"
    # iYunivesithi Walter Sisulu -- the isiXhosa name apply.org.za actually
    # uses; would have gone UNMAPPED without checking the real page.
    assert resolve_institution_id("iYunivesithi Walter Sisulu (WSU)") == "wsu"


def test_resolution_is_case_insensitive_and_whitespace_tolerant() -> None:
    assert resolve_institution_id("  university   of johannesburg (uj)  ") == "uj"


def test_unknown_name_reports_unmapped_rather_than_guessing() -> None:
    assert resolve_institution_id("Some New College Nobody Has Registered") is None


def test_kzn_cao_returns_skipped_with_its_reason() -> None:
    key = find_multi_institution_document("KZN-CAO Handbook 2027", "kzn-cao-handbook-2027")
    assert key == "kzn-cao"
    doc = MULTI_INSTITUTION_DOCUMENTS[key]
    assert doc["covers"] == ["ukzn", "dut", "mut", "unizulu"]
    assert "Central Applications Office" in doc["skip_reason"]


def test_non_multi_institution_document_returns_none() -> None:
    assert find_multi_institution_document(
        "University of Johannesburg (UJ)", "university-of-johannesburg-uj-prospectus-2027"
    ) is None


def test_unregistered_multi_institution_document_reports_unmapped_not_guessed() -> None:
    # "Central Applications Office (CAO)" from apply.org.za is a DIFFERENT
    # multi-institution document than kzn-cao and isn't registered yet --
    # it must resolve to neither a mapped institution_id nor a skip, only
    # UNMAPPED, for a human to review and add.
    assert find_multi_institution_document("Central Applications Office (CAO)", "cao") is None
    assert resolve_institution_id("Central Applications Office (CAO)") is None
