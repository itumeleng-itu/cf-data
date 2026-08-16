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
    find_aps_candidates,
    find_all_subject_aliases,
    find_subject_alias,
    interpret_cell,
    parse_aps_cell,
    resolve_subject_column,
    scan_page_exclusions,
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


# --- find_aps_candidates ---------------------------------------------------

def test_find_aps_candidates_finds_plausible_two_digit_numbers() -> None:
    assert [v for v, _s, _e in find_aps_candidates("31 with Mathematics")] == [31]


def test_find_aps_candidates_excludes_numbers_outside_14_48() -> None:
    assert find_aps_candidates("5 with Mathematics") == []
    assert find_aps_candidates("52 with Mathematics") == []


def test_find_aps_candidates_excludes_percentage_band_numbers() -> None:
    # A subject-level percentage cell like "3 (40%+)" must never be
    # mistaken for an APS score just because 40 is inside 14-48.
    assert find_aps_candidates("3 (40%+)") == []


def test_find_aps_candidates_finds_multiple_distinct_values() -> None:
    assert [v for v, _s, _e in find_aps_candidates("31 with Mathematics OR 32 with Mathematical Literacy")] == [31, 32]


# --- find_subject_alias / find_all_subject_aliases -------------------------

def test_find_subject_alias_matches_full_subject_name() -> None:
    assert find_subject_alias("with Mathematics OR") == "mathematics"


def test_find_subject_alias_prefers_longest_match() -> None:
    # "Technical Mathematics" contains "Mathematics" as a substring --
    # the longer, more specific alias must win.
    assert find_subject_alias("with Technical Mathematics") == "technical_mathematics"


def test_find_subject_alias_uses_manual_header_aliases() -> None:
    assert find_subject_alias("with Mathematical Literacy") == "mathematical_literacy"


def test_find_subject_alias_returns_none_for_unknown_abbreviation() -> None:
    # "Maths" is not in resolve_subject_column's own vocabulary -- not
    # invented here either.
    assert find_subject_alias("with Maths") is None


def test_find_all_subject_aliases_finds_non_overlapping_matches() -> None:
    result = find_all_subject_aliases("with Mathematics OR with Mathematical Literacy")
    assert result == ["mathematics", "mathematical_literacy"]


def test_find_all_subject_aliases_empty_when_nothing_matches() -> None:
    assert find_all_subject_aliases("with Maths/Tech Maths OR") == []


# --- parse_aps_cell ----------------------------------------------------

def test_parse_aps_cell_none_for_empty_or_none() -> None:
    assert parse_aps_cell(None) is None
    assert parse_aps_cell("") is None


def test_parse_aps_cell_bare_number_no_qualifier() -> None:
    assert parse_aps_cell("26") == [{"min_score": 26}]


def test_parse_aps_cell_single_value_single_alias() -> None:
    assert parse_aps_cell("31 with\nMathematics") == [
        {"min_score": 31, "requires_subject": "mathematics"},
    ]


def test_parse_aps_cell_single_value_multiple_aliases_same_score() -> None:
    # Real UJ B34ACC-shaped cell: one APS value, multiple subject
    # alternatives sharing it.
    result = parse_aps_cell("28 with Mathematics OR 28 with Mathematical Literacy")
    assert result == [
        {"min_score": 28, "requires_subject": "mathematics"},
        {"min_score": 28, "requires_subject": "mathematical_literacy"},
    ]


def test_parse_aps_cell_two_values_sequential_qualifiers() -> None:
    # Real UJ B4L03Q cell.
    result = parse_aps_cell("31 with\nMathematics OR\n32 with\nMathematical\nLiteracy")
    assert result == [
        {"min_score": 31, "requires_subject": "mathematics"},
        {"min_score": 32, "requires_subject": "mathematical_literacy"},
    ]


def test_parse_aps_cell_two_values_no_qualifier_in_span_abstains() -> None:
    # Real UJ B8CD2Q cell -- Table.extract() scrambled the word order so
    # no qualifier sits between the two numbers; must not guess.
    result = parse_aps_cell("26\nwith 25\nwith\nMathematical\nMathematics\nLiteracy OR")
    assert result is None


