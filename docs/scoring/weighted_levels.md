# `weighted_levels` — UNVERIFIED

**Status: algorithm exists in `api/src/app/scoring.py`; no institution is
registered against it; no worked example exists to test it against.**

## Why the algorithm exists without a config

`docs/scoring/uct.md` and `docs/scoring/wits.md` are read-only
investigations (their own headers say so explicitly: "No scoring function
written, `api/src/app/scoring.py` not touched, `institutions` table not
touched"). They establish the SHAPE both institutions' scoring takes —
per-subject multipliers applied within an otherwise-standard APS, e.g.
UCT's own text (`uct.md`, section 4): *"In order to calculate the FPS for
the Faculty of Science, double the scores achieved for Mathematics and
Physical Sciences."*

`weighted_levels` implements that general shape — `{subject: multiplier}`
weights, a default weight for everything else, top-N of the weighted
values — so that whoever writes UCT's or Wits's actual `scoring_config`
later has an algorithm ready to configure, rather than needing to write
one under deadline. It is deliberately generic and untied to either
institution's specific faculties.

## What is NOT done here, and why

Neither `uct.md` nor `wits.md` contains a worked example with real
numbers all the way to a final score — both are vocabulary/structure
investigations, not verification passes. Writing UCT's or Wits's real
`scoring_config` now would mean guessing at a detail neither document
pins down: whether the "double Mathematics and Physical Sciences" weight
applies BEFORE or AFTER the standard best-six subjects are selected
(`weighted_levels` applies it before — weight, then select top N — which
is a reasonable general design but is not confirmed as UCT's actual order
of operations). Registering a config on that guess would be exactly the
failure mode `scoring.py`'s own module docstring warns about: a wrong
scorer breaks every programme at that institution, consistently and
invisibly, with nothing about any individual record looking wrong.

Both institutions also have a harder, separate problem `weighted_levels`
does not attempt to solve at all: their Faculty of Health Sciences folds
National Benchmark Test results into a Composite Index / Weighted Points
Score, which needs an input (`api/v1/qualify` deliberately never
collects NBT scores — see the `scoreable` field and
`requires_additional_assessment` in `/v1/qualify`'s response). Those
programmes are marked `scoreable: false` regardless of which algorithm
their non-Health-Sciences siblings eventually use.

## To verify and register this algorithm for a real institution

1. Find a worked example in that institution's own prospectus — a
   named example, with subject percentages and a final published score,
   the same standard this file's siblings (`aps_best6_excl_lo`,
   `percentage_sum_div_10`) were held to.
2. Confirm the order of operations against that example (weight-then-
   select vs. select-then-weight) — if `weighted_levels`'s current
   before-selection order doesn't reproduce the published answer, that is
   itself the finding to record, not something to route around by
   tweaking the weights.
3. Add the case to `tests/test_scoring_worked_examples.py`.
4. Register the institution's `scoring_strategy: "weighted_levels"` and
   its real `scoring_config` in `seeds/institutions.json` (or a
   programme-level `scoring_strategy_override`/`scoring_override` for a
   single faculty — see `docs/BUNDLE_FORMAT.md`).
5. Delete this file, or narrow it to whichever institution still lacks a
   worked example.
