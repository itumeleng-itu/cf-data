import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "api" / "src"))

from seed_loader import load  # noqa: E402

from app.evaluator import Failure, evaluate  # noqa: E402
from app.qualify import select_score_threshold  # noqa: E402
from app.scoring import SCORERS  # noqa: E402

_DATA = load()
_PROGRAMMES = {p["qualification_code"]: p for p in _DATA["programmes"]}
_INSTITUTIONS = {i["id"]: i for i in _DATA["institutions"]}

CANONICAL_MARKS = {
    "english_hl": 87,
    "afrikaans_fal": 85,
    "mathematics": 88,
    "life_orientation": 88,
    "geography": 92,
    "life_sciences": 87,
    "physical_sciences": 73,
}


def _excluded_for(code: str) -> set[str]:
    nsc = _PROGRAMMES[code]["requirements"]["nsc"]
    return set(nsc.get("excluded_subjects") or [])


def _qualifies(code: str, marks: dict[str, int]) -> tuple[bool, list[Failure], int, int | None]:
    programme = _PROGRAMMES[code]
    nsc = programme["requirements"]["nsc"]
    excluded = _excluded_for(code)
    institution = _INSTITUTIONS[programme["institution_id"]]
    achieved = SCORERS[institution["scoring_strategy"]](marks)
    required = select_score_threshold(nsc["score"], marks)
    failures = evaluate(nsc["subjects"], marks, excluded)
    passes = required is not None and achieved >= required and not failures
    return passes, failures, achieved, required


# 1. aps_best6_excl_lo returns 41 -- LO excluded despite tying-highest,
#    exactly six subjects counted.
def test_aps_best6_excl_lo_returns_41() -> None:
    assert SCORERS["aps_best6_excl_lo"](CANONICAL_MARKS) == 41


# 2. B2M52Q (Actuarial Science, APS 40, Maths 7) qualifies, margin 1.
def test_b2m52q_qualifies_with_margin_one() -> None:
    passes, failures, achieved, required = _qualifies("B2M52Q", CANONICAL_MARKS)
    assert passes
    assert failures == []
    assert achieved - required == 1


# 3. B2I02Q qualifies (APS 30, Eng 5, Maths 6).
def test_b2i02q_qualifies() -> None:
    passes, failures, _achieved, _required = _qualifies("B2I02Q", CANONICAL_MARKS)
    assert passes
    assert failures == []


# 4. B4L03Q (LLB) qualifies: english_hl satisfies English, afrikaans_fal
#    satisfies any_additional_language. The two rules must consume
#    DIFFERENT families.
def test_b4l03q_qualifies_consuming_different_families() -> None:
    excluded = _excluded_for("B4L03Q")
    nsc = _PROGRAMMES["B4L03Q"]["requirements"]["nsc"]
    assert evaluate(nsc["subjects"], CANONICAL_MARKS, excluded) == []

    english_only_marks = {k: v for k, v in CANONICAL_MARKS.items() if k != "afrikaans_fal"}
    failures = evaluate(nsc["subjects"], english_only_marks, excluded)
    assert failures  # english alone must not also satisfy any_additional_language
    assert any(f.kind == "any_additional_language" for f in failures)


# 5. B8CD2Q qualifies via the 25-with-Maths threshold, not 26.
def test_b8cd2q_qualifies_via_25_with_maths() -> None:
    nsc = _PROGRAMMES["B8CD2Q"]["requirements"]["nsc"]
    assert select_score_threshold(nsc["score"], CANONICAL_MARKS) == 25
    passes, failures, _achieved, _required = _qualifies("B8CD2Q", CANONICAL_MARKS)
    assert passes
    assert failures == []


# 6. B5BFPQ qualifies; english_hl 87 clears the HL threshold of 5.
def test_b5bfpq_qualifies() -> None:
    passes, failures, _achieved, _required = _qualifies("B5BFPQ", CANONICAL_MARKS)
    assert passes
    assert failures == []


# 7. Maths Lit instead of Maths: measured against B8CD2Q's 26, not 25.
def test_mathematical_literacy_hits_26_not_25_on_b8cd2q() -> None:
    marks = {k: v for k, v in CANONICAL_MARKS.items() if k != "mathematics"}
    marks["mathematical_literacy"] = 90
    nsc = _PROGRAMMES["B8CD2Q"]["requirements"]["nsc"]
    assert select_score_threshold(nsc["score"], marks) == 26


