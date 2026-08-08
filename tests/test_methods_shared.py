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
    tree, excluded = build_subject_tree(row)
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
    tree, excluded = build_subject_tree(row)
    assert excluded == set()
    any_nodes = _find_any_nodes(tree)
    paired = {frozenset(_flatten_subjects(node)) for node in any_nodes}
    assert frozenset({"physical_sciences", "technical_sciences"}) in paired


def test_build_subject_tree_plain_levels_become_all_node() -> None:
    row = [
        ("english", CellValue(kind="level", level=5, raw="5")),
        ("mathematics", CellValue(kind="level", level=6, raw="6")),
    ]
    tree, excluded = build_subject_tree(row)
    assert excluded == set()
    assert tree["kind"] == "all"
    levels = {r["subject"]: r["min_level"] for r in tree["rules"] if r["kind"] == "subject" and "subject" in r}
    assert levels["mathematics"] == 6


def test_build_subject_tree_language_column_becomes_language_node() -> None:
    row = [("english", CellValue(kind="level", level=5, raw="5"))]
    tree, _excluded = build_subject_tree(row)
    languages = [r for r in tree["rules"] if r.get("kind") == "subject" and "language" in r]
    assert languages == [{"kind": "subject", "language": "english", "min_level": 5}]


def test_build_subject_tree_empty_cells_are_skipped() -> None:
    row = [
        ("english", CellValue(kind="level", level=5, raw="5")),
        ("technical_sciences", CellValue(kind="empty", raw="")),
    ]
    tree, excluded = build_subject_tree(row)
    assert excluded == set()
    assert "technical_sciences" not in _flatten_subjects(tree)


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
