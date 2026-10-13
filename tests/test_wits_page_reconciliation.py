"""Reconciles the Wits course lists in seeds/ against the extraction they
came from, page by page.

WHY A SEPARATE CHECK
--------------------
Every other test here asks whether the seed data is internally consistent
and whether it survives conversion and loading. None of them can see a
page that was dropped on the way IN. A programme page that never reached
the bundle is indistinguishable, from inside the repo, from a programme
that prints no course list -- and two real programmes were lost exactly
that way: prospectus page 16 prints one requirements row headed "Bachelor
of Commerce (BCom) in the fields of:" over three sub-bullets, the
admissions extract collapsed all three into the parent row, and CBA10
(Information Systems) and CBA12 (Politics, Philosophy and Economics)
vanished with the 81 courses on pages 51 and 52.

So the reconciliation needs a record from OUTSIDE the seed pipeline:
tests/fixtures/wits_2027_page_counts.json, written from the deterministic
extraction of the prospectus. Every page in it must be accounted for, and
the totals must add up.

The manifest must never be regenerated from the seed. That would compare
the data against itself, which is exactly how an earlier "68/68 pages,
zero failures" passed while five pages were being read across parallel
columns into course names that existed on neither.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
MANIFEST = ROOT / "tests" / "fixtures" / "wits_2027_page_counts.json"
SEED = ROOT / "seeds" / "wits" / "wits_2027.json"


@pytest.fixture(scope="module")
def manifest() -> dict:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {int(page): info for page, info in data["pages"].items()}


@pytest.fixture(scope="module")
def manifest_total() -> int:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["total_courses"]


@pytest.fixture(scope="module")
def streams() -> dict[int, tuple[str, dict]]:
    """Every seed stream, keyed by the prospectus page it was read from."""
    records = json.loads(SEED.read_text(encoding="utf-8"))
    by_page: dict[int, tuple[str, dict]] = {}
    for record in records:
        for stream in record.get("streams") or []:
            page = stream["source_page"]
            assert page not in by_page, (
                f"page {page} is claimed by both {by_page[page][0]} and "
                f"{record['qualification_code']} — one prospectus page "
                "describes one stream"
            )
            by_page[page] = (record["qualification_code"], stream)
    return by_page


def _courses(curriculum: dict | None) -> int:
    return sum(len(v) for v in (curriculum or {}).values())


def test_every_extracted_page_is_accounted_for(manifest, streams):
    """No page may be missing. This is the check that would have caught
    CBA10 and CBA12 the day they were lost."""
    missing = {page: info for page, info in manifest.items()
               if page not in streams}
    assert not missing, (
        "pages in the extraction with no stream in seeds/wits/wits_2027.json: "
        + ", ".join(f"p{p} {i['code']} ({i['courses']} courses)"
                    for p, i in sorted(missing.items())))


def test_no_stream_claims_a_page_the_extraction_never_saw(manifest, streams):
    """The other direction: a stream citing a page that produced no course
    list means its provenance is wrong, and its courses came from
    somewhere unaccounted for."""
    invented = {p: code for p, (code, _) in streams.items() if p not in manifest}
    assert not invented, f"streams citing pages outside the extraction: {invented}"


def test_each_page_serves_exactly_what_was_extracted(manifest, streams):
    """Fewer than the extraction found means conversion lost some; more
    means they came from somewhere else."""
    wrong = []
    for page, (code, stream) in sorted(streams.items()):
        expected = manifest[page]["courses"]
        actual = _courses(stream["curriculum"])
        if actual != expected:
            wrong.append(f"p{page} {code}: extracted {expected}, serves {actual}")
    assert not wrong, "; ".join(wrong)


def test_the_totals_balance(manifest_total, streams):
    """The arithmetic is the point: a page quietly gaining or losing
    courses breaks it even if every per-page check above were somehow
    satisfied."""
    served = sum(_courses(s["curriculum"]) for _, s in streams.values())
    assert served == manifest_total
    # Fixed, so the balance cannot be satisfied by a wholesale drop on
    # both sides -- 0 == 0 would balance too.
    #
    # 1703 until the extractor's prose test was anchored. "select"
    # unanchored matched inside "Selected", so six BULLETED courses
    # whose names begin "Selected topic(s)..." were filed as prose and
    # never reached a learner: two on p52, one each on p62, p63, p97 and
    # p99. Raising this number is therefore a deliberate correction, and
    # the figure stays hard-coded precisely so that the next change to
    # it has to be deliberate too.
    assert served == 1709


def test_nothing_is_transcribed_by_hand(manifest):
    """Five pages were read by eye until the extractor learned to handle
    parallel columns, wrapped items and prose. All 68 are machine-read
    now, which is what makes the manifest an independent record: a hand
    transcription and the seed built from it share one reading, so it
    could only ever confirm the count survived conversion."""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["transcribed_pages"] == 0
    assert data["extracted_pages"] == len(manifest) == 68
    assert all(i["provenance"] == "extracted" for i in manifest.values())


def test_codes_agree_between_the_extraction_and_the_seed(manifest, streams):
    """The page's own printed code must match the record serving it. A
    mismatch means a course list was attached to the wrong programme,
    which no count-based check can detect."""
    wrong = [
        f"p{page}: extraction says {manifest[page]['code']}, "
        f"seed serves it as {code}"
        for page, (code, _) in sorted(streams.items())
        if manifest[page]["code"] != code
    ]
    assert not wrong, "; ".join(wrong)


def test_multi_stream_programmes_keep_their_pages_apart(streams):
    """Four codes span several prospectus pages, one per major. Keying a
    course list on the degree code alone concatenated them, so SBA11
    arrived as 62 undifferentiated courses with "Introductory Life
    Sciences" six times over."""
    by_code: dict[str, list[int]] = {}
    for page, (code, _) in streams.items():
        by_code.setdefault(code, []).append(page)
    multi = {c: sorted(p) for c, p in by_code.items() if len(p) > 1}
    assert multi == {
        "EFA03": [62, 63],
        "MBA05": [76, 77, 78],
        "SBA11": [113, 114, 115, 116, 117, 118],
        "SBA12": [127, 130],
    }
