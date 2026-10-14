# TUT 2027 — source, conversion, and known gaps

**Status: `confidence: "extracted"` for all 124 TUT programmes, not
`"verified"`.** Registered against `aps_best6_excl_lo` with a real,
cross-checked `zero_below_level` config — the scoring formula is not the
gap here; the gap is that no human has read the converted requirements
against the prospectus.

## Source — re-encoded 2026-10-14 from TUT's own prospectus

`TUT First Year Course Information 2027`, the university's own PDF,
extracted by `scripts/extract_tut_programmes.py` and
`scripts/tut_requirements.py`, verified by
`scripts/verify_tut_programmes.py`, converted by
`scripts/convert_tut_programmes.py`. Running the extractor twice gives
the same file.

**This replaces the previous source, which no longer exists.** TUT's 125
programmes were originally converted from
`universities/2027/tut_2027_programmes.json`, a dataset supplied
directly and never committed to this repo. It is gone, and with it the
reference evaluator the conversion was cross-checked against. Only the
scoring config in `seeds/institutions.json` survived. The record of that
work is kept below, because the cross-check it describes is still the
strongest evidence the scoring config is right — but the requirements
now in `seeds/tut/tut_2027.json` come from the prospectus, not from it.

124, not 125: `Dip (Policing)` prints two admission ROUTES as two rows —
an experiential one for serving law-enforcement officers and an ordinary
NSC one — and is one programme.

## What the verification checks, and what it cannot

`verify_tut_programmes.py` reads the PDF with `pdftotext -layout`, a
different engine and code path from the `pdfplumber` table walk the
extractor uses, so it cannot confirm the parser's own mistakes back to
it. On the current extraction:

    1 FIDELITY   124/124 programme names printed on their page
    2 SUBJECTS   525/525 named subjects are real NSC subjects
    3 LEVELS     380/380 branches carry a level in 1-7
    4 APS        149/149 thresholds printed on their page
    5 COVERAGE   124 rows across 14 pages
    6 INHERITED  25 levels inherited, each listed

It does NOT check that a requirement means what TUT intends — only that
every name, level and threshold served is printed where the record says
it is.

## The one inference in the data: inherited levels

TUT's level column is set "print on change": a number appears beside an
alternative only where its requirement DIVERGES from the option above
it. Page 14 shows both halves on adjacent rows — `Dip (Adventure
Tourism)` prints 4 beside Mathematical Literacy because it is held
higher than Mathematics at 3, while `Dip (Administrative Information
Management)` prints nothing beside it because it is held to the same 3.

So an alternative with no printed level inherits the last one printed in
its own block, and **25 levels in the dataset were set this way**. They
are listed in full by the verifier. Inheritance is scoped to the block:
a requirement that opens with no level has nothing legitimate to
inherit and is reported, never defaulted.

The split corroborates itself — the BEd degrees inherit 4 and the
diplomas inherit 3, matching the prospectus's own general rule
("Bachelor's degrees: at least four subjects at performance level 4").

## What this document does NOT contain

No course lists. Despite its title, "First Year Course Information"
carries admission requirements only — compulsory subjects, levels, APS,
duration, campuses, closing dates, careers. There is no curriculum
outline anywhere in its 20 pages, so TUT programmes match learners but
have nothing to show behind "what you would study".

## Not scored

`Dip (Fire Technology)` is open only to serving Fire and Rescue
personnel and asks for a diploma-endorsed NSC, three years' service and
HAZMAT and Fire Fighter certificates. It names no subject and no APS, so
it is `scoreable: false` and reaches a learner in the
`requires_additional_assessment` bucket rather than being scored on
requirements TUT does not state.

## Two validator checks were widened for this data

Both narrowly, both in `scripts/validate_data.py`:

1. A programme that is `scoreable: false` AND states no subjects at all
   is exempt from "no English requirement". Dip (Fire Technology) names
   no subject; inventing an English level would state a requirement TUT
   does not.
2. A programme requiring TWO unnamed languages and naming none is also
   exempt. `BEd (Foundation Phase Teaching)` asks for "Home language
   offered in the programme" at 5 and "First additional language" at 4
   — a learner teaching in Sepedi and isiZulu satisfies it, and English
   appears nowhere on the row.

