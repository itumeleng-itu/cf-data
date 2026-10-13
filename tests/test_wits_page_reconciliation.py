"""Reconciles the Wits course lists in seeds/ against the extraction they
came from, page by page.

WHY A SEPARATE CHECK
--------------------
Every other test here asks whether the seed data is internally consistent
and whether it survives conversion and loading. None of them can see a page
that was dropped on the way IN. A programme page that never reached the
bundle is indistinguishable, from inside the repo, from a programme that
prints no course list -- and two real programmes were lost exactly that way:
prospectus page 16 prints one requirements row headed "Bachelor of Commerce
(BCom) in the fields of:" over three sub-bullets, the admissions extract
collapsed all three into the parent row, and CBA10 (Information Systems) and
CBA12 (Politics, Philosophy and Economics) vanished along with the 81
courses on pages 51 and 52.

So the reconciliation needs a record from OUTSIDE the seed pipeline:
tests/fixtures/wits_2027_page_counts.json, written from the deterministic
extraction of the prospectus. Every page in it must be accounted for -- as
courses served, or as a page withheld with a stated reason. Nothing may go
missing quietly, and the totals must add up.

The manifest must never be regenerated from the seed. That would make the
check compare the data against itself, which is the failure mode this whole
exercise kept running into: a check that shares the parser's blind spot
cannot see past it.
"""

import json
from collections import Counter
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
def provenance() -> dict[int, str]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {int(page): info["provenance"] for page, info in data["pages"].items()}


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
    missing = {
        page: info for page, info in manifest.items() if page not in streams
    }
    assert not missing, (
        "pages in the extraction with no stream in seeds/wits/wits_2027.json: "
        + ", ".join(f"p{p} {i['code']} ({i['courses']} courses)"
                    for p, i in sorted(missing.items()))
    )


def test_no_stream_claims_a_page_the_extraction_never_saw(manifest, streams):
    """The other direction: a stream citing a page that produced no course
    list means its provenance is wrong, and its courses came from somewhere
    unaccounted for."""
    invented = {p: code for p, (code, _) in streams.items() if p not in manifest}
    assert not invented, f"streams citing pages outside the extraction: {invented}"


def test_each_served_page_serves_exactly_what_was_extracted(manifest, streams):
    """A page that is served must serve all of its courses. Fewer means
    conversion lost some; more means they came from somewhere else."""
    wrong = []
    for page, (code, stream) in sorted(streams.items()):
        if stream.get("transcription_withheld"):
            continue
        expected = manifest[page]["courses"]
        actual = _courses(stream["curriculum"])
        if actual != expected:
            wrong.append(f"p{page} {code}: extracted {expected}, serves {actual}")
    assert not wrong, "; ".join(wrong)


def test_nothing_is_withheld_any_more(streams):
    """The five pages the extractor could not read were transcribed by
    hand instead, so every page in the prospectus now serves its courses.
    Stated outright because the test below passes vacuously once there is
    nothing withheld, and a silent vacuum is how a regression hides."""
    assert [p for p, (_, s) in streams.items()
            if s.get("transcription_withheld")] == []


def test_a_withheld_page_serves_nothing_and_says_why(manifest, streams):
    """Withholding is the only sanctioned way for a page's courses not to
    be served, and it has to be stated. An empty curriculum with no reason
    is the silent loss this file exists to prevent."""
    for page, (code, stream) in sorted(streams.items()):
        extracted = manifest[page]["courses"]
        withheld = stream.get("transcription_withheld")
        if withheld:
            assert _courses(stream["curriculum"]) == 0, (
                f"p{page} {code} is marked withheld but serves courses")
            assert extracted > 0, (
                f"p{page} {code} is marked withheld but the extraction found "
                "no courses there either — the reason is false")
        elif extracted == 0:
            assert _courses(stream["curriculum"]) == 0


def test_the_totals_balance(manifest, manifest_total, streams):
    """served + withheld == extracted, exactly. The arithmetic is the point:
    any page quietly gaining or losing courses breaks it even if every
    per-page check above were somehow satisfied."""
    served = sum(_courses(s["curriculum"]) for _, s in streams.values())
    withheld = sum(
        manifest[page]["courses"] for page, (_, s) in streams.items()
        if s.get("transcription_withheld")
    )
    assert served + withheld == manifest_total, (
        f"{served} served + {withheld} withheld = {served + withheld}, "
        f"but the page counts total {manifest_total}"
    )
    # Fixed so the balance cannot be satisfied by a wholesale drop on both
    # sides -- 0 + 1657 would balance too.
    assert (served, withheld) == (1657, 0)


def test_the_manifest_states_how_each_page_was_read(provenance):
    """A row is only a CHECK on the seed if it came from somewhere else.

    63 pages come from the deterministic extraction the seed was built
    from, so a page dropped or altered on the way in shows up here as a
    mismatch. 5 were transcribed by hand off the rendered page, because
    the extractor reads two parallel bulleted columns straight across and
    fused course names that exist in neither column. For those five the
    same reading produced both the manifest and the seed, so they confirm
    the count survived conversion and serving, and nothing more.

    Conflating the two would let a hand-written number pose as an
    independent check, so provenance is recorded per page and asserted
    here rather than left implicit."""
    assert set(provenance.values()) == {"extracted", "transcribed"}
    counts = Counter(provenance.values())
    assert counts["extracted"] == 63
    assert counts["transcribed"] == 5
    assert {p for p, v in provenance.items() if v == "transcribed"} == {
        62, 84, 115, 119, 124}


def test_most_pages_are_still_checked_against_an_independent_record(provenance):
    """If hand transcription spread far enough, this file would quietly
    stop being a check at all. Most pages must stay extracted."""
    extracted = sum(1 for v in provenance.values() if v == "extracted")
    assert extracted / len(provenance) > 0.9


def test_codes_agree_between_the_extraction_and_the_seed(manifest, streams):
    """The page's own printed code must match the record serving it. A
    mismatch means a course list was attached to the wrong programme, which
    no count-based check can detect."""
    wrong = [
        f"p{page}: extraction says {manifest[page]['code']}, seed serves it as {code}"
        for page, (code, _) in sorted(streams.items())
        # Synthetic codes exist for admissions rows with no programme page
        # and legitimately differ; they cite no page, so they never appear here.
        if manifest[page]["code"] != code
    ]
    assert not wrong, "; ".join(wrong)
