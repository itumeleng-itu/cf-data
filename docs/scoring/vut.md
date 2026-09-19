# VUT 2027 — source, conversion, and known gaps

**Status: `confidence: "extracted"` for all 49 VUT programmes, not
`"verified"`.**

## Source

`universities/2027/vut_2027_programmes.json` — same shared reference
schema as TUT's (see `docs/scoring/tut.md`), supplied directly. Converted
by the now-generalised `scripts/convert_reference_dataset.py vut`.

## Two real differences from TUT this conversion had to handle correctly

**An 8-point achievement scale, not the standard 1-7 NSC one.** VUT's own
`scoring.level_bands` splits the standard top band (80-100% = level 7)
into two: 80-89% = 7, 90-100% = a full 8. `scoring.py`'s
`aps_best6_excl_lo` gained a `level_bands` config for exactly this — see
that function's docstring. Checked before assuming this only affects
scoring: **no VUT programme's own subject requirement ever asks for level
7 or 8** (the highest `min_level` anywhere in the data is 6), so this
never changes a subject pass/fail, only the summed APS total. Cross-
checked against VUT's own reference evaluator with a 90%+-averaging
learner: reference APS 46, coursefind-data APS 46 — an exact match that
would have been APS 40 (6 points instead of 8, ×6 subjects doesn't
literally apply since not every subject was 90%+, but the undercounting
direction is real) had the level_bands config not been added, since the
standard `percentage_to_level` caps at 7 regardless of how far past 80% a
mark is.

**`min_percent` leaves, not just `min_level` ones.**
`vut-dip-analytical-chemistry` and `vut-dip-biotechnology` require
Engineering Mathematics N4 / Engineering Science N4 at "60%" directly,
not a pre-converted level. Converted by looking up 60% against VUT's own
`level_bands` (→ level 5, an exact band-boundary match, not an
approximation) rather than inventing a new evaluator leaf kind — a
`min_level` in the output tree either way.

## New subjects

`Engineering Mathematics N4`, `Engineering Science N4` — National
Certificate (Vocational) subjects, not NSC ones; VUT's brochure accepts
them as alternatives regardless. `Catering`, `Hotel` — appear as named
alternatives alongside Hospitality Studies/Tourism/Accounting/Business
Studies/Consumer Studies on `vut-dip-food-service-management`'s single
elective leaf; **not independently confirmed against the source brochure
text** (no official South African NSC subject is named exactly "Hotel" or
"Catering" alone — this could be informal shorthand in the source for
something with a more specific real name). Flagged, not silently trusted,
same as the rest of this document's `extracted`-not-`verified` status.

## Cross-checked against the reference evaluator, not just structurally

Five learner profiles (all-rounder, a 90%+ achiever, a technical stream
candidate, an Engineering-N4 candidate, and a Maths Lit candidate) run
through both `universities/2027/qualify.py`'s `Evaluator` directly
against the source JSON, and coursefind-data's real
`evaluator.py`/`scoring.py`/`qualify.py` against the converted data:

- **APS matched exactly on every profile**, including the 90%+ achiever
  (46 = 46) and the Engineering-N4 candidate (24 = 24) — confirming both
  the `level_bands` and `min_percent`-via-band-lookup conversions are
  behaviourally correct, not just structurally plausible.
- **Every programme the reference evaluator qualifies, coursefind-data
  also qualifies** — zero missing qualifications on any profile.
- The only extra qualifications on coursefind-data's side are exactly the
  ones the dropped `@`-token leaves (below) would have gated — the same
  lenient-not-strict pattern as TUT.

## Known, deliberate gaps (same shape as TUT's — see that file for the full reasoning)

- **NSC Bachelor's/Diploma endorsement** (`global_requirements.endorsement_by_qualification_type`)
  — dropped everywhere; no "N distinct free-choice subjects at level X"
  rule kind in `evaluator.py` yet.
- **`@ANY_SUBJECT` / `@ADDITIONAL_LANGUAGE` leaves used as a route's own
  elective** — 20 leaves across 10 programmes
  (`vut-dip-human-resources-management`, `vut-dip-logistics-and-supply-chain-management`,
  `vut-dip-marketing`, `vut-dip-retail-business-management`,
  `vut-dip-sport-management`, `vut-dip-public-relations-management`,
  `vut-dip-labour-law`, `vut-dip-legal-assistance`,
  `vut-dip-policing`, `vut-bachelor-of-communication-studies`)
  dropped for the same reason. (An earlier revision of the source had
  `vut-dip-safety-management` in this list instead of
  `vut-dip-policing` — the source was updated between the first and
  second conversion pass, re-checked below, not just re-run blindly.)
- **No `nsc_year_min` leaves in this dataset at all** — unlike TUT, VUT's
  source never uses one, so nothing was dropped for this reason here.
- **No page citations** — `source_page` is `null` throughout;
  `source_doc` is `"vut_2027_undergraduate_minimum_admission_requirements"`.

## Resolved: the source was revised to add the missing durations

The first conversion pass found 24 VUT programmes with no
`duration_years` at all (the source brochure didn't state one, each
carrying an honest *"Duration not stated in brochure"* note — nothing
was guessed to paper over it). The source file was since updated with a
new top-level note: *"Durations sourced from VUT's 2026 faculty
prospectuses where the 2027 brochure omits them."* — every one of those
24 programmes now has a real `duration_years`, and
`scripts/validate_data.py` passes on all 174 programmes (TUT + VUT) with
zero errors as of this revision.

This was **re-verified from scratch, not assumed to be duration-only**:
re-running the converter's `--dry-run` report against the revised source
showed the dropped-`@`-token programme list had also changed
(`vut-dip-safety-management` dropped out, `vut-dip-policing` appeared in
its place — a real requirements change, not a diffing artefact), so the
full cross-check against the reference evaluator was re-run in full
(six learner profiles this time, up from five, adding one exercising the
Home Language/First Additional Language mechanism specifically) rather
than trusting that only durations had moved. All six: APS matched
exactly, zero missing qualifications.

## What's NOT a gap, worth stating explicitly

`global_requirements.all_programmes` is **empty** for VUT (unlike TUT's
one-item English floor) — every VUT route already states its own English
requirement explicitly (checked: zero routes omit one), so there was
nothing to backfill. `scripts/convert_reference_dataset.py` derives this
from the source directly rather than assuming an English floor always
exists, so this isn't a special case in the script either.
