"""Tests for the flat-bundle -> requirement-tree conversion.

The mutual-exclusion tests (including both negative controls) are carried
over from the retired tests/test_methods_shared.py, because the logic
under them was carried over too rather than rewritten. They are the
reason "Mathematics required, Mathematical Literacy not accepted" cannot
silently become "Mathematics OR Mathematical Literacy" -- which would
admit learners the university rejects.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "api" / "src"))

from convert_bundle import (  # noqa: E402
    BundleError,
    build_requirements,
    build_score,
    convert_bundle,
    convert_record,
)
from seed_loader import load  # noqa: E402


def _find_any_nodes(node: dict) -> list[dict]:
    found = []
    if node.get("kind") == "any":
        found.append(node)
    for child in node.get("rules", []):
        if isinstance(child, dict):
            found.extend(_find_any_nodes(child))
    return found


def _subjects_in(node: dict) -> set[str]:
    return {r["subject"] for r in node["rules"] if "subject" in r}


# --- "not accepted" vs absent: the whole point of the flat format -------

def test_not_accepted_becomes_an_exclusion() -> None:
    _tree, excluded = build_requirements({"english": 4, "mathematical_literacy": "not_accepted"})
    assert excluded == ["mathematical_literacy"]


def test_explicit_null_is_not_an_exclusion() -> None:
    # B2I02Q's physical_science is "Not applicable" -- it bars nobody.
    _tree, excluded = build_requirements({"english": 4, "physical_science": None})
    assert excluded == []


def test_omitted_key_is_not_an_exclusion() -> None:
    _tree, excluded = build_requirements({"english": 4})
    assert excluded == []


def test_not_accepted_contributes_no_subject_node() -> None:
    tree, _excluded = build_requirements({"english": 4, "mathematical_literacy": "not_accepted"})
    assert tree["rules"] == [{"kind": "subject", "language": "english", "min_level": 4}]


# --- mutually exclusive subjects (carried over from test_methods_shared) -

def test_two_required_group_members_become_one_any() -> None:
    tree, _excluded = build_requirements({"english": 4, "mathematics": 3, "mathematical_literacy": 4})
    any_nodes = _find_any_nodes(tree)
    assert len(any_nodes) == 1
    assert _subjects_in(any_nodes[0]) == {"mathematics", "mathematical_literacy"}


def test_three_required_group_members_become_one_flat_three_way_any() -> None:
    # Not two nested pairwise `any` nodes -- a nested shape does not
    # compare equal to the flat one even though it means the same thing.
    tree, _excluded = build_requirements(
        {"english": 4, "mathematics_or_technical_mathematics": 4, "mathematical_literacy": 5}
    )
    any_nodes = _find_any_nodes(tree)
    assert len(any_nodes) == 1
    assert _subjects_in(any_nodes[0]) == {
        "mathematics", "technical_mathematics", "mathematical_literacy",
    }


def test_required_subject_plus_excluded_group_member_stays_all_b34caq_shape() -> None:
    # Negative control 1. Ground truth B34CAQ: mathematics 5 required,
    # excluded_subjects=[mathematical_literacy, technical_mathematics].
    # Both excluded members are in the SAME group as mathematics --
    # membership alone must not trigger an `any`.
    tree, excluded = build_requirements({
        "english": 4,
        "mathematics": 5,
        "mathematical_literacy": "not_accepted",
        "technical_mathematics": "not_accepted",
    })
    assert excluded == ["mathematical_literacy", "technical_mathematics"]
    assert _find_any_nodes(tree) == []
    assert tree == {
        "kind": "all",
        "rules": [
            {"kind": "subject", "language": "english", "min_level": 4},
            {"kind": "subject", "subject": "mathematics", "min_level": 5},
        ],
    }


def test_required_subject_plus_excluded_group_member_stays_all_b4c01q_shape() -> None:
    # Negative control 2. Real UJ page 82 row, BCOM (LAW) / B4C01Q,
    # "31 with Mathematics ONLY": Mathematics 4 required, Mathematical
    # Literacy explicitly "Not accepted" -- must not become an `any`.
    tree, excluded = build_requirements({
        "english": 5, "mathematics": 4, "mathematical_literacy": "not_accepted",
    })
    assert excluded == ["mathematical_literacy"]
    assert _find_any_nodes(tree) == []


def test_single_group_member_stays_a_plain_subject() -> None:
    tree, _excluded = build_requirements({"mathematics": 5})
    assert _find_any_nodes(tree) == []
    assert tree["rules"] == [{"kind": "subject", "subject": "mathematics", "min_level": 5}]


def test_ungrouped_compound_key_pairs_into_an_any() -> None:
    # physical_sciences/technical_sciences are NOT a national exclusive
    # group (a learner can hold both), so they only pair when the record
    # explicitly says either is accepted.
    tree, _excluded = build_requirements({"physical_sciences_or_technical_sciences": 5})
    any_nodes = _find_any_nodes(tree)
    assert len(any_nodes) == 1
    assert _subjects_in(any_nodes[0]) == {"physical_sciences", "technical_sciences"}


def test_separate_science_keys_do_not_pair_implicitly() -> None:
    tree, _excluded = build_requirements({"physical_science": 5, "life_sciences": 4})
    assert _find_any_nodes(tree) == []


def test_compound_not_accepted_excludes_both_members() -> None:
    _tree, excluded = build_requirements({"mathematics_or_technical_mathematics": "not_accepted"})
    assert excluded == ["mathematics", "technical_mathematics"]


def test_merged_any_keeps_the_position_of_its_first_member() -> None:
    # English stays first, as it is printed and as every existing seed
    # record encodes it.
    tree, _excluded = build_requirements({"english": 4, "mathematics": 3, "mathematical_literacy": 4})
    assert tree["rules"][0] == {"kind": "subject", "language": "english", "min_level": 4}
    assert tree["rules"][1]["kind"] == "any"


# --- language shapes ----------------------------------------------------

def test_language_band_becomes_one_node_with_both_levels() -> None:
    tree, _excluded = build_requirements(
        {"english": {"home_language": 5, "first_additional_language": 6}}
    )
    assert tree["rules"] == [
        {"kind": "subject", "language": "english", "min_level": 5, "min_level_fal": 6}
    ]


def test_any_additional_language_is_always_placed_last() -> None:
    # evaluate() threads "which family already satisfied a rule" left to
    # right through an `all`, so a named language rule must come first or
    # the same language counts twice. Order here is a correctness
    # guarantee, not cosmetic -- even when the operator types the keys
    # the other way round.
    tree, _excluded = build_requirements({"additional_language": 4, "english": 5})
    assert tree["rules"][-1] == {"kind": "any_additional_language", "min_level": 4}
    assert {"kind": "subject", "language": "english", "min_level": 5} in tree["rules"]


def test_band_on_a_non_language_key_is_rejected() -> None:
    with pytest.raises(BundleError):
        build_requirements({"mathematics": {"home_language": 5, "first_additional_language": 6}})


# --- scores -------------------------------------------------------------

def test_plain_aps_becomes_a_single_threshold() -> None:
    assert build_score(26) == ([{"min_score": 26}], [])


def test_variant_aps_becomes_one_threshold_per_subject() -> None:
    score, notes = build_score({"with_mathematics": 31, "with_mathematical_literacy": 32})
    assert score == [
        {"min_score": 31, "requires_subject": "mathematics"},
        {"min_score": 32, "requires_subject": "mathematical_literacy"},
    ]
    assert notes == []


def test_english_rating_banded_aps_encodes_the_strictest_value_and_notes_it() -> None:
    score, notes = build_score(
        {"with_english_rating_5": 24, "with_english_rating_5_upper": 26, "with_english_rating_4": 27}
    )
    assert score == [{"min_score": 27}]
    assert len(notes) == 1 and "strictest" in notes[0]


def test_unknown_aps_variant_key_is_rejected_not_dropped() -> None:
    with pytest.raises(BundleError):
        build_score({"with_astrology": 30})


# --- closed vocabulary --------------------------------------------------

def test_unknown_subject_key_is_rejected_not_dropped() -> None:
    with pytest.raises(BundleError):
        build_requirements({"underwater_basket_weaving": 4})


def test_percentage_in_a_level_field_is_rejected() -> None:
    with pytest.raises(BundleError):
        build_requirements({"mathematics": 60})


def test_singular_prospectus_spellings_are_accepted() -> None:
    tree, _excluded = build_requirements({"physical_science": 5})
    assert tree["rules"] == [{"kind": "subject", "subject": "physical_sciences", "min_level": 5}]


# --- record and bundle level -------------------------------------------

def test_extended_is_derived_from_the_qualification_type_heading() -> None:
    record = convert_record(
        {
            "qualification_code": "X1", "name": "Extended thing",
            "qualification_type": "Extended Degree (4 years)", "duration_years": 4,
            "minimum_aps": 26, "requirements": {"english": 4},
        },
        "uj", 2027, {},
    )
    assert record["extended"] is True


def test_source_document_is_carried_onto_every_record() -> None:
    _institution, records = convert_bundle({
        "institution": {"id": "uj", "name": "UJ", "scoring_strategy": "aps_best6_excl_lo"},
        "academic_year": 2027,
        "source": {"document": "uj/2027/prospectus.pdf"},
        "programmes": [{
            "qualification_code": "X1", "name": "Thing", "duration_years": 3,
            "minimum_aps": 26, "requirements": {"english": 4},
        }],
    })
    assert records[0]["source_doc"] == "uj/2027/prospectus.pdf"


def test_scoreable_defaults_to_true_when_omitted() -> None:
    record = convert_record(
        {"qualification_code": "X1", "name": "Thing", "duration_years": 3,
         "minimum_aps": 26, "requirements": {"english": 4}},
        "uj", 2027, {},
    )
    assert record["scoreable"] is True


def test_scoreable_false_is_carried_through() -> None:
    record = convert_record(
        {"qualification_code": "X1", "name": "Composite Index programme", "duration_years": 4,
         "minimum_aps": 26, "requirements": {"english": 4}, "scoreable": False},
        "uj", 2027, {},
    )
    assert record["scoreable"] is False


def test_scoring_override_defaults_to_none_when_omitted() -> None:
    record = convert_record(
        {"qualification_code": "X1", "name": "Thing", "duration_years": 3,
         "minimum_aps": 26, "requirements": {"english": 4}},
        "uj", 2027, {},
    )
    assert record["scoring_override"] is None
    assert record["scoring_strategy_override"] is None


def test_scoring_override_and_strategy_override_are_carried_through() -> None:
    record = convert_record(
        {"qualification_code": "X1", "name": "Thing", "duration_years": 3,
         "minimum_aps": 26, "requirements": {"english": 4},
         "scoring_override": {"subject_count": 5},
         "scoring_strategy_override": "percentage_sum_div_10"},
        "uj", 2027, {},
    )
    assert record["scoring_override"] == {"subject_count": 5}
    assert record["scoring_strategy_override"] == "percentage_sum_div_10"


def test_a_bad_record_names_its_qualification_code() -> None:
    with pytest.raises(BundleError, match="B00BAD"):
        convert_bundle({
            "institution": {"id": "uj", "name": "UJ", "scoring_strategy": "aps_best6_excl_lo"},
            "academic_year": 2027,
            "programmes": [{
                "qualification_code": "B00BAD", "name": "Thing", "duration_years": 3,
                "minimum_aps": 26, "requirements": {"nonsense": 4},
            }],
        })


# --- against the real hand-verified dataset -----------------------------

_SEEDS = {p["qualification_code"]: p for p in load()["programmes"]}

# Flat transcriptions of nine real UJ records, covering every hard shape
# in the encoded set: a three-way exclusive group, an ungrouped science
# alternative, both language bands, a prose-only exclusion, and both
# negative controls. Each must rebuild its hand-verified tree exactly.
_REAL_CASES: dict[str, tuple[dict, object]] = {
    "B34CAQ": (
        {"english": 4, "mathematics": 5, "mathematical_literacy": "not_accepted",
         "technical_mathematics": "not_accepted"},
        {"with_mathematics": 33},
    ),
    "B6CV3Q": (
        {"english": 4, "mathematics_or_technical_mathematics": 5,
         "physical_sciences_or_technical_sciences": 5},
        {"with_mathematics": 28, "with_technical_mathematics": 28},
    ),
    "B6CS0Q": (
        {"english": 5, "mathematics_or_technical_mathematics": 5,
         "physical_science": 5, "technical_science": "not_accepted"},
        {"with_mathematics": 32, "with_technical_mathematics": 32},
    ),
    "B34HRQ": (
        {"english": 4, "mathematics_or_technical_mathematics": 4, "mathematical_literacy": 5},
        {"with_mathematics": 28, "with_technical_mathematics": 28,
         "with_mathematical_literacy": 28},
    ),
    "B5LAZQ": (
        {"english": {"home_language": 5, "first_additional_language": 6},
         "isizulu": {"home_language": 4, "first_additional_language": 5}},
        28,
    ),
    "B5BFPQ": (
        {"english": {"home_language": 5, "first_additional_language": 6},
         "mathematics": 3, "mathematical_literacy": 5},
        28,
    ),
    "B8CD2Q": (
        {"english": 5, "mathematics": 3, "mathematical_literacy": 4,
         "technical_mathematics": "not_accepted"},
        {"with_mathematics": 25, "with_mathematical_literacy": 26},
    ),
    "B1CISQ": (
        {"english": 4, "mathematics_or_technical_mathematics": 4,
         "mathematical_literacy": "not_accepted"},
        26,
    ),
    "B2I02Q": (
        {"english": 5, "mathematics": 6, "technical_mathematics": "not_accepted",
         "technical_science": "not_accepted", "physical_science": None},
        30,
    ),
}


@pytest.mark.parametrize("code", sorted(_REAL_CASES))
def test_flat_transcription_rebuilds_the_hand_verified_tree(code: str) -> None:
    flat, aps = _REAL_CASES[code]
    tree, excluded = build_requirements(flat)
    score, _notes = build_score(aps)
    assert {"score": score, "subjects": tree, "excluded_subjects": excluded} == (
        _SEEDS[code]["requirements"]["nsc"]
    )


def test_b4l03q_matches_apart_from_the_deliberate_any_additional_language_placement() -> None:
    # The one encoded record whose hand-written rule ORDER differs from
    # what the converter emits: the seed places any_additional_language
    # second, the converter always places it last. Both evaluate
    # identically (English is still consumed first either way); this test
    # pins that the difference is order and nothing else.
    tree, excluded = build_requirements(
        {"english": 5, "additional_language": 4, "mathematics": 3, "mathematical_literacy": 4}
    )
    seed = _SEEDS["B4L03Q"]["requirements"]["nsc"]
    assert excluded == seed["excluded_subjects"]
    assert tree["kind"] == seed["subjects"]["kind"]
    as_text = lambda rules: sorted(json.dumps(r, sort_keys=True) for r in rules)  # noqa: E731
    assert as_text(tree["rules"]) == as_text(seed["subjects"]["rules"])
    assert tree["rules"][-1]["kind"] == "any_additional_language"


# --- seeds/bundle.schema.json must not drift from the converter --------
# The schema is what validates an operator's file while they type it. If
# it accepts a key the converter rejects, the editor says the file is
# fine right up until conversion fails; if it rejects a key the converter
# accepts, the editor cries wolf. Neither is caught by any other test,
# because nothing in the test suite reads the schema at runtime (there is
# no JSON Schema library in this project's dependencies, deliberately).

_SCHEMA = json.loads((ROOT / "seeds" / "bundle.schema.json").read_text(encoding="utf-8"))


def _schema_base_keys() -> set[str]:
    names = _SCHEMA["$defs"]["requirements"]["propertyNames"]["anyOf"]
    return set(names[0]["enum"])


def test_schema_accepts_exactly_the_keys_the_converter_accepts() -> None:
    from app.subjects import LANGUAGE_FAMILIES, Subject
    from convert_bundle import _SUBJECT_ALIASES

    variants = {key for pair in LANGUAGE_FAMILIES.values() for key in pair}
    expected = ({s.value for s in Subject} - variants) | set(LANGUAGE_FAMILIES) | set(_SUBJECT_ALIASES)
    assert _schema_base_keys() == expected | {"additional_language"}


def test_every_key_the_schema_lists_actually_resolves() -> None:
    from convert_bundle import _resolve_slug

    for key in _schema_base_keys() - {"additional_language"}:
        _resolve_slug(key)


def test_schema_aps_bounds_match_the_validator() -> None:
    from validate_data import APS_MAX, APS_MIN

    assert _SCHEMA["$defs"]["aps"]["minimum"] == APS_MIN
    assert _SCHEMA["$defs"]["aps"]["maximum"] == APS_MAX


def test_schema_names_the_not_accepted_sentinel_the_converter_uses() -> None:
    from convert_bundle import NOT_ACCEPTED

    assert _SCHEMA["$defs"]["notAccepted"]["const"] == NOT_ACCEPTED


def test_schema_score_variant_keys_match_the_converter() -> None:
    from convert_bundle import _SCORE_SUBJECT_MAP

    schema_keys = set(_SCHEMA["$defs"]["apsVariants"]["properties"])
    english_banded = {"with_english_rating_5", "with_english_rating_5_upper", "with_english_rating_4"}
    assert schema_keys == set(_SCORE_SUBJECT_MAP) | english_banded


def test_schema_declares_the_scoring_override_and_scoreable_fields() -> None:
    # Extends the schema-drift coverage above to the scoring-generalisation
    # fields: if convert_bundle.py accepts one of these keys but the schema
    # doesn't declare it, an operator's editor flags a perfectly valid
    # field as an error; if the schema declares one convert_record doesn't
    # actually carry through, the editor is silently lying about what
    # taking effect.
    programme_props = set(_SCHEMA["$defs"]["programme"]["properties"])
    assert {"scoring_override", "scoring_strategy_override", "scoreable"} <= programme_props

    record = convert_record(
        {"qualification_code": "X1", "name": "Thing", "duration_years": 3,
         "minimum_aps": 26, "requirements": {"english": 4},
         "scoring_override": {"subject_count": 5},
         "scoring_strategy_override": "percentage_sum_div_10", "scoreable": False},
        "uj", 2027, {},
    )
    assert record["scoring_override"] == {"subject_count": 5}
    assert record["scoring_strategy_override"] == "percentage_sum_div_10"
    assert record["scoreable"] is False


def test_cli_dry_run_converts_and_validates_without_writing(tmp_path: Path) -> None:
    bundle = tmp_path / "uj_2027.json"
    bundle.write_text(json.dumps({
        "institution": {
            "id": "uj", "name": "University of Johannesburg",
            "scoring_strategy": "aps_best6_excl_lo",
            "scoring_config": {"excludes_life_orientation": True, "subject_count": 6},
        },
        "academic_year": 2027,
        "source": {"document": "uj/2027/prospectus.pdf", "retrieved_at": "2026-06-25"},
        "programmes": [{
            "qualification_code": "B34CAQ", "name": "Bachelor of Accounting",
            "faculty": "College of Business and Economics", "campus": ["APK"],
            "duration_years": 3, "source_page": 40, "confidence": "verified",
            "minimum_aps": {"with_mathematics": 33},
            "requirements": {
                "english": 4, "mathematics": 5,
                "mathematical_literacy": "not_accepted",
                "technical_mathematics": "not_accepted",
            },
        }],
    }), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "convert_bundle.py"), str(bundle),
         "--out", str(tmp_path / "seeds"), "--dry-run"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 validation errors" in result.stdout
    assert not (tmp_path / "seeds").exists()


def test_the_worked_example_in_the_docs_converts_exactly_as_documented(tmp_path: Path) -> None:
    # docs/BUNDLE_FORMAT.md shows a two-record bundle and the tree one of
    # them converts to. Both blocks are read back out of the markdown and
    # run, so the document cannot quietly become wrong.
    import re

    md = (ROOT / "docs" / "BUNDLE_FORMAT.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)\n```", md, re.S)
    bundle = next(b for b in blocks if '"programmes": [' in b and "B34CAQ" in b and "B2I02Q" in b)
    expected = json.loads(next(b for b in blocks if '"excluded_subjects": ["mathematical_literacy"' in b))

    source = tmp_path / "uj_2027.json"
    source.write_text(bundle, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "convert_bundle.py"), str(source),
         "--out", str(tmp_path / "seeds")],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr

    records = json.loads((tmp_path / "seeds" / "uj" / "uj_2027.json").read_text(encoding="utf-8"))
    by_code = {r["qualification_code"]: r for r in records}
    assert by_code["B34CAQ"]["requirements"]["nsc"] == expected
    # The other half of the contrast: "not_accepted" excludes, null does not.
    assert by_code["B2I02Q"]["requirements"]["nsc"]["excluded_subjects"] == [
        "technical_mathematics", "technical_sciences",
    ]
    assert by_code["B2I02Q"]["source_doc"] == "uj/2027/prospectus.pdf"


def test_converting_elsewhere_never_writes_into_the_repo_seeds(tmp_path: Path) -> None:
    before = (ROOT / "seeds" / "institutions.json").read_text(encoding="utf-8")
    bundle = tmp_path / "zz_2027.json"
    bundle.write_text(json.dumps({
        "institution": {"id": "zz", "name": "Elsewhere", "scoring_strategy": "aps_best6_excl_lo"},
        "academic_year": 2027,
        "programmes": [{
            "qualification_code": "Z1", "name": "Thing", "duration_years": 3,
            "minimum_aps": 26, "requirements": {"english": 4},
        }],
    }), encoding="utf-8")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "convert_bundle.py"), str(bundle),
         "--out", str(tmp_path / "seeds")],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    assert (tmp_path / "seeds" / "institutions.json").exists()
    assert (ROOT / "seeds" / "institutions.json").read_text(encoding="utf-8") == before


def test_cli_rejects_a_semantically_wrong_bundle(tmp_path: Path) -> None:
    # Maths Lit required at a LOWER level than Mathematics -- the swapped
    # -columns shape scripts/validate_data.py was taught to catch.
    bundle = tmp_path / "uj_2027.json"
    bundle.write_text(json.dumps({
        "institution": {
            "id": "uj", "name": "University of Johannesburg",
            "scoring_strategy": "aps_best6_excl_lo",
        },
        "academic_year": 2027,
        "programmes": [{
            "qualification_code": "B00BAD", "name": "Swapped columns",
            "duration_years": 3, "minimum_aps": 26,
            "requirements": {"english": 4, "mathematics": 5, "mathematical_literacy": 3},
        }],
    }), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "convert_bundle.py"), str(bundle),
         "--out", str(tmp_path / "seeds"), "--dry-run"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 1
    assert "columns likely swapped" in result.stdout
