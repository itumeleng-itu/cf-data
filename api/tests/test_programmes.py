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
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
SEEDS = ROOT / "seeds"


def _wits_seed() -> list[dict]:
    return json.loads((SEEDS / "wits" / "wits_2027.json").read_text(encoding="utf-8"))


def _seed_course_total(records: list[dict]) -> int:
    return sum(
        len(courses)
        for r in records
        for stream in (r.get("streams") or [])
        for courses in stream["curriculum"].values()
    )


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


def test_list_names_the_streams_of_a_multi_stream_programme(client):
    body = client.get("/v1/programmes", params={"institution": "wits"}).json()
    sba11 = next(p for p in body if p["qualification_code"] == "SBA11")
    assert len(sba11["stream_names"]) == 6
    assert "Microbiology and Biotechnology" in sba11["stream_names"]

    cba00 = next(p for p in body if p["qualification_code"] == "CBA00")
    assert cba00["has_curriculum"] is True
    assert cba00["stream_names"] == [], "a single stream needs no name"


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
    assert body
    d = client.get(
        f"/v1/programmes/{body[0]['institution']}/{body[0]['qualification_code']}"
    ).json()
    assert d["source_doc"]
    assert d["source_page"]
    assert d["confidence"] in {"extracted", "verified"}
    # Every stream names the page its own course list came from, so a
    # multi-stream programme stays checkable page by page.
    assert all(s["source_page"] for s in d["streams"])


# --- the regression that matters -------------------------------------------

def test_wits_course_lists_survive_the_whole_path(client):
    """The counts are fixed deliberately.

    1,530 course requirements across 53 of Wits' 58 programmes were
    extracted from the prospectus and verified page by page. They are
    asserted here as literals, not derived from the response, because a
    derived assertion passes against an empty dataset -- which is exactly
    how they were silently dropped before.
    """
    served = client.get(
        "/v1/programmes", params={"institution": "wits", "with_curriculum": True},
    ).json()
    assert len(served) == 52

    total = streams = 0
    for p in served:
        d = client.get(f"/v1/programmes/wits/{p['qualification_code']}").json()
        assert d["streams"], f"{p['qualification_code']} lost its streams"
        assert any(s["curriculum"] for s in d["streams"]), \
            f"{p['qualification_code']} lost its curriculum"
        streams += len(d["streams"])
        total += len(_entries(d))
    assert total == 1464
    assert streams == 61


def test_served_curriculum_is_identical_to_the_seed(client):
    """Guards the export + load + serialise path, not the data. If the
    served course list diverges from the reviewed file in seeds/, the
    thing a learner sees is no longer the thing that was verified.

    Compares the full entry, not just names, so a dropped `options` list
    or a flipped `choice` flag fails here too."""
    seed = {r["qualification_code"]: r for r in _wits_seed()}
    assert _seed_course_total(list(seed.values())) == 1464

    def strip(entry: dict) -> dict:
        # The response model fills the absent half of the union with
        # null; the seed simply omits it. Same meaning, different bytes.
        return {k: v for k, v in entry.items() if v is not None}

    for code, record in seed.items():
        if not any(s["curriculum"] for s in record.get("streams") or []):
            continue
        d = client.get(f"/v1/programmes/wits/{code}").json()
        got = [
            (s["name"], s["source_page"],
             {stage: [strip(c) for c in courses]
              for stage, courses in s["curriculum"].items()})
            for s in d["streams"]
        ]
        expected = [
            (s.get("name"), s.get("source_page"),
             {stage: [strip(c) for c in courses]
              for stage, courses in s["curriculum"].items()})
            for s in record["streams"]
        ]
        assert got == expected, f"{code} differs from seeds/wits/wits_2027.json"