Both conditions are required in each case, so a record that lists some
subjects but not English is still an error — which is the transcription
slip that check exists to catch.

---

# Previous conversion (source no longer available)

**Status: `confidence: "extracted"` for all 125 TUT programmes, not
`"verified"`.** Registered against `aps_best6_excl_lo` with a real,
cross-checked `zero_below_level` config — this is not an UNVERIFIED
scoring algorithm the way `weighted_levels`/`custom_points_with_bonus`
are; the gap here is in *which requirements got converted*, not in the
scoring formula itself.

## Source

`universities/2027/tut_2027_programmes.json` — supplied directly, not
transcribed through this repo's normal bundle pipeline. It's a complete,
independently-structured dataset (125 programmes, its own schema, its own
reference evaluator at `universities/2027/qualify.py`) with a
self-documenting `subject_matching` and `requirement_tree_spec` block, not
a flat per-cell bundle a human filled in against
`seeds/bundle.schema.json`.

Converted by `scripts/convert_tut_reference.py`, which transliterates the
source's `any`/`all`/`subject`/`aps_min` tree into this repo's
`requirements.nsc.{score,subjects,excluded_subjects}` shape. Every run
prints a full report of what it dropped and why; that report is
reproduced below rather than only living in a terminal.

## Cross-checked, not just structurally validated

`scripts/validate_data.py` passes on the merged dataset (154 programmes:
29 UJ + 125 TUT) — but structural validity alone doesn't prove the
conversion is *behaviourally* correct, so it was checked against the
source's own reference evaluator directly: the same test learner (APS 28:
English HL 65%, Mathematics 60%, Physical Sciences 55%, Life Sciences
60%, Geography 55%, Accounting 60%, Life Orientation 70%) was run through
both `universities/2027/qualify.py` (107 qualifying programmes) and
`coursefind-data`'s real `evaluator.py`/`scoring.py`/`qualify.py` against
the converted data (113 qualifying programmes).

- **APS matched exactly (28 = 28)** — confirms `scoring.py`'s new
  `zero_below_level` config (added alongside this conversion) reproduces
  TUT's own `aps()` function faithfully, not just structurally.
- **Every programme the reference evaluator qualifies, coursefind-data
  also qualifies** — zero missing qualifications, zero under-counting.
- **The only 6 programmes coursefind-data qualifies that the reference
  doesn't** are exactly the ones whose gating condition is one of the
  dropped `@`-token leaves below (`tut-bed-foundation-phase-teaching`,
  `tut-bed-intermediate-phase-teaching`, and four ACE/legal-support
  diplomas needing `@ADDITIONAL_LANGUAGE`) — this test learner doesn't
  offer a second language, so the reference correctly excludes them and
  coursefind-data, having dropped that leaf, doesn't check for it.

No other discrepancy was found. This is one test learner, not exhaustive
coverage — but it's a real behavioural cross-check against the source's
own evaluator, not just "the JSON parses."

## Known, deliberate gaps

### 1. The NSC Bachelor's/Diploma "endorsement" requirement — dropped everywhere