# 8. english_fal only: 72 (level 6) passes, 65 (level 5) fails, on B5BFPQ.
def test_english_fal_only_on_b5bfpq_72_passes_65_fails() -> None:
    nsc = _PROGRAMMES["B5BFPQ"]["requirements"]["nsc"]
    excluded = _excluded_for("B5BFPQ")
    assert evaluate(nsc["subjects"], {"english_fal": 72, "mathematics": 88}, excluded) == []
    failures = evaluate(nsc["subjects"], {"english_fal": 65, "mathematics": 88}, excluded)
    assert failures
    assert any(f.required == 6 for f in failures)


# 9. Excluded-subject non-disqualification: mathematics 88 AND
#    technical_mathematics 95 qualifies for B2I02Q on the Mathematics mark,
#    and APS is 41 -- Technical Mathematics counts toward the score just
#    like any other subject (exclusion governs subject rules only, never
#    scoring; APS is institution-wide, not per-programme). Assert the
#    number explicitly, not just the pass.
#
#    Six non-LO subjects total here (technical_mathematics replaces
#    life_sciences from the canonical fixture, rather than being added as a
#    7th) so the arithmetic lands on 41 exactly, as it would for any
#    ordinary 6-subject NSC certificate -- simply adding a 7th level-7
#    subject on top of the full canonical fixture would give 42, since it
#    would displace physical_sciences (level 6) out of the best-6.
def test_excluded_subject_does_not_disqualify_and_still_counts_toward_score() -> None:
    marks = {
        "english_hl": 87,
        "afrikaans_fal": 85,
        "mathematics": 88,
        "technical_mathematics": 95,
        "life_orientation": 88,
        "geography": 92,
        "physical_sciences": 73,
    }

    passes, failures, achieved, _required = _qualifies("B2I02Q", marks)
    assert passes
    assert failures == []
    assert achieved == 41


# 10. Only technical_mathematics, no mathematics: B2I02Q fails with a
#     missing-subject failure naming mathematics.
def test_only_technical_mathematics_fails_b2i02q_naming_mathematics() -> None:
    marks = {k: v for k, v in CANONICAL_MARKS.items() if k != "mathematics"}
    marks["technical_mathematics"] = 90
    nsc = _PROGRAMMES["B2I02Q"]["requirements"]["nsc"]
    excluded = _excluded_for("B2I02Q")
    failures = evaluate(nsc["subjects"], marks, excluded)
    assert len(failures) == 1
    assert failures[0].kind == "subject"
    assert failures[0].subject == "mathematics"
    assert failures[0].actual is None


# 11. No isiZulu fails B5LAZQ with exactly one failure, naming isizulu.
#     B5LAZQ is a two-language programme (English then isiZulu, both
#     explicit language rules) -- the English rule passes on the canonical
#     fixture, so the failure count stays at exactly one.
def test_no_isizulu_fails_b5lazq_with_exactly_one_failure() -> None:
    nsc = _PROGRAMMES["B5LAZQ"]["requirements"]["nsc"]
    excluded = _excluded_for("B5LAZQ")

    english_rule = nsc["subjects"]["rules"][0]
    assert evaluate(english_rule, CANONICAL_MARKS, excluded) == []

    failures = evaluate(nsc["subjects"], CANONICAL_MARKS, excluded)
    assert len(failures) == 1
    assert failures[0].kind == "subject"
    assert failures[0].subject == "isizulu"


# Neither Mathematics nor Mathematical Literacy: B8CD2Q's score has two
# conditional entries and no unconditional fallback -- a learner with
# neither subject must fail outright, not silently pass via some fallback
# threshold.
def test_neither_maths_nor_maths_lit_fails_score_outright() -> None:
    marks = {k: v for k, v in CANONICAL_MARKS.items() if k != "mathematics"}
    nsc = _PROGRAMMES["B8CD2Q"]["requirements"]["nsc"]
    assert select_score_threshold(nsc["score"], marks) is None

    passes, _failures, _achieved, required = _qualifies("B8CD2Q", marks)
    assert not passes
    assert required is None


