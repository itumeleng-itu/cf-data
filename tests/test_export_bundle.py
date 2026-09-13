"""The round-trip gate: seeds -> flat bundle -> requirement tree must
reproduce the tree that is already in seeds/ (and, transitively, in
Postgres -- load_seeds.py copies seeds/ into the database unchanged).

This is the cheapest possible test of whether the flat format is right.
If a real, hand-verified record can't survive the trip, the FORMAT is
missing something -- and this test says so before 150 more records get
typed into it, not after.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from convert_bundle import convert_bundle  # noqa: E402
from export_bundle import (  # noqa: E402
    ExportError,
    export_institution,
    unflatten_programme,
    unflatten_requirements,
    unflatten_score,
)
from seed_loader import load  # noqa: E402

_DATA = load()
_INSTITUTIONS = {i["id"]: i for i in _DATA["institutions"]}
_UJ_PROGRAMMES = [p for p in _DATA["programmes"] if p["institution_id"] == "uj"]
_UJ_SEEDS = {p["qualification_code"]: p for p in _UJ_PROGRAMMES}

# The one documented, pre-existing exception (not introduced by this
# task): any_additional_language's ORIGINAL hand-written position in this
# one seed record differs from convert_bundle.py's own deterministic
# "always last" placement policy (see build_requirements' docstring).
# Both orderings evaluate identically -- evaluator.py only requires that
# any_additional_language come AFTER whichever language rule it must not
# double-count, not that it be in any specific absolute position -- so
# this is a real, harmless divergence in ORDER only, never in content.
_KNOWN_ORDER_ONLY_EXCEPTIONS = {"B4L03Q"}


def _rules_as_multiset(rules: list[dict]) -> list[str]:
    import json
    return sorted(json.dumps(r, sort_keys=True) for r in rules)


def test_every_uj_seed_record_exports_without_error() -> None:
    _bundle, skipped = export_institution(_INSTITUTIONS["uj"], _UJ_PROGRAMMES)
    assert skipped == [], f"{len(skipped)} record(s) could not be exported: {skipped}"


def test_export_produces_exactly_29_programmes() -> None:
    bundle, _skipped = export_institution(_INSTITUTIONS["uj"], _UJ_PROGRAMMES)
    assert len(bundle["programmes"]) == 29


@pytest.mark.parametrize("code", sorted(set(_UJ_SEEDS) - _KNOWN_ORDER_ONLY_EXCEPTIONS))
def test_round_trip_reproduces_the_exact_seed_tree(code: str) -> None:
    """The gate. Export one seed record to flat, convert it straight
    back, and it must be byte-for-byte the tree already in seeds/ --
    for every record except the one documented order-only exception."""
    flat = unflatten_programme(_UJ_SEEDS[code])
    institution, records = convert_bundle({
        "institution": {
            "id": "uj", "name": "University of Johannesburg",
            "scoring_strategy": "aps_best6_excl_lo",
        },
        "academic_year": 2027,
        "programmes": [flat],
    })
    assert records[0]["requirements"]["nsc"] == _UJ_SEEDS[code]["requirements"]["nsc"]


def test_the_one_known_exception_differs_only_in_rule_order_never_in_content() -> None:
    code = "B4L03Q"
    flat = unflatten_programme(_UJ_SEEDS[code])
    _institution, records = convert_bundle({
        "institution": {"id": "uj", "name": "UJ", "scoring_strategy": "aps_best6_excl_lo"},
        "academic_year": 2027,
        "programmes": [flat],
    })
    got = records[0]["requirements"]["nsc"]
    original = _UJ_SEEDS[code]["requirements"]["nsc"]

    assert got["score"] == original["score"]
    assert got["excluded_subjects"] == original["excluded_subjects"]
    assert got["subjects"]["kind"] == original["subjects"]["kind"]
    assert _rules_as_multiset(got["subjects"]["rules"]) == _rules_as_multiset(original["subjects"]["rules"])
    # Pin down that it IS actually reordered, not accidentally identical --
    # this test would be vacuous otherwise.
    assert got["subjects"]["rules"] != original["subjects"]["rules"]


def test_round_trip_through_the_full_export_bundle_output(tmp_path: Path) -> None:
    """Not just the per-record helper -- export_institution's whole
    bundle, converted back via convert_bundle() exactly as
    scripts/ingest_bundle.py would call it."""
    bundle, skipped = export_institution(_INSTITUTIONS["uj"], _UJ_PROGRAMMES)
    assert skipped == []

    _institution, records = convert_bundle(bundle)
    by_code = {r["qualification_code"]: r for r in records}
    assert set(by_code) == set(_UJ_SEEDS)

    mismatches = [
        code for code, rec in by_code.items()
        if code not in _KNOWN_ORDER_ONLY_EXCEPTIONS
        and rec["requirements"]["nsc"] != _UJ_SEEDS[code]["requirements"]["nsc"]
    ]
    assert mismatches == [], f"round trip diverged for: {mismatches}"


def test_exported_bundle_carries_one_shared_source_document() -> None:
    bundle, _skipped = export_institution(_INSTITUTIONS["uj"], _UJ_PROGRAMMES)
    assert bundle["source"]["document"] == "uj_undergrad_prospectus2027"


def test_exported_institution_block_matches_seeds_institutions_json() -> None:
    bundle, _skipped = export_institution(_INSTITUTIONS["uj"], _UJ_PROGRAMMES)
    assert bundle["institution"]["id"] == "uj"
    assert bundle["institution"]["scoring_strategy"] == "aps_best6_excl_lo"
    assert bundle["institution"]["scoring_config"] == _INSTITUTIONS["uj"]["scoring_config"]


def test_exported_bundle_never_carries_confidence() -> None:
    # "Confidence is never yours to set" (docs/BUNDLE_FORMAT.md) -- an
    # exported bundle is meant to be re-ingested, not to smuggle a
    # review status back in as if it were bundle-supplied data.
    bundle, _skipped = export_institution(_INSTITUTIONS["uj"], _UJ_PROGRAMMES)
    assert all("confidence" not in p for p in bundle["programmes"])


# --- unit tests for the harder reversal logic ---------------------------

def test_unflatten_auto_group_any_becomes_plain_keys() -> None:
    nsc = {
        "score": [{"min_score": 26}],
        "subjects": {"kind": "all", "rules": [
            {"kind": "any", "rules": [
                {"kind": "subject", "subject": "mathematics", "min_level": 3},
                {"kind": "subject", "subject": "mathematical_literacy", "min_level": 4},
            ]},
        ]},
        "excluded_subjects": [],
    }
    flat = unflatten_requirements(nsc)
    assert flat == {"mathematics": 3, "mathematical_literacy": 4}
    assert "any_of" not in flat


def test_unflatten_manual_any_becomes_any_of() -> None:
    nsc = {
        "score": [{"min_score": 26}],
        "subjects": {"kind": "all", "rules": [
            {"kind": "any", "rules": [
                {"kind": "subject", "subject": "physical_sciences", "min_level": 5},
                {"kind": "subject", "subject": "technical_sciences", "min_level": 5},
            ]},
        ]},
        "excluded_subjects": [],
    }
    flat = unflatten_requirements(nsc)
    assert flat == {"any_of": [{"physical_sciences": 5}, {"technical_sciences": 5}]}


def test_unflatten_two_manual_any_groups_raises() -> None:
    nsc = {
        "score": [{"min_score": 26}],
        "subjects": {"kind": "all", "rules": [
            {"kind": "any", "rules": [
                {"kind": "subject", "subject": "geography", "min_level": 4},
                {"kind": "subject", "subject": "history", "min_level": 4},
            ]},
            {"kind": "any", "rules": [
                {"kind": "subject", "subject": "accounting", "min_level": 4},
                {"kind": "subject", "subject": "business_studies", "min_level": 4},
            ]},
        ]},
        "excluded_subjects": [],
    }
    with pytest.raises(ExportError):
        unflatten_requirements(nsc)


def test_unflatten_excluded_subjects_becomes_not_accepted() -> None:
    nsc = {
        "score": [{"min_score": 26}],
        "subjects": {"kind": "all", "rules": [
            {"kind": "subject", "subject": "mathematics", "min_level": 5},
        ]},
        "excluded_subjects": ["mathematical_literacy", "technical_mathematics"],
    }
    flat = unflatten_requirements(nsc)
    assert flat["mathematical_literacy"] == "not_accepted"
    assert flat["technical_mathematics"] == "not_accepted"
    assert flat["mathematics"] == 5


def test_unflatten_language_band_round_trips() -> None:
    nsc = {
        "score": [{"min_score": 26}],
        "subjects": {"kind": "all", "rules": [
            {"kind": "subject", "language": "english", "min_level": 5, "min_level_fal": 6},
        ]},
        "excluded_subjects": [],
    }
    flat = unflatten_requirements(nsc)
    assert flat == {"english": {"home_language": 5, "first_additional_language": 6}}


def test_unflatten_plain_language_stays_a_bare_level() -> None:
    nsc = {
        "score": [{"min_score": 26}],
        "subjects": {"kind": "all", "rules": [
            {"kind": "subject", "language": "english", "min_level": 4},
        ]},
        "excluded_subjects": [],
    }
    flat = unflatten_requirements(nsc)
    assert flat == {"english": 4}


def test_unflatten_any_additional_language() -> None:
    nsc = {
        "score": [{"min_score": 26}],
        "subjects": {"kind": "all", "rules": [
            {"kind": "any_additional_language", "min_level": 4},
        ]},
        "excluded_subjects": [],
    }
    assert unflatten_requirements(nsc) == {"additional_language": 4}


def test_unflatten_plain_score() -> None:
    assert unflatten_score([{"min_score": 26}]) == 26


def test_unflatten_variant_score() -> None:
    score = [
        {"min_score": 31, "requires_subject": "mathematics"},
        {"min_score": 32, "requires_subject": "mathematical_literacy"},
    ]
    assert unflatten_score(score) == {"with_mathematics": 31, "with_mathematical_literacy": 32}


def test_unflatten_refuses_an_unreversible_score_shape() -> None:
    # The English-rating-banded shape is intentionally lossy going
    # forward (build_score collapses it to one strictest value); there is
    # no single correct flat shape to reconstruct it into.
    with pytest.raises(ExportError):
        unflatten_score([{"min_score": 27}, {"min_score": 27, "requires_subject": "life_orientation"}])


def test_unflatten_top_level_any_node_is_rejected() -> None:
    nsc = {
        "score": [{"min_score": 26}],
        "subjects": {"kind": "any", "rules": [
            {"kind": "subject", "subject": "mathematics", "min_level": 5},
        ]},
        "excluded_subjects": [],
    }
    with pytest.raises(ExportError):
        unflatten_requirements(nsc)


def test_unflatten_unsupported_nested_kind_is_rejected_not_guessed() -> None:
    nsc = {
        "score": [{"min_score": 26}],
        "subjects": {"kind": "all", "rules": [
            {"kind": "all", "rules": [{"kind": "subject", "subject": "mathematics", "min_level": 5}]},
        ]},
        "excluded_subjects": [],
    }
    with pytest.raises(ExportError):
        unflatten_requirements(nsc)


def test_unflatten_any_with_a_language_child_is_rejected() -> None:
    # CellValue/build_subject_tree's alternative-chain grouping (Method
    # A/B's OR marker) can in principle nest a language inside an `any`;
    # export_bundle.py's any_of format has no way to express that, so it
    # must refuse rather than silently drop the language aspect.
    nsc = {
        "score": [{"min_score": 26}],
        "subjects": {"kind": "all", "rules": [
            {"kind": "any", "rules": [
                {"kind": "subject", "language": "english", "min_level": 5},
                {"kind": "subject", "subject": "afrikaans_hl", "min_level": 5},
            ]},
        ]},
        "excluded_subjects": [],
    }
    with pytest.raises(ExportError):
        unflatten_requirements(nsc)


def test_export_skips_and_names_an_unreversible_record_rather_than_crashing() -> None:
    bad_programme = {
        "institution_id": "uj", "academic_year": 2027, "qualification_code": "ZZBAD",
        "name": "Unreversible", "duration_years": 3,
        "requirements": {"nsc": {
            "score": [{"min_score": 27}, {"min_score": 27, "requires_subject": "life_orientation"}],
            "subjects": {"kind": "all", "rules": []},
            "excluded_subjects": [],
        }},
    }
    bundle, skipped = export_institution(_INSTITUTIONS["uj"], [bad_programme])
    assert bundle["programmes"] == []
    assert len(skipped) == 1 and "ZZBAD" in skipped[0]
