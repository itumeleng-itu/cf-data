# Sol Plaatje University (SPU) — admission scoring investigation

Read-only investigation, produced via a research pass (WebSearch/WebFetch,
not a direct prospectus read the way `uct.md` and the original `wits.md`
were). No `scoring_strategy` registered to `spu` in `seeds/institutions.json`
— nothing in this repo currently loads any SPU data at all.

## What's confirmed, and how

SPU does **not** use the default `aps_best6_excl_lo` convention this
dataset otherwise defaults to. Multiple independent sources converge on
the same shape:

- SPU uses its **own points table**, not the standard NSC 1-7 achievement
  levels. Claimed structure (see "Not independently verified" below):
  the old 80-100% band splits into two tiers worth 7 and 8 points, i.e.
  roughly a 1-8 scale.
- **Mathematics and Home Language get bonus points** on top of their
  base points, tiered by percentage.
- **Life Orientation is scored on its own separate 0-4 scale** — and,
  like Wits, is **added into the total, not excluded**: a fresh search
  independently confirms *"SPU uses all 7 NSC subjects — including Life
  Orientation"*.

## Confirmed vs. not — read this before trusting a number

**Life Orientation's 0-4 scale** — confirmed by two independent sources
in close agreement: `90-100%=4, 80-89%=3, 70-79%=2, 60-69%=1, <60%=0`.

**The Mathematics/Home Language bonus THRESHOLDS are disputed between
sources, not just imprecisely worded:**

| Source | +1 bonus at | +2 bonus at |
|---|---|---|
| SPU's own 2026 prospectus PDF (one subagent's read, not independently reproduced) | 40-59% | 60-100% |
| A broader search across several aggregators | 40-59% | 60% + |
| coursematch.co.za (fetched directly, independently) | 50-69% | 70-100% |

Two of three agree on a 40/60 split, and `coursematch.co.za` being the
outlier matches a pattern already caught twice elsewhere in this project
— aggregator sites quietly mis-transcribing a real formula. That makes
40/60 the more likely number, **not a confirmed one.**

**The base 1-8 points table itself is the weakest claim here.** It rests
entirely on one subagent's read of `spu.ac.za`'s 2026 Undergraduate
Prospectus PDF. Two independent attempts to fetch and read that exact
PDF directly (via `WebFetch`, and via downloading it and attempting to
render it locally) both failed — the document's text layer extracts as
unreadable compressed stream data with the tools available in this
environment. The specific claim (80-100% splitting into a 7pt/8pt pair)
was never independently reproduced. It may well be right; it simply
hasn't been checked twice.

## Bottom line for scoring.py

`api/src/app/scoring.py`'s `_custom_points_with_bonus` was built to
express this shape (and Wits' — see `wits.md` section 5, which found the
same "own points table + named-subject bonus + Life-Orientation-on-its-
own-included-scale" pattern independently). It is registered but
**UNVERIFIED** for SPU: no official worked numeric example was found
anywhere in this research pass, and the base points table specifically
has never been read from SPU's own document by anyone in this project,
only cited by a subagent whose read could not be reproduced.

To move this to verified: get a human-readable copy of SPU's 2026
Undergraduate Prospectus (or contact SPU admissions directly — their own
admissions page shows the calculator as an image, not machine-readable
text) and check the base points table and the exact bonus thresholds
against a real example, per `tests/test_scoring_worked_examples.py`.
