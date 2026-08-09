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
from selftest import _names_equal, _scores_equal, compute_gate, find_genuine_conflict_pages, run_ensemble  # noqa: E402


# --- _names_equal / _scores_equal: comparison, not raw equality ----------

def test_names_equal_case_and_whitespace_insensitive() -> None:
    assert _names_equal("Civil Engineering", "CIVIL   ENGINEERING") is True


def test_names_equal_short_form_contained_in_full_title() -> None:
    assert _names_equal("Civil Engineering", "Bachelor of Engineering in Civil Engineering") is True
    assert _names_equal("Bachelor of Engineering in Civil Engineering", "Civil Engineering") is True


def test_names_equal_genuinely_different_names_still_fail() -> None:
    assert _names_equal("Civil Engineering", "Mechanical Engineering") is False


def test_names_equal_none_only_matches_none() -> None:
    assert _names_equal(None, None) is True
    assert _names_equal(None, "Civil Engineering") is False


def test_scores_equal_ignores_redundant_null_requires_subject() -> None:
    a = [{"min_score": 32}]
    b = [{"min_score": 32, "requires_subject": None}]
    assert _scores_equal(a, b) is True


def test_scores_equal_order_insensitive() -> None:
    a = [{"min_score": 32, "requires_subject": "mathematics"}, {"min_score": 32, "requires_subject": "technical_mathematics"}]
    b = [{"min_score": 32, "requires_subject": "technical_mathematics"}, {"min_score": 32, "requires_subject": "mathematics"}]
    assert _scores_equal(a, b) is True


def test_scores_equal_single_entry_vs_conditional_pair_still_differs() -> None:
    # A real completeness gap, not a formatting artefact -- must not be
    # normalised away.
    single = [{"min_score": 32}]
    conditional = [
        {"min_score": 32, "requires_subject": "mathematics"},
        {"min_score": 32, "requires_subject": "technical_mathematics"},
    ]
    assert _scores_equal(single, conditional) is False


def test_scores_equal_different_thresholds_differ() -> None:
    assert _scores_equal([{"min_score": 32}], [{"min_score": 30}]) is False


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


def test_name_formatting_difference_does_not_trigger_a_page() -> None:
    # Short form vs full title -- not a real disagreement, must not spend
    # Method C resolving a comparison artefact.
    a = [_programme("X1", page=10, name="Civil Engineering")]
    b = [_programme("X1", page=10, name="Bachelor of Engineering in Civil Engineering")]
    assert find_genuine_conflict_pages(a, b) == set()


def test_score_redundant_null_does_not_trigger_a_page() -> None:
    a = [_programme("X1", page=10, requirements={"nsc": {
        "score": [{"min_score": 32}], "subjects": {"kind": "all", "rules": []}, "excluded_subjects": [],
    }})]
    b = [_programme("X1", page=10, requirements={"nsc": {
        "score": [{"min_score": 32, "requires_subject": None}], "subjects": {"kind": "all", "rules": []}, "excluded_subjects": [],
    }})]
    assert find_genuine_conflict_pages(a, b) == set()


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
        return [], {"model": "fake/model", "pages_attempted": 1, "pages_parsed": 1, "pages_abstained": 0}

    import selftest
    monkeypatch.setattr(selftest, "extract_textlayer", fake_extract_textlayer)
    monkeypatch.setattr(selftest, "extract_geometric", fake_extract_geometric)

    results, c_pages, vision_stats = run_ensemble(
        Path("fake.pdf"), {}, [10, 11], api_key="fake", extract_vision_fn=fake_extract_vision,
    )
    assert c_pages == {10}
    assert calls == [[10]]
    assert set(results) == {"X1", "X2"}
    assert vision_stats["model"] == "fake/model"


def test_run_ensemble_skips_vision_entirely_when_no_conflicts(monkeypatch) -> None:
    calls = []

    def fake_extract_textlayer(pdf_path, profile, pages):
        return [_programme("X1", page=10)]

    def fake_extract_geometric(pdf_path, profile, pages):
        return [_programme("X1", page=10)]

    def fake_extract_vision(pdf_path, profile, table_pages, api_key, **kwargs):
        calls.append(table_pages)
        return [], {"model": "fake/model", "pages_attempted": 1, "pages_parsed": 1, "pages_abstained": 0}

    import selftest
    monkeypatch.setattr(selftest, "extract_textlayer", fake_extract_textlayer)
    monkeypatch.setattr(selftest, "extract_geometric", fake_extract_geometric)

    results, c_pages, vision_stats = run_ensemble(
        Path("fake.pdf"), {}, [10], api_key="fake", extract_vision_fn=fake_extract_vision,
    )
    assert c_pages == set()
    assert calls == []  # never called at all -- zero cost when A and B already agree
    assert vision_stats["model"] is None  # nothing ran -- not attributable to any model