def _tree_references_subject(rule: dict, subject_key: str) -> bool:
    """Recursively check whether a subject-tree node references a given
    subject key anywhere (all/any/subject nodes only -- language and
    any_additional_language nodes never reference a plain subject key)."""
    if not isinstance(rule, dict):
        return False
    kind = rule.get("kind")
    if kind in ("all", "any"):
        return any(_tree_references_subject(r, subject_key) for r in rule.get("rules") or [])
    if kind == "subject":
        return rule.get("subject") == subject_key
    return False


# Generalized rather than a hardcoded per-programme exclusion list -- that
# list needed updating twice in two tranches (B2M43Q, then all six FEBE
# programmes) and Health is coming next with the same subject. Scoping by
# "does this programme's tree even reference physical_sciences" scales
# without remembering to touch this test every time.
def test_physical_sciences_at_level_6_constrains_nothing_where_not_required() -> None:
    without_ps = {k: v for k, v in CANONICAL_MARKS.items() if k != "physical_sciences"}
    for code, programme in _PROGRAMMES.items():
        nsc = programme["requirements"]["nsc"]
        if _tree_references_subject(nsc["subjects"], "physical_sciences"):
            continue
        excluded = set(nsc.get("excluded_subjects") or [])
        with_ps = evaluate(nsc["subjects"], CANONICAL_MARKS, excluded)
        no_ps = evaluate(nsc["subjects"], without_ps, excluded)
        assert with_ps == no_ps, code


def test_physical_sciences_actually_required_where_tree_references_it() -> None:
    without_ps = {k: v for k, v in CANONICAL_MARKS.items() if k != "physical_sciences"}
    checked = []
    for code, programme in _PROGRAMMES.items():
        nsc = programme["requirements"]["nsc"]
        if not _tree_references_subject(nsc["subjects"], "physical_sciences"):
            continue
        excluded = set(nsc.get("excluded_subjects") or [])
        with_ps = evaluate(nsc["subjects"], CANONICAL_MARKS, excluded)
        no_ps = evaluate(nsc["subjects"], without_ps, excluded)
        assert with_ps != no_ps, f"{code}: removing physical_sciences should have changed the result"
        checked.append(code)
    # Sanity: this test isn't vacuously true because no programme matched.
    assert "B2M43Q" in checked
    assert {"B6CS0Q", "B6ES0Q", "B6MS0Q", "B6CV3Q", "B6EL1Q", "B6MC2Q"} <= set(checked)


# Technical-stream learner (FEBE tranche): Technical Maths and Technical
# Science, no pure Mathematics, no Physical Sciences. Exercises both
# encodings of the Technical Maths/Science pattern in one profile --
# accepted-as-alternative (B6CV3Q, B6MC2Q via `any`) and excluded-entirely
# (B6CS0Q, B6ES0Q, B6EL1Q, B2I02Q, B34CAQ via excluded_subjects) -- so a
# future mix-up in either direction shows up here.
_TECHNICAL_STREAM_MARKS = {
    "english_hl": 75,
    "technical_mathematics": 78,
    "technical_sciences": 75,
    "life_sciences": 70,
    "geography": 70,
    "life_orientation": 70,
}


def test_technical_stream_learner_qualifies_where_technical_maths_is_an_alternative() -> None:
    for code in ("B6CV3Q", "B6MC2Q"):
        passes, failures, _achieved, _required = _qualifies(code, _TECHNICAL_STREAM_MARKS)
        assert passes, f"{code}: {failures}"
        assert failures == []


def test_technical_stream_learner_fails_where_technical_maths_is_excluded_or_absent() -> None:
    # Health's five programmes join this list too: none of them accept
    # Technical Mathematics or Technical Sciences (B9S15Q doesn't even
    # reference science, but Maths Lit is the only accepted alternative to
    # plain Mathematics there, and this learner holds neither).
    codes = (
        "B6CS0Q", "B6ES0Q", "B6EL1Q", "B2I02Q", "B34CAQ",
        "B9N02Q", "B9O02Q", "B9M01Q", "B9E01Q", "B9S15Q",
    )
    for code in codes:
        passes, failures, _achieved, _required = _qualifies(code, _TECHNICAL_STREAM_MARKS)
        assert not passes, f"{code} unexpectedly passed"
        assert failures
