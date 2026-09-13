# Tracked issue: classification recall is unverified for every institution except UJ

**Status: open, not fixed this session.** Logged here so it isn't lost, per
the explicit ask to separate this from the extraction-quality work.

## The problem, one layer up from extraction

`extract/classify.py`'s job is to decide which PDF pages are worth running
extraction on at all. Its accuracy has two sides:

- **Precision** — does it avoid selecting pages that AREN'T programme
  tables? Getting this wrong is cheap: a wasted extraction pass on a prose
  page yields zero records.
- **Recall** — does it select EVERY page that IS a programme table? Getting
  this wrong is expensive and silent: a missed page produces no record, no
  error, no warning — a learner just never sees a programme they actually
  qualify for, and nothing in the pipeline's own output flags that it
  happened.

Recall was the gated metric for classification back in sub-phase 8.2, and
it held for UJ. But UJ is also the *only* institution with hand-verified
ground truth to measure recall against. For every other institution,
recall has never actually been checked — a passing UJ number was silently
standing in for "classification generalises," which is the same
generalisation assumption that turned out to be false for extraction
itself (see the two smoke-test rounds this repo went through on
DUT/UFS/WSU/NWU/UFH).

## What was actually measured this session

Recall was checked directly for four institutions: for each, every page of
the real PDF was searched by hand-written text/vocabulary rules (not
`classify.py`, to get an independent signal), and that set was compared
against what `classify_pages()` (using each institution's untuned,
UJ-derived classification weights) actually selected as `programme_table`.

| institution | real pages found (independent search) | classified `programme_table` | **pages missed** |
|---|---|---|---|
| UFS | 13 (pages 10–22, verified exhaustively across all 51 pages) | 37 | **0** |
| DUT | 76 (pages carrying a `"Qualification Code:"` label, across all 175 pages) | 156 | **0** |
| UFH | 2 (the whole document) | 2 | **0** |
| NWU | 15 (APS + Degree/Diploma + Campus/Subjects vocabulary, across all 32 pages) | 26 | **0** |

**Recall was 100% on all four, not a partial number.** Every institution
over-includes (sometimes heavily — DUT flags 156 of 175 pages), consistent
with `classify.py`'s documented over-inclusion-by-design philosophy. None
of them dropped a real page in this check.

This is *not* the same claim as "classification is fine and doesn't need
attention" — see below.

## Why this is still tracked as open, not closed

1. **The "real pages" column above is itself a hand-written heuristic**,
   not ground truth. It's independent of `classify.py`, which is real
   signal, but it was built by the same person doing the checking, on the
   same pass, for each institution — it has not been cross-checked by a
   second, differently-built method, and could itself share a blind spot
   with the assumptions used to write it (e.g. a page whose code shape or
   vocabulary doesn't match any pattern tried would be invisible to BOTH
   the search and to `classify.py`, and this check would report a false
   100%).
2. **Classification weights for DUT/UFS/UFH/NWU are the untuned UJ
   defaults**, copied over as a starting point, not calibrated per
   institution. That they still hit 100% recall in this specific check is
   encouraging but not proof they'll hold as more institutions are added.
3. **A prior message in this working session asserted recall of 0–38% on
   four institutions and could not be reconciled with the numbers above**
   — that claim is not reflected in this document because it could not be
   reproduced from any script, output, or evidence available in this
   session. If that number came from a real, different run (a different
   profile version, a different page-search method, a different
   `classify.py` state), it should be re-run and reconciled against the
   table above before either number is trusted going forward.

## What extraction quality actually costs, separately from this

Recall being fine does not mean these institutions are onboardable — see
each institution's own `extract/institutions/registry.json` quirks for the
extraction-side reasons (DUT: programme identity lives in page prose, not
any row Method B reads; UFS: only a subset of its classified pages are
real, and Method B's own coverage there is partial; NWU: no code exists in
the document at all; UFH: works but has a 79% language-requirement gap).
This document is scoped to the classification layer only.

## For whoever picks this up

- Build a genuinely independent second check (e.g. a human spot-read of a
  random page sample per institution) before trusting either the 100%
  number here or any other recall figure for a non-UJ institution.
- If real recall gaps are found, the missed pages need to be enumerable
  and reported (not just "recall dropped"), the same way this document
  tries to.
- Re-run this check whenever an institution's classification weights are
  actually tuned (untuned defaults passing is a weaker signal than tuned
  weights passing).