TUT's `global_requirements.endorsement_by_qualification_type` requires 4
(bachelor's) or 4 (diploma) *distinct, free-choice* subjects at a minimum
level, on top of whatever else a route names — plus three programmes
(`tut-bengtech-electrical-engineering`, `tut-benvironmental-health`,
`tut-bpharm-bachelor-of-pharmacy`) embed their own stricter version
(`count: 2` or `count: 3`) directly in a route.

`evaluator.py` has no rule kind for "N distinct subjects from anywhere,
at level >= X, not already used elsewhere" — `kind: "subject"` names one
specific subject or language family; there's nothing that means "any N of
the learner's remaining subjects." Building one properly needs the same
kind of bipartite-matching logic the reference `qualify.py`'s own
`assign()` function implements (see that file). **Not built here** — this
conversion's stated goal was proving coursefind-data and courseFinder
connect correctly with a second real institution, not full TUT parity on
day one.

**Practical impact:** every condition this conversion DOES check (English,
the named elective, the APS threshold) is checked exactly. What's missing
is a background check that a learner's *other* subjects clear a modest
bar (level 4, in most cases) — something the overwhelming majority of
real NSC candidates with 6+ subjects satisfy incidentally. This makes the
converted data slightly more lenient than the true rule, never stricter.

### 2. `@`-token leaves used as a route's own elective — dropped

Beyond the endorsement, `@HOME_LANGUAGE` / `@FIRST_ADDITIONAL_LANGUAGE` /
`@OTHER_HOME_LANGUAGE` / `@ADDITIONAL_LANGUAGE` / `@ANY_SUBJECT` appear as
a route's *actual* gating leaf (not the endorsement) on:

`tut-bengtech-electrical-engineering`, `tut-bed-foundation-phase-teaching`
(×2 routes), `tut-bed-intermediate-phase-teaching`,
`tut-dip-adult-and-community-education-and-training-specialisation-in-civil-technology`,
`tut-dip-adult-and-community-education-and-training-specialisation-in-consumer-sciences`,
`tut-dip-adult-and-community-education-and-training-specialisation-in-electrical-and-mechanical`,
`tut-dip-legal-support`, `tut-benvironmental-health`,
`tut-bpharm-bachelor-of-pharmacy`, `tut-hcert-dental-assisting` — 18 leaves
across 10 programmes. Same underlying cause as #1 (no "any subject/any
language-category" rule kind); dropped for the same reason, with the same
lenient-not-strict direction of error.

### 3. `nsc_year_min` — dropped, always true in practice

`tut-dip-policing` and `tut-dip-traffic-safety-and-municipal-police-management`
require an NSC from 2008 or later. `/v1/qualify` collects no NSC-year
input at all, and no real 2027 applicant would have a pre-2008 NSC in the
first place (the NSC didn't exist before 2008) — dropping this leaf
changes nothing for any real learner.

### 4. Second Additional Language — not representable

TUT's bare language-name leaves (e.g. `"Sepedi"`, meaning "any level —
Home, First Additional, or Second Additional") are converted to a
`language` rule checked against Home and First Additional only. `Subject`
(`api/src/app/subjects.py`) has no Second Additional Language slug for
any language at all — checked: no leaf in this dataset actually needs
one, so this is a latent gap, not a live one, for TUT specifically.

### 5. No page citations

Unlike UJ's data (`source_page` on every record, resolving to a specific
page of the prospectus PDF), this source carries no per-programme page
reference — `source_page` is `null` throughout. `source_doc` is set to
`"tut_2027_first_year_brochure"` so the document itself is at least
named. This — combined with #1/#2 above — is why every converted record
is stamped `"extracted"`, not `"verified"`: nobody has cross-checked an
individual record against a cited page the way UJ's worked examples were.

## Scoring

`scoring.py`'s `_aps_best6_excl_lo` gained an optional `zero_below_level`
config (additive — UJ's existing config is untouched and behaves exactly
as before). TUT's own brochure states the rule directly (quoted verbatim
in the source's `scoring.aps.note`): *"LO and any subject at level 1 are
not counted. Brochure requires a minimum of six subjects; APS uses the
best six non-LO subjects."* — i.e. a level-1 subject still occupies one of
the six slots (it isn't simply skipped in favour of a 7th, stronger
subject) but contributes 0 instead of 1. `zero_below_level: 2` encodes
this exactly, and the cross-check above confirms it reproduces the
source's own `aps()` function's output.

## To move any of this from `extracted` to `verified`

1. Build the "N distinct free-choice subjects at level X" rule kind in
   `evaluator.py`, generalising `dnf`/`assign`-style matching the way the
   reference `qualify.py` already does it, and wire it into the
   endorsement requirement and the 10 affected programmes above.
2. Get page references for at least a sample of records from TUT's actual
   2027 brochure, and add a worked example to
   `tests/test_scoring_worked_examples.py`.
3. Re-run `scripts/convert_tut_reference.py` (it's idempotent — reads the
   same source, replaces TUT's institution/programme entries wholesale)
   and re-validate.
