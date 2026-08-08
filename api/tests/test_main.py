import pytest
from fastapi.testclient import TestClient

CANONICAL_MARKS = [
    {"subject": "english_hl", "percentage": 87},
    {"subject": "afrikaans_fal", "percentage": 85},
    {"subject": "mathematics", "percentage": 88},
    {"subject": "life_orientation", "percentage": 88},
    {"subject": "geography", "percentage": 92},
    {"subject": "life_sciences", "percentage": 87},
    {"subject": "physical_sciences", "percentage": 73},
]


# --- health / readiness -------------------------------------------------------

def test_healthz_always_200(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200


def test_readyz_200_after_load(client: TestClient) -> None:
    assert client.get("/readyz").status_code == 200


def test_readyz_503_before_data_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.main as main_module

    monkeypatch.setattr(main_module, "PROGRAMMES", [])
    monkeypatch.setattr(main_module, "INSTITUTIONS", {})
    # No `with` block -- lifespan never runs, so the patched empty state holds.
    plain_client = TestClient(main_module.app)
    resp = plain_client.get("/readyz")
    assert resp.status_code == 503


# --- headers -------------------------------------------------------------------

def test_qualify_sets_data_version_and_cache_headers(client: TestClient) -> None:
    resp = client.post("/v1/qualify", json={"subjects": CANONICAL_MARKS})
    assert resp.headers["x-data-version"] == "2027.1-test"
    assert resp.headers["cache-control"] == "public, max-age=3600"


# --- /v1/qualify -----------------------------------------------------------------

def test_qualify_canonical_fixture_matches_expected_programmes(client: TestClient) -> None:
    resp = client.post("/v1/qualify", json={"subjects": CANONICAL_MARKS})
    assert resp.status_code == 200
    body = resp.json()
    qualified_codes = {r["qualification_code"] for r in body["qualified"]}
    assert {"B2M52Q", "B2I02Q", "B4L03Q"} <= qualified_codes
    assert body["scores"]["uj"] == 41
    assert body["evaluated_count"] == 29


def test_qualify_sorts_qualified_by_margin_descending(client: TestClient) -> None:
    resp = client.post("/v1/qualify", json={"subjects": CANONICAL_MARKS})
    margins = [r["margin"] for r in resp.json()["qualified"]]
    assert margins == sorted(margins, reverse=True)


def test_qualify_rejects_too_few_subjects(client: TestClient) -> None:
    resp = client.post("/v1/qualify", json={"subjects": CANONICAL_MARKS[:3]})
    assert resp.status_code == 422


def test_qualify_rejects_unknown_subject(client: TestClient) -> None:
    subjects = CANONICAL_MARKS[:6] + [{"subject": "klingon", "percentage": 90}]
    resp = client.post("/v1/qualify", json={"subjects": subjects})
    assert resp.status_code == 422


def test_qualify_institutions_filter_narrows_candidates(client: TestClient) -> None:
    resp = client.post("/v1/qualify", json={"subjects": CANONICAL_MARKS, "institutions": ["nonexistent"]})
    assert resp.status_code == 200
    assert resp.json()["evaluated_count"] == 0


def test_qualify_academic_year_filter_narrows_candidates(client: TestClient) -> None:
    resp = client.post("/v1/qualify", json={"subjects": CANONICAL_MARKS, "academic_year": 1999})
    assert resp.json()["evaluated_count"] == 0


def test_qualify_near_miss_appears_within_failure_cap(client: TestClient) -> None:
    marks = [
        {"subject": "english_hl", "percentage": 87},
        {"subject": "afrikaans_fal", "percentage": 85},
        {"subject": "mathematics", "percentage": 75},  # level 6, one short of B2M52Q's level 7
        {"subject": "life_orientation", "percentage": 88},
        {"subject": "geography", "percentage": 92},
        {"subject": "life_sciences", "percentage": 87},
        {"subject": "physical_sciences", "percentage": 73},
    ]
    resp = client.post("/v1/qualify", json={"subjects": marks})
    body = resp.json()
    entry = next(r for r in body["near_misses"] if r["qualification_code"] == "B2M52Q")
    assert len(entry["failures"]) == 1
    assert entry["failures"][0]["actual_level"] == 6


def test_qualify_excludes_far_misses_from_near_misses(client: TestClient) -> None:
    weak_marks = [
        {"subject": "geography", "percentage": 35},
        {"subject": "history", "percentage": 35},
        {"subject": "tourism", "percentage": 35},
        {"subject": "life_orientation", "percentage": 35},
        {"subject": "accounting", "percentage": 35},
        {"subject": "economics", "percentage": 35},
    ]
    resp = client.post("/v1/qualify", json={"subjects": weak_marks})
    body = resp.json()
    codes = {r["qualification_code"] for r in body["qualified"] + body["near_misses"]}
    assert "B4L03Q" not in codes


def test_qualify_include_near_misses_false_returns_empty(client: TestClient) -> None:
    marks = [
        {"subject": "english_hl", "percentage": 87},
        {"subject": "afrikaans_fal", "percentage": 85},
        {"subject": "mathematics", "percentage": 75},
        {"subject": "life_orientation", "percentage": 88},
        {"subject": "geography", "percentage": 92},
        {"subject": "life_sciences", "percentage": 87},
        {"subject": "physical_sciences", "percentage": 73},
    ]
    resp = client.post("/v1/qualify", json={"subjects": marks, "include_near_misses": False})
    assert resp.json()["near_misses"] == []


def test_qualify_excluded_subject_does_not_reject_when_valid_alternative_held(client: TestClient) -> None:
    marks = CANONICAL_MARKS + [{"subject": "technical_mathematics", "percentage": 60}]
    resp = client.post("/v1/qualify", json={"subjects": marks})
    codes = {r["qualification_code"] for r in resp.json()["qualified"]}
    assert "B2M52Q" in codes  # holds valid mathematics=88 too -- technical_mathematics must not block it


def test_qualify_excluded_subject_absent_gives_generic_missing_subject_message(client: TestClient) -> None:
    # technical_mathematics stands in for mathematics. It still counts
    # toward APS like any other subject (exclusion governs subject rules
    # only, never scoring), so the score clears B2M52Q's 40 on its own --
    # no compensating subject needed. Excluded subjects are invisible, not
    # disqualifying, and there is no special "forbidden subject" message --
    # this must read exactly like any other missing-subject failure, naming
    # Mathematics.
    marks = [
        {"subject": "english_hl", "percentage": 87},
        {"subject": "afrikaans_fal", "percentage": 85},
        {"subject": "technical_mathematics", "percentage": 88},
        {"subject": "life_orientation", "percentage": 88},
        {"subject": "geography", "percentage": 92},
        {"subject": "life_sciences", "percentage": 87},
        {"subject": "physical_sciences", "percentage": 73},
    ]
    resp = client.post("/v1/qualify", json={"subjects": marks})
    entry = next(r for r in resp.json()["near_misses"] if r["qualification_code"] == "B2M52Q")
    assert len(entry["failures"]) == 1
    assert entry["failures"][0]["message"] == "Requires Mathematics as a matric subject"
    assert "Technical Mathematics" not in entry["failures"][0]["message"]


def test_qualify_neither_maths_nor_maths_lit_fails_b8cd2q_with_null_required(client: TestClient) -> None:
    marks = [
        {"subject": "english_hl", "percentage": 87},
        {"subject": "afrikaans_fal", "percentage": 85},
        {"subject": "life_orientation", "percentage": 88},
        {"subject": "geography", "percentage": 92},
        {"subject": "life_sciences", "percentage": 87},
        {"subject": "physical_sciences", "percentage": 73},
    ]
    resp = client.post("/v1/qualify", json={"subjects": marks})
    body = resp.json()
    codes = {r["qualification_code"] for r in body["qualified"]}
    assert "B8CD2Q" not in codes
    entry = next(r for r in body["near_misses"] if r["qualification_code"] == "B8CD2Q")
    assert entry["score_required"] is None
    assert entry["margin"] is None
    assert any(f["kind"] == "score" for f in entry["failures"])


# --- /v1/meta --------------------------------------------------------------------

def test_meta_shape(client: TestClient) -> None:
    resp = client.get("/v1/meta")
    body = resp.json()
    assert body["data_version"] == "2027.1-test"
    assert body["academic_years"] == [2027]
    assert body["institutions"] == {"uj": [2027]}
    assert body["programme_count"] == 29
