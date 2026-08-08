"""Tests for extract/reconcile.py -- per-field majority vote across three
independent extraction candidates. Pure function, synthetic candidate
dicts only; the candidates' own correctness is Methods A/B/C's job, not
this module's.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
from reconcile import reconcile  # noqa: E402


def _programme(**overrides) -> dict:
    base = {
        "qualification_code": "B6CS0Q",
        "name": "Bachelor of Engineering in Civil Engineering",
        "faculty": "Engineering and the Built Environment",
        "campus": ["APK"],
        "duration_years": 4,
        "extended": False,
        "requirements": {
            "nsc": {
                "score": [{"min_score": 32}],
                "subjects": {
                    "kind": "all",
                    "rules": [
                        {"kind": "subject", "language": "english", "min_level": 5},
                        {"kind": "subject", "subject": "mathematics", "min_level": 5},
                    ],
                },
                "excluded_subjects": [],
            },
        },
        "selection_notes": [],
        "career_text": None,
    }
    base.update(overrides)
    return base


# --- confidence buckets ---------------------------------------------------

def test_all_three_agree_gives_full_confidence() -> None:
    a, b, c = _programme(), _programme(), _programme()
    merged, confidence = reconcile(a, b, c)
    assert confidence["qualification_code"] == 1.0
    assert confidence["name"] == 1.0
    assert merged["qualification_code"] == "B6CS0Q"


def test_two_of_three_agree_majority_wins_minority_recorded() -> None:
    a = _programme(faculty="Engineering and the Built Environment")
    b = _programme(faculty="Engineering and the Built Environment")
    c = _programme(faculty="Engineering")  # Method C misreads the faculty label
    merged, confidence = reconcile(a, b, c)
    assert confidence["faculty"] == 0.66
    assert merged["faculty"] == "Engineering and the Built Environment"
    assert merged["disagreements"]["faculty"]["c"] == "Engineering"


def test_all_three_differ_gives_zero_confidence_and_null_field() -> None:
    a = _programme(duration_years=3)
    b = _programme(duration_years=4)
    c = _programme(duration_years=3.5)
    merged, confidence = reconcile(a, b, c)
    assert confidence["duration_years"] == 0.0
    assert merged["duration_years"] is None
    assert set(merged["disagreements"]["duration_years"].values()) == {3, 4, 3.5}


def test_abstention_does_not_count_as_disagreement() -> None:
    # Method B produced no opinion on campus (None) -- A and C agreeing
    # unanimously among themselves must still read as full confidence,
    # not penalised for B's abstention.
    a = _programme(campus=["APK"])
    b = _programme(campus=None)
    c = _programme(campus=["APK"])
    merged, confidence = reconcile(a, b, c)
    assert confidence["campus"] == 1.0
    assert merged["campus"] == ["APK"]
    assert "campus" not in merged.get("disagreements", {})


def test_single_source_gets_uncorroborated_confidence() -> None:
    a = _programme(campus=["DFC"])
    b = _programme(campus=None)
    c = _programme(campus=None)
    merged, confidence = reconcile(a, b, c)
    assert confidence["campus"] == 0.5
    assert merged["campus"] == ["DFC"]


def test_all_abstain_gives_zero_confidence_and_needs_review() -> None:
    a = _programme(faculty=None)
    b = _programme(faculty=None)
    c = _programme(faculty=None)
    merged, confidence = reconcile(a, b, c)
    assert confidence["faculty"] == 0.0
    assert merged["faculty"] is None
    assert merged["verification"]["needs_review"] is True


# --- the task's own worked example: per-field, not per-record -----------

def test_campus_only_review_when_everything_else_agrees() -> None:
    a = _programme(campus=["APK"])
    b = _programme(campus=["APK"])
    c = _programme(campus=["DFC"])  # only campus disagrees
    merged, confidence = reconcile(a, b, c)
    assert confidence["qualification_code"] == 1.0
    assert confidence["requirements.nsc.score"] == 1.0
    assert confidence["requirements.nsc.subjects"] == 1.0
    assert confidence["campus"] == 0.66
    assert merged["verification"]["needs_review"] is True
    assert set(merged["verification"]["fields"].keys()) - {"campus"} == set()  # nothing else below 1.0


# --- requirements.nsc.subjects: structural, order-insensitive ------------

def test_subject_tree_agrees_even_with_reordered_any_children() -> None:
    tree_a = {
        "kind": "all",
        "rules": [{
            "kind": "any",
            "rules": [
                {"kind": "subject", "subject": "physical_sciences", "min_level": 5},
                {"kind": "subject", "subject": "technical_sciences", "min_level": 5},
            ],
        }],
    }
    tree_b_reordered = {
        "kind": "all",
        "rules": [{
            "kind": "any",
            "rules": [
                {"kind": "subject", "subject": "technical_sciences", "min_level": 5},
                {"kind": "subject", "subject": "physical_sciences", "min_level": 5},
            ],
        }],
    }
    a = _programme(requirements={"nsc": {"score": [{"min_score": 28}], "subjects": tree_a, "excluded_subjects": []}})
    b = _programme(
        requirements={"nsc": {"score": [{"min_score": 28}], "subjects": tree_b_reordered, "excluded_subjects": []}}
    )
    c = _programme(
        requirements={"nsc": {"score": [{"min_score": 28}], "subjects": tree_b_reordered, "excluded_subjects": []}}
    )
    merged, confidence = reconcile(a, b, c)
    assert confidence["requirements.nsc.subjects"] == 1.0


def test_technical_mathematics_exclude_vs_alternative_is_a_real_disagreement() -> None:
    # The task's flagged highest-risk case: one method encodes Technical
    # Mathematics as excluded, another as an accepted `any` alternative --
    # these are NOT the same structure and must not be silently merged.
    excluded_tree = {
        "kind": "all",
        "rules": [{"kind": "subject", "subject": "mathematics", "min_level": 5}],
    }
    alternative_tree = {
        "kind": "all",
        "rules": [{
            "kind": "any",
            "rules": [
                {"kind": "subject", "subject": "mathematics", "min_level": 5},
                {"kind": "subject", "subject": "technical_mathematics", "min_level": 5},
            ],
        }],
    }
    a = _programme(
        requirements={
            "nsc": {"score": [{"min_score": 32}], "subjects": excluded_tree, "excluded_subjects": ["technical_mathematics"]},
        },
    )
    b = _programme(
        requirements={"nsc": {"score": [{"min_score": 32}], "subjects": alternative_tree, "excluded_subjects": []}},
    )
    c = _programme(
        requirements={"nsc": {"score": [{"min_score": 32}], "subjects": alternative_tree, "excluded_subjects": []}},
    )
    merged, confidence = reconcile(a, b, c)
    # 2 of 3 (b, c) agree on the alternative-tree shape -- majority wins.
    assert confidence["requirements.nsc.subjects"] == 0.66
    assert confidence["requirements.nsc.excluded_subjects"] == 0.66
    assert merged["requirements"]["nsc"]["excluded_subjects"] == []
    assert merged["verification"]["needs_review"] is True


# --- fields that are never voted on ---------------------------------------

def test_selection_notes_are_unioned_and_deduped_not_voted() -> None:
    a = _programme(selection_notes=["Waitlist available."])
    b = _programme(selection_notes=["Waitlist available.", "NBT required."])
    c = _programme(selection_notes=[])
    merged, confidence = reconcile(a, b, c)
    assert set(merged["selection_notes"]) == {"Waitlist available.", "NBT required."}
    assert "selection_notes" not in confidence


def test_career_text_always_stays_none() -> None:
    a = _programme(career_text=None)
    b = _programme(career_text=None)
    c = _programme(career_text="Marketing prose Method C should never have produced.")
    merged, _confidence = reconcile(a, b, c)
    assert merged["career_text"] is None


# --- unresolved_footnotes folded into verification -------------------------

def test_unresolved_footnotes_are_folded_into_verification() -> None:
    a = _programme()
    a["unresolved_footnotes"] = [{"marker": "*", "cell_ref": "physical_sciences", "footnote_text": "Reduced to 4 for BEngTech."}]
    b = _programme()
    c = _programme()
    merged, _confidence = reconcile(a, b, c)
    assert merged["verification"]["footnotes"] == a["unresolved_footnotes"]
    assert merged["verification"]["needs_review"] is True


def test_none_candidate_is_treated_as_full_abstention() -> None:
    # A method can abstain on an entire page/record, not just one field.
    a = _programme()
    b = None
    c = _programme()
    merged, confidence = reconcile(a, b, c)
    assert confidence["qualification_code"] == 1.0
    assert merged["qualification_code"] == "B6CS0Q"