def test_parse_aps_cell_abbreviation_only_falls_back_to_bare_value() -> None:
    # Real UJ B34HRQ cell -- only abbreviated "Maths"/"Tech Maths" forms
    # present, none of which resolve via the reused alias vocabulary, so
    # this correctly degrades to a single unconditional entry rather than
    # the true 3-branch structure.
    result = parse_aps_cell("28 28\nwith with\nMaths/Tech\nMathematical\nMaths\nLiteracy OR")
    assert result == [{"min_score": 28}]


def test_parse_aps_cell_percentage_band_cell_returns_none() -> None:
    assert parse_aps_cell("3 (40%+)") is None


# --- scan_page_exclusions --------------------------------------------------

def test_scan_page_exclusions_finds_real_uj_science_faculty_note() -> None:
    # Real UJ page 86/89/90 footer, upright text reassembled in reading
    # order by text_repair.page_prose_text().
    page_text = (
        "We are proud to be the first University in Africa to have received "
        "accreditation from the BCS: Chartered Institute for IT, for our BSc "
        "IT Honours programme which one can pursue upon completion of our "
        "BSc Information Technology degree. PLEASE NOTE: Technical "
        "Mathematics and Technical Science are not accepted for Degree "
        "programmes in the Faculty of Science. DEGREE PROGRAMMES"
    )
    assert scan_page_exclusions(page_text, _UJ_PROFILE) == ["technical_mathematics", "technical_sciences"]


def test_scan_page_exclusions_only_resolves_subjects_before_the_phrase() -> None:
    # Real UJ page 75 footer: a second subject (plain Mathematics) is
    # mentioned later in the SAME sentence as something REQUIRED, not
    # excluded -- whole-sentence scanning would wrongly exclude it too.
    page_text = (
        "Technical Mathematics is not accepted, and where Mathematics is "
        "selected as a major, the Faculty of Science's minimum "
        "requirements for Grade 12 Mathematics should be met."
    )
    assert scan_page_exclusions(page_text, _UJ_PROFILE) == ["technical_mathematics"]


def test_scan_page_exclusions_ignores_sentence_with_a_qualification_code() -> None:
    # Real UJ page 54 false positive: several unrelated programmes' own
    # upright "Not applicable" cells (Accounting, Economics) sit on the
    # same page with no punctuation between them, so without this guard
    # they coalesce into one giant "sentence" carrying unrelated codes and
    # subjects far from the actual marker.
    page_text = (
        "COMMERCE EDUCATION Not ACCOUNTING B5BSAQ 28 4 (50%+) applicable "
        "Home language 5 (60%+) OR BUSINESS MANAGEMENT B5BSBQ 28 4 (50%+) "
        "5 (60%+) Additional Language 6 (70%+) Not ECONOMICS B5BSEQ 28 "
        "4 (50%+) applicable CAREER: Educator focusing on high school "
        "teaching."
    )
    assert scan_page_exclusions(page_text, _UJ_PROFILE) == []


def test_scan_page_exclusions_isolated_table_cell_marker_contributes_nothing() -> None:
    # Each rotated table cell gets its own line (see page_prose_text) --
    # a bare one-word marker with no subject alias on its own line must
    # not pick up a subject from an unrelated neighbouring line.
    page_text = "Mathematics\nNot applicable\nPhysical Science"
    assert scan_page_exclusions(page_text, _UJ_PROFILE) == []


def test_scan_page_exclusions_returns_empty_when_phrase_absent() -> None:
    page_text = "Bachelor of Human Resource Management. English 5 (60%+)."
    assert scan_page_exclusions(page_text, _UJ_PROFILE) == []


def test_scan_page_exclusions_returns_empty_when_profile_has_no_phrases() -> None:
    profile = {"layout": {"code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}"}}
    page_text = "Technical Mathematics is not accepted."
    assert scan_page_exclusions(page_text, profile) == []
