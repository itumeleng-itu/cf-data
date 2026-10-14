"""Reconciles the TUT programmes in seeds/ against the extraction they
came from, page by page.

WHY A SEPARATE CHECK
--------------------
Every other test asks whether the seed data is internally consistent
and whether it survives conversion. None can see a page dropped on the
way IN -- a faculty that never reached the bundle is indistinguishable,
from inside the repo, from a faculty TUT does not offer. Two were lost
exactly that way while this extraction was being built: pages 9 and 16
measured their column widths from a merged first row, reported the
whole page as one column, and silently contributed nothing.

So the reconciliation needs a record from OUTSIDE the seed pipeline:
tests/fixtures/tut_2027_page_counts.json, written from the
deterministic extraction. The manifest must never be regenerated from
the seed -- that would compare the data against itself, which is how an
earlier Wits run reported "68/68 pages, zero failures" while five pages
were wrong.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
MANIFEST = ROOT / "tests" / "fixtures" / "tut_2027_page_counts.json"
SEED = ROOT / "seeds" / "tut" / "tut_2027.json"


@pytest.fixture(scope="module")
def manifest() -> dict:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {int(page): info for page, info in data["pages"].items()}


@pytest.fixture(scope="module")
def records() -> list[dict]:
    return json.loads(SEED.read_text(encoding="utf-8"))


def _by_page(records) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for r in records:
        out.setdefault(r["source_page"], []).append(r)
    return out


def test_every_extracted_page_is_accounted_for(manifest, records):
    """The check that would have caught pages 9 and 16 the day they
    were silently dropped."""
    served = _by_page(records)
    missing = {p: i for p, i in manifest.items() if p not in served}
    assert not missing, (
        "pages in the extraction with no programme in seeds/tut/tut_2027.json: "
        + ", ".join(f"p{p} ({i['programmes']} programmes)"
                    for p, i in sorted(missing.items())))


def test_no_record_claims_a_page_the_extraction_never_saw(manifest, records):
    invented = {r["source_page"] for r in records} - set(manifest)
    assert not invented, f"records citing pages outside the extraction: {invented}"


def test_each_page_serves_exactly_what_was_extracted(manifest, records):
    served = _by_page(records)
    wrong = [
        f"p{page}: extracted {manifest[page]['programmes']}, serves {len(served[page])}"
        for page in sorted(served)
        if len(served[page]) != manifest[page]["programmes"]
    ]
    assert not wrong, "; ".join(wrong)


def test_the_totals_balance(manifest, records):
    total = json.loads(MANIFEST.read_text(encoding="utf-8"))["total_programmes"]
    assert len(records) == total
    # Fixed, so the balance cannot be satisfied by a wholesale drop on
    # both sides -- 0 == 0 would balance too. 124 and not 125 because
    # Dip (Policing) prints two admission ROUTES as two rows and is one
    # programme; TUT's own vanished dataset counted 125 rows.
    assert len(records) == 124


def test_every_faculty_is_present(records):
    """Seven faculties, and a page-count check alone cannot notice one
    going missing if another gains the same number of rows."""
    assert {r["faculty"] for r in records} == {
        "Faculty of Arts and Design",
        "Faculty of Economics and Finance",
        "Faculty of Engineering and the Built Environment",
        "Faculty of Humanities",
        "Faculty of ICT",
        "Faculty of Management Sciences",
        "Faculty of Science",
    }


def test_the_conditional_aps_routes_survive(records):
    """TUT publishes a different APS per mathematics route -- 22 with
    Mathematics, 24 with Mathematical Literacy. Collapsing them to one
    threshold would quietly admit or reject whole cohorts, and no
    count-based check above would notice."""
    acc = next(r for r in records if r["name"] == "Dip (Accounting)")
    entries = {(e["min_score"], e.get("requires_subject"))
               for e in acc["requirements"]["nsc"]["score"]}
    assert entries == {
        (22, "accounting"), (22, "mathematics"), (22, "technical_mathematics"),
        (24, "mathematical_literacy"),
    }


def test_the_experiential_programme_is_not_scored(records):
    """Dip (Fire Technology) is admitted on service and fire
    certificates, with no APS and no subject requirements. Scoring it
    would invent requirements TUT does not state."""
    fire = next(r for r in records if r["name"].startswith("Dip (Fire Technology)"))
    assert fire["scoreable"] is False
    assert fire["requirements"]["nsc"]["subjects"]["rules"] == []
