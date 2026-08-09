"""Tests for extract/selftest.py -- the gate. Method C is always injected
as a fake in these tests (extract_vision_fn parameter) -- no real
OpenRouter call, no cost. What's tested is the SCOPING logic (which pages
trigger Method C) and the GATE MATH (completeness recall, false
agreement), both of which are pure/deterministic given method outputs.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
from selftest import compute_gate, find_genuine_conflict_pages, run_ensemble  # noqa: E402


def _programme(code: str, page: int, **overrides) -> dict:
    base = {
        "qualification_code": code,
        "name": f"Programme {code}",
        "faculty": None,
        "campus": ["APK"],
        "duration_years": None,
        "extended": None,
        "requirements": {
            "nsc": {
                "score": [{"min_score": 30}],
                "subjects": {
                    "kind": "all",
                    "rules": [{"kind": "subject", "language": "english", "min_level": 5}],
                },
                "excluded_subjects": [],
            },
        },
        "selection_notes": [],
        "career_text": None,
        "source_page": page,
    }
    base.update(overrides)
    return base


# --- find_genuine_conflict_pages -----------------------------------------

def test_one_sided_coverage_gap_does_not_trigger_a_page() -> None:
    # A found campus, B didn't even find the row -- not a genuine conflict.
    a = [_programme("X1", page=10, campus=["APK"])]
    b: list[dict] = []
    assert find_genuine_conflict_pages(a, b) == set()


def test_one_sided_field_gap_within_a_shared_code_does_not_trigger() -> None:
    # Both found the row, but only A determined campus -- B abstained on
    # that one field (None), not a disagreement.
    a = [_programme("X1", page=10, campus=["APK"])]
    b = [_programme("X1", page=10, campus=None)]
    assert find_genuine_conflict_pages(a, b) == set()


def test_genuine_both_present_disagreement_triggers_its_page() -> None:
    a = [_programme("X1", page=10, campus=["APK"])]
    b = [_programme("X1", page=10, campus=["DFC"])]
    assert find_genuine_conflict_pages(a, b) == {10}


def test_genuine_subject_tree_disagreement_triggers_its_page() -> None:
    a_tree = {"kind": "all", "rules": [{"kind": "subject", "subject": "mathematics", "min_level": 5}]}
    b_tree = {"kind": "all", "rules": [{"kind": "subject", "subject": "mathematics", "min_level": 4}]}
    a = [_programme("X1", page=20, requirements={"nsc": {"score": None, "subjects": a_tree, "excluded_subjects": []}})]
    b = [_programme("X1", page=20, requirements={"nsc": {"score": None, "subjects": b_tree, "excluded_subjects": []}})]
    assert find_genuine_conflict_pages(a, b) == {20}


def test_agreeing_records_never_trigger() -> None:
    a = [_programme("X1", page=10)]
    b = [_programme("X1", page=10)]
    assert find_genuine_conflict_pages(a, b) == set()


def test_multiple_pages_only_conflicting_ones_included() -> None:
    a = [_programme("X1", page=10, campus=["APK"]), _programme("X2", page=11, campus=["APK"])]
    b = [_programme("X1", page=10, campus=["DFC"]), _programme("X2", page=11, campus=["APK"])]
    assert find_genuine_conflict_pages(a, b) == {10}


# --- run_ensemble: fake Method C, verify scoping ----------------------

def test_run_ensemble_only_calls_vision_on_conflict_pages(monkeypatch) -> None:
    calls = []

    def fake_extract_textlayer(pdf_path, profile, pages):
        return [_programme("X1", page=10, campus=["APK"]), _programme("X2", page=11, campus=["APK"])]

    def fake_extract_geometric(pdf_path, profile, pages):
        return [_programme("X1", page=10, campus=["DFC"]), _programme("X2", page=11, campus=["APK"])]

    def fake_extract_vision(pdf_path, profile, table_pages, api_key, **kwargs):
        calls.append(sorted(table_pages))
        return []

    import selftest
    monkeypatch.setattr(selftest, "extract_textlayer", fake_extract_textlayer)
    monkeypatch.setattr(selftest, "extract_geometric", fake_extract_geometric)

    results, c_pages = run_ensemble(
        Path("fake.pdf"), {}, [10, 11], api_key="fake", extract_vision_fn=fake_extract_vision,
    )
    assert c_pages == {10}
    assert calls == [[10]]
    assert set(results) == {"X1", "X2"}


def test_run_ensemble_skips_vision_entirely_when_no_conflicts(monkeypatch) -> None:
    calls = []

    def fake_extract_textlayer(pdf_path, profile, pages):
        return [_programme("X1", page=10)]

    def fake_extract_geometric(pdf_path, profile, pages):
        return [_programme("X1", page=10)]

    def fake_extract_vision(pdf_path, profile, table_pages, api_key, **kwargs):
        calls.append(table_pages)
        return []

    import selftest
    monkeypatch.setattr(selftest, "extract_textlayer", fake_extract_textlayer)
    monkeypatch.setattr(selftest, "extract_geometric", fake_extract_geometric)

    results, c_pages = run_ensemble(
        Path("fake.pdf"), {}, [10], api_key="fake", extract_vision_fn=fake_extract_vision,
    )
    assert c_pages == set()
    assert calls == []  # never called at all -- zero cost when A and B already agree


def test_run_ensemble_reconciles_with_c_only_on_its_own_page(monkeypatch) -> None:
    def fake_extract_textlayer(pdf_path, profile, pages):
        return [_programme("X1", page=10, campus=["APK"])]

    def fake_extract_geometric(pdf_path, profile, pages):
        return [_programme("X1", page=10, campus=["DFC"])]

    def fake_extract_vision(pdf_path, profile, table_pages, api_key, **kwargs):
        return [_programme("X1", page=10, campus=["APK"])]

    import selftest
    monkeypatch.setattr(selftest, "extract_textlayer", fake_extract_textlayer)
    monkeypatch.setattr(selftest, "extract_geometric", fake_extract_geometric)

    results, c_pages = run_ensemble(
        Path("fake.pdf"), {}, [10], api_key="fake", extract_vision_fn=fake_extract_vision,
    )
    merged, confidence = results["X1"]
    # A and C agree (APK), B is now the minority -- majority wins at 0.66,
    # not the 0.0 it would have been with just A vs B.
    assert merged["campus"] == ["APK"]
    assert confidence["campus"] == 0.66


# --- compute_gate ---------------------------------------------------------

def test_compute_gate_completeness_recall() -> None:
    ground_truth = [_programme("X1", page=10), _programme("X2", page=10), _programme("X3", page=10)]
    results = {
        "X1": ({"qualification_code": "X1", "name": "Programme X1", "campus": ["APK"],
                "requirements": {"nsc": {"score": [{"min_score": 30}], "subjects": {"kind": "all", "rules": []}, "excluded_subjects": []}}}, {}),
        "X2": ({"qualification_code": "X2", "name": "Programme X2", "campus": ["APK"],
                "requirements": {"nsc": {"score": [{"min_score": 30}], "subjects": {"kind": "all", "rules": []}, "excluded_subjects": []}}}, {}),
    }
    gate = compute_gate(results, ground_truth)
    assert gate["programmes_found"] == 2
    assert gate["programmes_present"] == 3
    assert abs(gate["completeness_recall"] - 2 / 3) < 1e-9


def test_compute_gate_false_agreement_only_counts_confidence_1_0_fields() -> None:
    gt = _programme("X1", page=10, name="Correct Name")
    wrong_merged = _programme("X1", page=10, name="Wrong Name")
    results = {
        "X1": (wrong_merged, {"qualification_code": 1.0, "name": 1.0, "campus": 0.5}),
    }
    gate = compute_gate(results, [gt])
    # name is wrong AND fully agreed -> counts. campus is only 0.5
    # confidence (uncorroborated single source) -> must NOT count even
    # though its value also happens to differ from nothing checked here.
    assert gate["fields_agreed_wrong"] == 1
    assert gate["false_agreement_by_field"] == {"name": 1}


def test_compute_gate_zero_false_agreement_when_all_agreed_fields_correct() -> None:
    gt = _programme("X1", page=10)
    results = {"X1": (_programme("X1", page=10), {name: 1.0 for name, _p, _k in __import__("selftest")._GROUND_TRUTH_FIELDS})}
    gate = compute_gate(results, [gt])
    assert gate["false_agreement_rate"] == 0.0
    assert gate["fields_agreed_wrong"] == 0


def test_compute_gate_missing_record_does_not_crash_false_agreement_count() -> None:
    gt = [_programme("X1", page=10), _programme("MISSING", page=10)]
    results = {"X1": (_programme("X1", page=10), {"qualification_code": 1.0})}
    gate = compute_gate(results, gt)
    assert gate["programmes_found"] == 1
    assert gate["programmes_present"] == 2
