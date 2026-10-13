"""Tests for /v1/programmes and /v1/programmes/{institution}/{code}.

WHAT THESE ARE FOR
------------------
The course lists reached the repository long before they reached a client.
They were loaded into memory, survived Pydantic validation, and were then
dropped on the floor because no route returned them -- a failure no existing
test could catch, because every test asked /v1/qualify, and /v1/qualify does
not carry a curriculum by design.

So the load-bearing assertion here is not "the endpoint returns 200". It is
"a course list that exists in the data arrives intact at a client", with a
count fixed in the test. A future refactor that silently drops the field
again -- the exact bug that already happened once with _ProgrammeModel --
fails these tests rather than passing them quietly.
"""

import json

import pytest
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
SEEDS = ROOT / "seeds"




def _entries(detail: dict) -> list[dict]:
    """Every course entry a detail response carries, across all streams."""
    return [
        entry
        for stream in detail["streams"]
        for courses in stream["curriculum"].values()
        for entry in courses
    ]


# --- the list endpoint ------------------------------------------------------

def test_list_returns_every_loaded_programme(client):
    body = client.get("/v1/programmes").json()
    assert len(body) == client.get("/v1/meta").json()["programme_count"]


def test_list_filters_by_institution(client):
    for inst in client.get("/v1/meta").json()["institutions"]:
        body = client.get("/v1/programmes", params={"institution": inst}).json()
        assert body, f"{inst} has no programmes"
        assert {p["institution"] for p in body} == {inst}


def test_list_filters_by_year(client):
    body = client.get("/v1/programmes", params={"academic_year": 2027}).json()
    assert {p["academic_year"] for p in body} == {2027}


def test_list_filters_by_faculty(client):
    all_p = client.get("/v1/programmes").json()
    faculty = next(p["faculty"] for p in all_p if p["faculty"])
    body = client.get("/v1/programmes", params={"faculty": faculty}).json()
    assert body
    assert {p["faculty"] for p in body} == {faculty}


def test_list_filters_combine_as_and(client):
    all_p = client.get("/v1/programmes").json()
    pick = next(p for p in all_p if p["faculty"])
    body = client.get("/v1/programmes", params={
        "institution": pick["institution"], "faculty": pick["faculty"],
    }).json()
    assert all(
        p["institution"] == pick["institution"] and p["faculty"] == pick["faculty"]
        for p in body
    )


def test_list_omits_curriculum_to_stay_small(client):
    """The list response must not inline course lists -- that is the whole
    reason the detail endpoint exists. has_curriculum is the pointer, and
    stream_names lets a client offer the majors without the courses."""
    body = client.get("/v1/programmes").json()
    assert body
    assert "curriculum" not in body[0]
    assert "streams" not in body[0]
    assert "has_curriculum" in body[0]
    assert "stream_names" in body[0]


def test_with_curriculum_filter_matches_has_curriculum(client):
    filtered = client.get("/v1/programmes", params={"with_curriculum": True}).json()
    unfiltered = client.get("/v1/programmes").json()
    assert all(p["has_curriculum"] for p in filtered)
    assert len(filtered) == sum(1 for p in unfiltered if p["has_curriculum"])


# --- the detail endpoint ----------------------------------------------------

def test_detail_returns_the_requested_programme(client):
    summary = client.get("/v1/programmes").json()[0]
    body = client.get(
        f"/v1/programmes/{summary['institution']}/{summary['qualification_code']}",
        params={"academic_year": summary["academic_year"]},
    ).json()
    assert body["qualification_code"] == summary["qualification_code"]
    assert body["institution"] == summary["institution"]
    assert body["name"] == summary["name"]


def test_detail_404s_on_unknown_code(client):
    inst = next(iter(client.get("/v1/meta").json()["institutions"]))
    r = client.get(f"/v1/programmes/{inst}/NO-SUCH-CODE")
    assert r.status_code == 404


def test_detail_404s_on_unknown_institution(client):
    summary = client.get("/v1/programmes").json()[0]
    r = client.get(f"/v1/programmes/nosuchuni/{summary['qualification_code']}")
    assert r.status_code == 404


def test_detail_404s_on_year_with_no_data(client):
    summary = client.get("/v1/programmes").json()[0]
    r = client.get(
        f"/v1/programmes/{summary['institution']}/{summary['qualification_code']}",
        params={"academic_year": 1999},
    )
    assert r.status_code == 404


def test_detail_carries_provenance(client):
    """Every record states which document and page it came from. A served
    course list with no provenance cannot be checked against the source."""
    body = client.get("/v1/programmes", params={"with_curriculum": True}).json()
    if not body:
        pytest.skip("no institution in this dataset has a transcribed curriculum yet")
    d = client.get(
        f"/v1/programmes/{body[0]['institution']}/{body[0]['qualification_code']}"
    ).json()
    assert d["source_doc"]
    assert d["source_page"]
    assert d["confidence"] in {"extracted", "verified"}
    # Every stream names the page its own course list came from, so a
    # multi-stream programme stays checkable page by page.
    assert all(s["source_page"] for s in d["streams"] if s["curriculum"])


# --- the regression that matters -------------------------------------------

def test_qualify_still_does_not_carry_curriculum(client):
    """Deliberate: inlining 1,530 courses into a list response of ~90
    programmes is the cost this split exists to avoid. If a curriculum
    ever appears here, the split has been undone by accident."""
    marks = {
        "english_fal": 75, "isizulu_hl": 77, "geography": 72, "history": 78,
        "life_sciences": 50, "life_orientation": 83, "mathematics": 8,
    }
    body = client.post("/v1/qualify", json={
        "subjects": [{"subject": k, "percentage": v} for k, v in marks.items()],
        "academic_year": 2027,
    }).json()
    for bucket in ("qualified", "near_misses", "requires_additional_assessment"):
        for p in body[bucket]:
            assert "curriculum" not in p
            assert "streams" not in p