def test_run_ensemble_reconciles_with_c_only_on_its_own_page(monkeypatch) -> None:
    def fake_extract_textlayer(pdf_path, profile, pages):
        return [_programme("X1", page=10, campus=["APK"])]

    def fake_extract_geometric(pdf_path, profile, pages):
        return [_programme("X1", page=10, campus=["DFC"])]

    def fake_extract_vision(pdf_path, profile, table_pages, api_key, **kwargs):
        return [_programme("X1", page=10, campus=["APK"])], {
            "model": "fake/model", "pages_attempted": 1, "pages_parsed": 1, "pages_abstained": 0,
        }

    import selftest
    monkeypatch.setattr(selftest, "extract_textlayer", fake_extract_textlayer)
    monkeypatch.setattr(selftest, "extract_geometric", fake_extract_geometric)

    results, c_pages, _vision_stats = run_ensemble(
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


def test_compute_gate_name_format_difference_is_not_false_agreement() -> None:
    # The exact real-world shape that inflated the first live run's false-
    # agreement figure: ground truth's full title vs the ensemble's
    # shorter consensus name -- correct, not an error.
    gt = _programme("X1", page=10, name="Bachelor of Engineering in Civil Engineering")
    merged = _programme("X1", page=10, name="Civil Engineering")
    results = {"X1": (merged, {"name": 1.0})}
    gate = compute_gate(results, [gt])
    assert gate["fields_agreed_wrong"] == 0
    assert gate["false_agreement_by_field"] == {}


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


def test_compute_gate_queue_fraction_over_full_ensemble_not_just_ground_truth() -> None:
    # Two records need review (a real, non-unanimous field), one doesn't
    # -- 2/3, regardless of whether any of them happen to be in the
    # (empty here) ground-truth sample. needs_review is recomputed from
    # confidence, not read off a pre-set verification flag -- see the
    # unpopulated-fields tests below for why.
    results = {
        "X1": (_programme("X1", page=10), {"campus": 0.66}),
        "X2": (
            {**_programme("X2", page=10), "disagreements": {"requirements.nsc.subjects": {"a": {}, "b": {}, "c": {}}}},
            {"requirements.nsc.subjects": 0.0},
        ),
        "X3": (_programme("X3", page=10), {"campus": 1.0}),
    }
    gate = compute_gate(results, ground_truth=[])
    assert gate["records_total"] == 3
    assert gate["records_needing_review"] == 2
    assert abs(gate["queue_fraction"] - 2 / 3) < 1e-9


def test_compute_gate_queue_fraction_zero_when_no_records() -> None:
    gate = compute_gate({}, ground_truth=[])
    assert gate["queue_fraction"] == 0.0


# --- unpopulated fields: excluded from the review trigger -----------------
# duration_years/faculty/extended currently come back None from every
# method -- confidence 0.0 on every record, indistinguishable by value
# alone from a genuine three-way disagreement. Only the latter should
# force review.

def test_field_no_method_ever_populates_does_not_force_review() -> None:
    results = {
        "X1": (_programme("X1", page=10), {"duration_years": 0.0, "campus": 1.0}),
        "X2": (_programme("X2", page=10), {"duration_years": 0.0, "campus": 1.0}),
    }
    gate = compute_gate(results, ground_truth=[])
    assert gate["unpopulated_fields"] == ["duration_years"]
    assert gate["records_needing_review"] == 0
    assert gate["queue_fraction"] == 0.0


def test_field_with_a_real_disagreement_on_any_record_stays_in_the_trigger() -> None:
    # duration_years reaches confidence > 0.0 on X2 (someone actually
    # voted), so it's a real, if imperfectly covered, field -- not
    # "unpopulated" -- and X1's disagreement on it must still count.
    results = {
        "X1": (_programme("X1", page=10), {"duration_years": 0.0}),
        "X2": (_programme("X2", page=10), {"duration_years": 1.0}),
    }
    gate = compute_gate(results, ground_truth=[])
    assert gate["unpopulated_fields"] == []
    assert gate["records_needing_review"] == 1


def test_field_flagged_via_disagreements_even_at_confidence_zero_counts_as_attempted() -> None:
    # All three methods weighed in and disagreed (0.0, genuine 3-way
    # conflict) -- disagreements records that, distinguishing it from
    # "nobody voted at all" even though the confidence value is the same.
    results = {
        "X1": (
            {**_programme("X1", page=10), "disagreements": {"campus": {"a": ["APK"], "b": ["DFC"], "c": ["SWC"]}}},
            {"campus": 0.0},
        ),
    }
    gate = compute_gate(results, ground_truth=[])
    assert gate["unpopulated_fields"] == []
    assert gate["records_needing_review"] == 1


# --- run_ensemble: Method C abstention degrades to A+B gracefully --------

def test_run_ensemble_falls_back_to_ab_when_vision_abstains(monkeypatch) -> None:
    def fake_extract_textlayer(pdf_path, profile, pages):
        return [_programme("X1", page=10, campus=["APK"])]

    def fake_extract_geometric(pdf_path, profile, pages):
        return [_programme("X1", page=10, campus=["DFC"])]

    def fake_extract_vision(pdf_path, profile, table_pages, api_key, **kwargs):
        # Simulates a page that abstained after a JSON-parse retry failure.
        return [], {"model": "fake/model", "pages_attempted": 1, "pages_parsed": 0, "pages_abstained": 1}

    import selftest
    monkeypatch.setattr(selftest, "extract_textlayer", fake_extract_textlayer)
    monkeypatch.setattr(selftest, "extract_geometric", fake_extract_geometric)

    results, c_pages, vision_stats = run_ensemble(
        Path("fake.pdf"), {}, [10], api_key="fake", extract_vision_fn=fake_extract_vision,
    )
    merged, confidence = results["X1"]
    # No third vote arrived -- A vs B alone, both present and disagreeing
    # -> no majority, confidence 0.0, exactly as if Method C had never
    # been scoped in for this page at all.
    assert confidence["campus"] == 0.0
    assert vision_stats["pages_abstained"] == 1
