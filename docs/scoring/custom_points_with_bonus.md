# `custom_points_with_bonus` — UNVERIFIED

**Status: algorithm exists in `api/src/app/scoring.py`; no institution is
registered against it; no confirmed worked example exists for either
candidate institution.**

## Why this algorithm exists

Two independent institutions — University of the Witwatersrand and Sol
Plaatje University — were found, via a research pass (not a direct
prospectus read the way `uct.md`'s original investigation was), to share
the same admission-scoring SHAPE despite different actual numbers:

- Their own points table, not the standard NSC 1-7 achievement-level
  scale.
- Life Orientation scored on its own separate, lower table — but
  **included** in the total, not excluded the way `aps_best6_excl_lo`
  excludes it everywhere else in this dataset.
- Bonus points for Mathematics and whichever subject the learner offers
  as Home Language, on top of their base points.

One algorithm, configured differently per institution, covers both --
see `docs/scoring/wits.md` (section 5) and `spu.md` for exactly what each
institution's own config would look like, and — more importantly — what
in each is actually confirmed versus still disputed between sources.

## Why neither is registered yet

Read `wits.md` section 5 and `spu.md` in full before registering either.
Short version: both rest on research-pass findings (WebSearch/WebFetch),
not a verified prospectus read cross-checked the way UJ's and CPUT's
worked examples were. Specific open items:

- **Wits**: whether the "Wits APS" 0-8 scale found on their live
  entry-requirements page is the actual figure that gates the `APS N+`
  thresholds printed in their prospectus, or a separate self-assessment
  number — not confirmed either way. No official worked example found.
- **SPU**: the exact Mathematics/Home-Language bonus thresholds are
  disputed between sources (40/60 split vs. 50/70 split). The base
  points table itself was read by one subagent from SPU's own prospectus
  PDF and could not be independently reproduced — two direct attempts to
  read the same document both failed.

Registering a `scoring_config` on either right now would be exactly the
failure mode `scoring.py`'s own module docstring warns against: a wrong
scorer breaks every programme at that institution, consistently and
invisibly, with nothing about any individual record looking wrong.

## To verify and register this algorithm for a real institution

1. Get a human-readable copy of the institution's own current
   prospectus or admissions documentation — for SPU specifically, the
   PDF's text layer would not extract with the tools available when this
   was investigated; a different tool, or contacting the institution
   directly, may be needed.
2. Find (or produce, by hand-checking a specific case) a worked numeric
   example with a real answer to check the config against — the same
   standard `aps_best6_excl_lo` (UJ) and `percentage_sum_div_10` (CPUT)
   were held to.
3. Add the case to `tests/test_scoring_worked_examples.py`.
4. Register the institution's `scoring_strategy: "custom_points_with_bonus"`
   and its real `scoring_config` in `seeds/institutions.json`.
5. Update `wits.md`/`spu.md` to record what was confirmed, or delete this
   file once every candidate institution has a verified config.
