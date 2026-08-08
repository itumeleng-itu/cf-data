"""Tests for extract/methods/shared.py -- column/cell interpretation logic
shared by Method A (textlayer) and Method B (geometric). Pure functions,
synthetic input only, no PDF -- the real-PDF spot checks live in
test_methods_textlayer.py/test_methods_geometric.py.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
from methods.shared import (  # noqa: E402
    CellValue,
    build_subject_tree,
    interpret_cell,
    resolve_subject_column,
)

_UJ_PROFILE = {
    "layout": {
        "code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}",
        "header_keywords": ["Minimum APS", "Qualification Code", "CAREER", "CAMPUS", "PROGRAMME"],
        "rotated_headers": True,
        "footnote_markers": ["*", "**"],
        "campus_tokens": ["APK", "APB", "DFC", "SWC"],
        "not_accepted_phrases": ["Not accepted", "Not applicable"],
        "alternative_phrases": ["OR", "or"],
        "mutually_exclusive_subjects": [
            ["mathematics", "mathematical_literacy", "technical_mathematics"],
        ],
    },
}


# --- resolve_subject_column ---------------------------------------------

def test_resolve_subject_column_matches_known_subject() -> None:
    assert resolve_subject_column("Physical Science", _UJ_PROFILE) == "physical_sciences"


def test_resolve_subject_column_matches_technical_mathematics() -> None:
    assert resolve_subject_column("Technical Mathematics", _UJ_PROFILE) == "technical_mathematics"


def test_resolve_subject_column_matches_technical_science() -> None:
    assert resolve_subject_column("Technical Science", _UJ_PROFILE) == "technical_sciences"


def test_resolve_subject_column_matches_english_as_language_family() -> None:
    assert resolve_subject_column("English", _UJ_PROFILE) == "english"


def test_resolve_subject_column_returns_none_for_unrecognised_header() -> None:
    assert resolve_subject_column("CAREER", _UJ_PROFILE) is None


# --- interpret_cell -------------------------------------------------------

def test_interpret_cell_plain_level() -> None:
    result = interpret_cell("5 (60%+)", _UJ_PROFILE)
    assert result.kind == "level"
    assert result.level == 5


def test_interpret_cell_level_without_percentage() -> None:
    result = interpret_cell("4", _UJ_PROFILE)
    assert result.kind == "level"
    assert result.level == 4


def test_interpret_cell_not_accepted() -> None:
    result = interpret_cell("Not accepted", _UJ_PROFILE)
    assert result.kind == "not_accepted"


def test_interpret_cell_alternative() -> None:
    # UJ's real BEngTech Civil Engineering cell shape: "OR 5 (60%+)"
    result = interpret_cell("OR 5 (60%+)", _UJ_PROFILE)
    assert result.kind == "alternative"
    assert result.level == 5


def test_interpret_cell_empty() -> None:
    result = interpret_cell("", _UJ_PROFILE)
    assert result.kind == "empty"


def test_interpret_cell_whitespace_only_is_empty() -> None:
    assert interpret_cell("   ", _UJ_PROFILE).kind == "empty"


def test_interpret_cell_footnote_marker_does_not_block_level_parsing() -> None:
    # UJ's real B2M43Q Physical Science cell shape. Confirmed by direct
    # diagnosis this ALREADY parsed correctly before any stripping was
    # added (the \b-bounded level pattern tolerates a trailing "**" on
    # its own) -- this test guards that behaviour explicitly rather than
    # leaving it as an accident of regex boundaries.
    result = interpret_cell("5 (60%+)**", _UJ_PROFILE)
    assert result.kind == "level"
    assert result.level == 5
    assert "**" in result.raw


def test_resolve_subject_column_strips_footnote_marker_from_header() -> None:
    # The real bug: UJ page 89's header reads "Physical Science **" (the
    # marker on the HEADER itself, not just the data cell) -- this failed
    # the alias lookup outright and dropped the whole column, which is
    # what actually caused B2M43Q's missing physical_sciences, not
    # anything in interpret_cell.
    assert resolve_subject_column("Physical Science **", _UJ_PROFILE) == "physical_sciences"


# --- build_subject_tree ----------------------------------------------------
# The high-risk case the task calls out explicitly: Technical Mathematics
# appears in BOTH roles across UJ. Faculty of Science EXCLUDES it; FEBE
# ACCEPTS it as an alternative to Mathematics in an `any` node. Both must
# come out of this SAME function, driven only by which phrase matched in
# the cell -- never a per-subject special case.

def test_build_subject_tree_excludes_not_accepted_subject() -> None:
    row = [
        ("english", CellValue(kind="level", level=5, raw="5")),
        ("mathematics", CellValue(kind="level", level=5, raw="5 (60%+)")),
        ("technical_mathematics", CellValue(kind="not_accepted", raw="Not accepted")),
    ]
    tree, excluded = build_subject_tree(row, _UJ_PROFILE)
    assert excluded == {"technical_mathematics"}
    # excluded subjects must not appear anywhere in the rule tree itself
    assert "technical_mathematics" not in _flatten_subjects(tree)


def test_build_subject_tree_pairs_alternative_with_preceding_column() -> None:
    # UJ's real BEngTech Civil Engineering row: Physical Science 5 (60%+),
    # then an adjacent "OR Technical Science 5 (60%+)" cell -- the
    # alternative cell pairs with the immediately preceding subject column.
    row = [
        ("english", CellValue(kind="level", level=4, raw="4")),
        ("mathematics", CellValue(kind="level", level=5, raw="5")),
        ("physical_sciences", CellValue(kind="level", level=5, raw="5 (60%+)")),
        ("technical_sciences", CellValue(kind="alternative", level=5, raw="OR 5 (60%+)")),
    ]
    tree, excluded = build_subject_tree(row, _UJ_PROFILE)
    assert excluded == set()
    any_nodes = _find_any_nodes(tree)
    paired = {frozenset(_flatten_subjects(node)) for node in any_nodes}
    assert frozenset({"physical_sciences", "technical_sciences"}) in paired


def test_build_subject_tree_plain_levels_become_all_node() -> None:
    row = [
        ("english", CellValue(kind="level", level=5, raw="5")),
        ("accounting", CellValue(kind="level", level=6, raw="6")),
    ]
    tree, excluded = build_subject_tree(row, _UJ_PROFILE)
    assert excluded == set()
    assert tree["kind"] == "all"
    levels = {r["subject"]: r["min_level"] for r in tree["rules"] if r["kind"] == "subject" and "subject" in r}
    assert levels["accounting"] == 6


def test_build_subject_tree_language_column_becomes_language_node() -> None:
    row = [("english", CellValue(kind="level", level=5, raw="5"))]
    tree, _excluded = build_subject_tree(row, _UJ_PROFILE)
    languages = [r for r in tree["rules"] if r.get("kind") == "subject" and "language" in r]
    assert languages == [{"kind": "subject", "language": "english", "min_level": 5}]


def test_build_subject_tree_empty_cells_are_skipped() -> None:
    row = [
        ("english", CellValue(kind="level", level=5, raw="5")),
        ("technical_sciences", CellValue(kind="empty", raw="")),
    ]
    tree, excluded = build_subject_tree(row, _UJ_PROFILE)
    assert excluded == set()
    assert "technical_sciences" not in _flatten_subjects(tree)


# --- build_subject_tree: implicit mutually-exclusive subject groups ------
# Mathematics vs Mathematical Literacy has no "/" merge and no "OR" marker
# in UJ's tables -- the alternative is national NSC convention, declared
# per-institution in profile.layout.mutually_exclusive_subjects, not
# hardcoded here. Two level-bearing cells from the same configured group
# must become an `any`, even with zero markers; a group member marked
# not_accepted must still go to excluded_subjects, unchanged.

def test_two_group_members_with_levels_become_any_b8cd2q_shape() -> None:
    # Ground truth B8CD2Q: any[mathematics 3, mathematical_literacy 4].
    row = [
        ("english", CellValue(kind="level", level=5, raw="5")),
        ("mathematics", CellValue(kind="level", level=3, raw="3")),
        ("mathematical_literacy", CellValue(kind="level", level=4, raw="4")),
    ]
    tree, excluded = build_subject_tree(row, _UJ_PROFILE)
    assert excluded == set()
    any_nodes = _find_any_nodes(tree)
    paired = {frozenset(_flatten_subjects(node)) for node in any_nodes}
    assert frozenset({"mathematics", "mathematical_literacy"}) in paired
    levels_in_any = {
        r["subject"]: r["min_level"]
        for node in any_nodes for r in node["rules"]
        if frozenset(_flatten_subjects(node)) == frozenset({"mathematics", "mathematical_literacy"})
    }
    assert levels_in_any == {"mathematics": 3, "mathematical_literacy": 4}


def test_three_group_members_with_levels_become_one_any_b34hrq_shape() -> None:
    # Ground truth B34HRQ: any[mathematics 4, technical_mathematics 4,
    # mathematical_literacy 5] -- three separate plain header columns on
    # that page, no merge, no marker.
    row = [
        ("english", CellValue(kind="level", level=4, raw="4")),
        ("mathematics", CellValue(kind="level", level=4, raw="4")),
        ("mathematical_literacy", CellValue(kind="level", level=5, raw="5")),
        ("technical_mathematics", CellValue(kind="level", level=4, raw="4")),
    ]
    tree, excluded = build_subject_tree(row, _UJ_PROFILE)
    assert excluded == set()
    any_nodes = _find_any_nodes(tree)
    group = {"mathematics", "mathematical_literacy", "technical_mathematics"}
    matching = [n for n in any_nodes if _flatten_subjects(n) == group]
    assert len(matching) == 1, "expected exactly one 3-way any node, not several pairwise ones"


def test_required_subject_plus_excluded_group_member_stays_all_b34caq_shape() -> None:
    # Negative control 1. Ground truth B34CAQ: mathematics 5 required,
    # excluded_subjects=[mathematical_literacy, technical_mathematics].
    # Both excluded members are in the SAME configured group as
    # mathematics -- membership alone must not trigger an `any`.
    row = [
        ("english", CellValue(kind="level", level=4, raw="4")),
        ("mathematics", CellValue(kind="level", level=5, raw="5")),
        ("mathematical_literacy", CellValue(kind="not_accepted", raw="Not accepted")),
        ("technical_mathematics", CellValue(kind="not_accepted", raw="Not accepted")),
    ]
    tree, excluded = build_subject_tree(row, _UJ_PROFILE)
    assert excluded == {"mathematical_literacy", "technical_mathematics"}
    assert _find_any_nodes(tree) == []
    assert tree == {
        "kind": "all",
        "rules": [
            {"kind": "subject", "language": "english", "min_level": 4},
            {"kind": "subject", "subject": "mathematics", "min_level": 5},
        ],
    }


def test_required_subject_plus_excluded_group_member_stays_all_b4c01q_shape() -> None:
    # Negative control 2. Real page 82 row (not in seeds, verified
    # directly against the PDF -- BCOM (LAW), Q10C4B/B4C01Q, "31 with
    # Mathematics ONLY"): Mathematics 4 required, Mathematical Literacy
    # explicitly "Not accepted" -- must not become an `any`. (An earlier
    # manual read of this page's concatenated raw text misattributed a
    # neighbouring row's value and called this level 3 -- corrected here
    # against the actual column-by-column extraction.)
    row = [
        ("english", CellValue(kind="level", level=5, raw="5")),
        ("mathematics", CellValue(kind="level", level=4, raw="4")),
        ("mathematical_literacy", CellValue(kind="not_accepted", raw="Not accepted")),
    ]
    tree, excluded = build_subject_tree(row, _UJ_PROFILE)
    assert excluded == {"mathematical_literacy"}
    assert _find_any_nodes(tree) == []


def test_single_group_member_present_stays_plain_subject() -> None:
    # Only one group member appears at all (no alternative in sight) --
    # trivially must not be wrapped in a one-child any.
    row = [("mathematics", CellValue(kind="level", level=5, raw="5"))]
    tree, _excluded = build_subject_tree(row, _UJ_PROFILE)
    assert _find_any_nodes(tree) == []
    assert tree["rules"] == [{"kind": "subject", "subject": "mathematics", "min_level": 5}]


def test_mutual_exclusion_grouping_is_opt_in_per_profile() -> None:
    # A profile with no mutually_exclusive_subjects key (an institution
    # that hasn't been analysed for this yet) must fall back to the
    # existing flat-`all` behaviour exactly -- this is declarative
    # per-institution config, never a hardcoded assumption in this module.
    profile_without_groups = {"layout": {**_UJ_PROFILE["layout"]}}
    del profile_without_groups["layout"]["mutually_exclusive_subjects"]
    row = [
        ("mathematics", CellValue(kind="level", level=3, raw="3")),
        ("mathematical_literacy", CellValue(kind="level", level=4, raw="4")),
    ]
    tree, _excluded = build_subject_tree(row, profile_without_groups)
    assert _find_any_nodes(tree) == []


# --- helpers for tree assertions ----------------------------------------

def _flatten_subjects(node: dict) -> set[str]:
    if node.get("kind") in ("all", "any"):
        found: set[str] = set()
        for child in node["rules"]:
            found |= _flatten_subjects(child)
        return found
    if node.get("kind") == "subject":
        return {node.get("subject") or node.get("language")}
    return set()


def _find_any_nodes(node: dict) -> list[dict]:
    found = []
    if node.get("kind") == "any":
        found.append(node)
    if node.get("kind") in ("all", "any"):
        for child in node["rules"]:
            found.extend(_find_any_nodes(child))
    return found