def test_choices_stay_one_requirement_with_their_options(client):
    """A prospectus "X or Y" is ONE requirement with two ways to satisfy
    it. If the options are flattened into separate entries, or the
    `choice` flag is lost, every alternative reads as compulsory and the
    course list is wrong rather than incomplete."""
    seed = _wits_seed()

    def choices(record: dict) -> list[list[str]]:
        return [
            c["options"]
            for stream in (record.get("streams") or [])
            for courses in stream["curriculum"].values()
            for c in courses if c.get("choice")
        ]

    with_choices = [r for r in seed if choices(r)]
    assert with_choices, "fixture no longer covers choices"
    assert sum(len(choices(r)) for r in with_choices) == 25

    for record in with_choices:
        d = client.get(f"/v1/programmes/wits/{record['qualification_code']}").json()
        assert choices(d) == choices(record), record["qualification_code"]


def test_a_choice_carries_options_and_a_compulsory_carries_a_name(client):
    """The two halves of the union are mutually exclusive. An entry with
    neither -- or both -- means the shape has drifted."""
    served = client.get(
        "/v1/programmes", params={"institution": "wits", "with_curriculum": True},
    ).json()
    seen_choice = seen_compulsory = 0
    for p in served:
        d = client.get(f"/v1/programmes/wits/{p['qualification_code']}").json()
        for c in _entries(d):
            if c["choice"]:
                assert c["options"] and len(c["options"]) >= 2
                assert c["name"] is None
                seen_choice += 1
            else:
                assert c["name"]
                assert c["options"] is None
                seen_compulsory += 1
    assert (seen_choice, seen_compulsory) == (25, 1439)


def test_curriculum_notes_are_not_served_as_courses(client):
    """Instruction prose printed among a course list ("choose two of the
    following") is not a course. It travels in its own field."""
    seed = {r["qualification_code"]: r for r in _wits_seed()}
    noted = [c for c, r in seed.items()
             if any(s.get("curriculum_notes") for s in r.get("streams") or [])]
    assert noted, "fixture no longer covers curriculum notes"

    for code in noted:
        d = client.get(f"/v1/programmes/wits/{code}").json()
        for served, expected in zip(d["streams"], seed[code]["streams"], strict=True):
            assert served["curriculum_notes"] == expected.get("curriculum_notes", [])
            names = {
                c["name"] for courses in served["curriculum"].values()
                for c in courses if c.get("name")
            } | {
                opt for courses in served["curriculum"].values()
                for c in courses for opt in (c.get("options") or [])
            }
            # A note is prose printed among the courses, not a course. The
            # same string appearing in both buckets of ONE stream means the
            # parser could not tell them apart.
            assert not (names & set(served["curriculum_notes"])), \
                f"{code}/{served['name']}: {names & set(served['curriculum_notes'])}"


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


def test_a_withheld_course_list_says_so(client):
    """Five pages set their course list in two parallel bulleted columns,
    which the extractor reads across rather than down. Those lists are
    withheld, and the reason travels with them.

    The point of the field is that "we cannot read this correctly yet" must
    not be silently indistinguishable from "this programme has no courses".
    A client can tell the learner which it is.
    """
    withheld = []
    for p in client.get("/v1/programmes", params={"institution": "wits"}).json():
        d = client.get(f"/v1/programmes/wits/{p['qualification_code']}").json()
        for s in d["streams"]:
            if s["transcription_withheld"]:
                withheld.append((p["qualification_code"], s["source_page"]))
                # A withheld list is empty. A reason beside a populated
                # curriculum would mean one of the two is a lie.
                assert s["curriculum"] == {}
                assert s["curriculum_notes"] == []
    assert sorted(withheld) == [
        ("EFA03", 62), ("MFA03", 84), ("SBA10", 119), ("SBA11", 115), ("SBA21", 124),
    ]


def test_withholding_one_stream_does_not_withhold_its_siblings(client):
    """EFA03 and SBA11 each have one withheld stream and others intact.
    Withholding is per stream, which is the reason streams exist: before
    the split, one unparseable page would have taken the whole code's
    course list with it."""
    for code, kept in (("EFA03", 1), ("SBA11", 5)):
        d = client.get(f"/v1/programmes/wits/{code}").json()
        populated = [s for s in d["streams"] if s["curriculum"]]
        assert len(populated) == kept, code
        assert all(s["transcription_withheld"] is None for s in populated)
