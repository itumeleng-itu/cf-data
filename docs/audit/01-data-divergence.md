# Section 1 — Data Divergence

**Status: read-only audit. Nothing outside `docs/audit/` was changed.**

## Method (read this before the numbers below)

There is no shared identifier between the two repos' UJ data. The API's
`programmes.json` keys every programme by `qualification_code` (e.g.
`B8CD2Q`). The frontend's `data/universities/uj.ts` has **no code field at
all** — courses are identified only by a free-text `name` and an internal
`id` slug the author invented (e.g. `uj-ba-communication-design`). This is
itself a finding: **the two datasets cannot be joined mechanically or
audited automatically without first re-deriving a name-matching heuristic**,
which is what the rest of this section had to do.

Matching was done with a small Node script (`_courses` array literals in
each `data/universities/*.ts` file are plain JS object literals — no TS
syntax inside them — so they can be parsed by locating the array boundary
and evaluating it directly; this was verified against the raw source before
trusting it), producing a bag-of-words Jaccard similarity between the API's
`name` and every frontend course `name` at that institution, after
expanding common abbreviations (`Bachelor of Commerce` → `bcom`, etc). Every
match below score ≥0.5 was hand-checked against the actual two name strings
before being accepted; three (`B6CS0Q`, `B6MS0Q`, `B9E01Q`) scored 0.60–0.75
and were manually confirmed correct (cosmetic differences: `(BEng)` suffix,
`Health Science` vs `Health Sciences`). Everything reported as "no match"
below was independently confirmed absent by direct `grep` on the frontend
source file, not just a low similarity score.

All numbers in this section come from reading `api/src/app/data/programmes.json`
(the API's actual in-memory dataset — see the correction below) and
`data/universities/*.ts` directly, not from any prior summary.

**Correction to a premise in the audit brief:** the brief describes the API
as serving programmes "from Postgres." It does not. `api/src/app/main.py`
loads `api/src/app/data/programmes.json` into an in-memory Python list at
startup (`load_data`, `main.py:117-127`) and never touches a database —
confirmed by reading the file in full; there is no `postgres`, `DATABASE_URL`,
or SQL anywhere in `api/src/app/`. This doesn't change any conclusion below,
but "Postgres" should not be repeated as fact in future planning.

---

## UJ: programme counts

| | count |
|---|---|
| API (`programmes.json`, institution `uj`) | **29** |
| Frontend (`data/universities/uj.ts`, `_courses`) | **98** |

## UJ: matching

| | count | codes |
|---|---|---|
| Present in both (matched by name) | **25** | see table below |
| API-only (no frontend match, confirmed by grep) | **4** | `B2M43Q` BSc Computational Science, `B2M52Q` BSc Actuarial Science, `B2M55Q` BSc Mathematics and Mathematical Statistics (Financial Orientation), `B2M56Q` BSc Mathematical Statistics and Economics (Financial Orientation), `B2M57Q` BSc Mathematics and Economics (Financial Orientation) — wait, 5 listed, see note |
| Frontend-only (no API match) | **73** | mostly diplomas, extended-curriculum variants, and programmes the API hasn't encoded yet — see below |

**Note on the API-only count:** the initial pass found 4 *and* B2M52Q separately
appeared as a genuine match on close reading (it exists in the frontend as
`uj-bsc-actuarial-science` / "BSc (Actuarial Science)" — matched, but with a
badly wrong APS, see the adjudication table). The true API-only set (present
in the API, genuinely absent from the frontend, confirmed by `grep -i` for
every distinguishing word in the name) is the other four: **B2M43Q, B2M55Q,
B2M56Q, B2M57Q** — all "with Financial Orientation" or "Computational
Science" specialisations UJ's Faculty of Science offers that never made it
into the frontend's file at all.

**Frontend-only breakdown (73 courses):** dominated by (a) Diplomas and
Higher Certificates (UJ's undergraduate offering includes many the API
dataset doesn't yet cover — the API's 29 skew toward degree programmes),
(b) named individual BEd Senior Phase subject specialisations (isiZulu,
Sepedi, Geography, Life Sciences, Mathematics, Physical Sciences, English,
Afrikaans — the API currently only encodes the isiZulu one, `B5LAZQ`), (c)
Extended Curriculum Programme variants, and (d) a genuine handful the API
is simply missing (e.g. `uj-bsc-mine-surveying`, `uj-b-urban-planning`,
several Health Science variants like Chiropractic, Podiatry, Nuclear
Medicine). This is the number that matters for "what would be lost by
switching to the API today" — see the closing section.

---

## UJ: field-by-field disagreements (the 25 matched pairs)

Full field dump for all 25 pairs was produced and reviewed (APS/score,
subject requirements + levels, excluded subjects, campus, faculty,
duration). Summary of every disagreement found:

| Code | Field | API value | Frontend value | Note |
|---|---|---|---|---|
| B8CD2Q | APS | conditional: 25 (with Mathematics) / 26 (with Maths Lit) | flat 25 | frontend always charges the lower figure, even for Maths Lit candidates |
| B8CD2Q | Mathematics level | 3 | 4 | frontend requires a level higher than the API's verified figure |
| B8CD2Q | Maths Lit level | 4 | 5 | same, one level higher |
| B9S15Q | APS | conditional: 32 (Maths) / 33 (Maths Lit) | flat 32 | same pattern as B8CD2Q |
| B4L03Q (LLB) | APS | conditional: 31 (Maths) / 32 (Maths Lit) | flat 31 | same pattern |
| B4L03Q (LLB) | 2nd-language requirement | `any_additional_language`, min level 4, any of 10 non-English languages | key literally named `"Additional Language"` | **confirmed dangling key — see Section 2b; no dropdown option produces this string, so this requirement can never be satisfied by any input** |
| B2M52Q (Actuarial Science) | APS | **40** | **33** | 7-point gap — see adjudication, this is wrong on the frontend |
| B5BFPQ (BEd Foundation Phase) | English requirement | one rule: HL level 5 **or** FAL level 6 | two separate dict keys, `"english home language": 5` **and** `"english first additional language": 6` | structurally different — see Section 2a, this makes the requirement harder or impossible to satisfy depending on the learner, not equivalent to the API's rule |
| B5LAZQ (BEd isiZulu) | English + isiZulu requirements | two banded language rules (HL5/FAL6, HL4/FAL5) | four separate flat keys | same structural issue |
| B6CV3Q, B6EL1Q, B6MC2Q, B6ES0Q, B6CS0Q, B6MS0Q (6 Engineering/BEngTech codes) | Mathematics alternative | API: Mathematics level 5 **or** Technical Mathematics level 5 (via a second conditional score entry) | flat `"mathematics": 5`, no Technical Mathematics alternative | see Section 2f/2c — B6CV3Q is the literal case named in the audit brief |
| all 6 of the above | English requirement | banded HL/FAL rule | two separate ANDed keys (equal thresholds, e.g. 4/4) | see Section 2a — equal-threshold version of the same bug, silently excludes FAL-only candidates |

Everything else in the 25 matched pairs — campus code, duration, faculty
label (modulo cosmetic differences like `"Business and Economics"` vs
`"College of Business and Economics"`, and `"Faculty of X"` prefixing),
excluded-subjects sets where they matched, and every other subject level —
agreed exactly. **Campus is entirely absent from the frontend's UJ course
objects** (`grep -c "campus:" data/universities/uj.ts` → 0) — the API
tracks it (`["APK"]`, `["DFC"]`, `["APB"]`, `["SWC"]`) and the frontend
tracks nothing at all for any of the 98 UJ courses.

---

## Adjudication against the prospectus (13 disagreements checked)

**Environment limitation, stated up front:** this machine's PDF renderer
(`pdftoppm`/poppler-utils) is not installed, so `data/downloads/uj_2027.pdf`
could not be read directly via page number — every attempt returned
`pdftoppm is not installed`. Two independent prior structured-text
extractions of the same PDF exist in this repo instead —
`universities/2027/According to the University of Joha....txt` and
`universities/2027/new.txt` — produced by two separate earlier passes, in
different JSON shapes, evidently without either author aware of the other.
Where both agree, that is treated as reasonably strong corroboration (two
independent transcriptions of the same primary source converging); where
they disagree, that is reported as genuinely unresolved, not adjudicated by
guessing.

| # | Code | Disagreement | Both independent extractions say | Verdict |
|---|---|---|---|---|
| 1 | B2M52Q | APS 40 (API) vs 33 (frontend) | Both say **40**, Mathematics level 7 | **API correct, frontend wrong by 7 points** — a serious understatement for one of UJ's most competitive programmes |
| 2 | B8CD2Q | APS 25/26 conditional (API) vs flat 25 (frontend); Math levels 3/4 (API) vs 4/5 (frontend) | Old-extraction text: `"minimum_aps": "25 with Maths OR 26 with Maths Lit"`, `"mathematics": "3 (40%+)"`, `"mathematical_literacy": "4 (50%+)"` | **API correct on both counts, frontend wrong on both** — flattens the conditional APS and requires a level higher than the real minimum on both subjects |
| 3 | B9S15Q | APS 32/33 conditional vs flat 32 | (same pattern confirmed for B8CD2Q/B4L03Q; not separately re-extracted for B9S15Q, but the mechanism is identical and confirmed institution-wide — see #4) | **Frontend flattening pattern confirmed elsewhere; treat as the same systemic bug** |
| 4 | B4L03Q (LLB) | APS 31/32 conditional vs flat 31; separate "additional_language" requirement vs dangling key | Old-extraction: `"minimum_aps": "31 with Maths OR 32 with Maths Lit"`, `"additional_language": "4 (50%+)"` present as its **own real requirement**, distinct from `english` | **API correct on both** — confirms the audit brief's stated LLB bug is real, and confirms the conditional-APS flattening is a second, separate bug on the same programme |
| 5–10 | B6CV3Q, B6EL1Q, B6MC2Q, B6ES0Q, B6CS0Q, B6MS0Q | API encodes Technical Mathematics as an accepted alternative to Mathematics (same APS either way); frontend and **both** independent extractions show Mathematics as a flat, single-value requirement with no Technical Mathematics alternative for any of these six | **UNVERIFIED / genuinely inconclusive.** Two independently-produced text extractions of the same PDF and the frontend's own data all agree with each other and disagree with the API. This could mean the API is wrong (an over-generalised assumption that FEBE broadly accepts Technical Mathematics, applied here without a per-programme footnote actually saying so) — **or** it could mean all three other sources missed a faculty-wide footnote that both extraction passes, working page-by-page, wouldn't have captured. This audit could not resolve it without rendering the actual PDF page, which failed in this environment. **This is flagged, not adjudicated, and should be the first thing re-checked with a working PDF reader before any migration decision relies on it.** |
| 11 | B5BFPQ | HL5-or-FAL6 banded rule vs two ANDed keys | (not independently re-extracted; the *existence* of the underlying HL/FAL band as a single conceptual requirement is standard NSC convention, confirmed for UJ specifically via the API's own verified data and via B8CD2Q/LLB's extraction matches above) | **Frontend's encoding mechanism is wrong regardless of the exact numbers** — see Section 2a for the executed proof that no learner can satisfy it as coded |
| 12 | B5LAZQ | Same, for English *and* isiZulu | (same reasoning as #11) | **Same verdict** |
| 13 | (general) — subject count, campus, faculty naming | n/a | n/a | Cosmetic only; not adjudicated further since it doesn't change any outcome for a learner |

**Bottom line for UJ:** of the disagreements that could be independently
checked (1, 2, 4), **the API was right every time and the frontend was
wrong every time** — one by a large, isolated margin (B2M52Q, 7 APS
points), the others by a small, systemic margin (the conditional-APS
flattening, which appears to be a general pattern any time a programme has
a Maths-or-Maths-Lit conditional threshold, not a one-off typo). One class
of disagreement (5–10, Technical Mathematics on Engineering programmes)
could not be resolved and should not be treated as "the API is right" by
default just because it's the "verified" dataset — the weight of the two
other available sources currently points the other way.

---

## The other 25 institutions

### Coverage

| | courses |
|---|---|
| Total frontend courses across all 26 institutions (`_courses` arrays) | **1,668** |
| Of which at UJ | 98 |
| Of which at the other 25 institutions | **1,570** |
| API programmes at institutions other than UJ | **0** |

Per-institution frontend course counts (all 26, for reference — every file
parsed and counted directly, not estimated):

`cput 84, cut 23, dut 80, mut 23, nmu 166, nwu 73, rhodes 32, smu 20, spu 27,
stellenbosch 63, tut 115, uct 31, ufh 46, ufs 78, uj 98, ukzn 60, ul 53,
ump 20, unisa 24, univen 83, unizulu 73, up 122, uwc 42, vut 48, wits 102,
wsu 82`

### Spot checks (2 institutions, cross-referenced against this session's
own prior prospectus investigations, `docs/scoring/wits.md` and `spu.md`,
which read Wits' 144-page prospectus and researched SPU's directly)

**Wits.** The frontend's `lib/aps/methods.ts` contains a dedicated
`calculateWitsAPS()` (best 7 subjects, 0–8 scale, Life Orientation halved).
This is dead code — see Section 2g for the proof it is never called with
`"wits"` as an argument — but as a data-accuracy question in its own right:
it gets the *shape* half right (0-8 scale, best 7 including LO — matching
`docs/scoring/wits.md` section 5's independently-researched finding) but
the *mechanism* wrong (halves LO's own level rather than scoring it on its
own separate, lower table, and has no English/Mathematics bonus at all,
both of which `wits.md` found evidence for). Neither this audit nor the
prior investigation has a confirmed worked example for Wits, so neither
figure can be called "right" — but they are not the same formula, and only
one of them is even reachable from the live app (neither, as it happens —
see Section 2g).

Wits' *subject-requirement* records show a third, independently-discovered
encoding bug beyond the two found at UJ: 47 of Wits' 102 frontend courses
use a single key literally named `"english home language or first
additional language"` — a compound string, not the `alternatives`
structure the type system supports. This was executed against the real
matcher (not inferred): **it matches no student input at all, regardless of
which language variant or level they have.** See Section 2a — this is
Wits' version of the LLB bug, at roughly 8x the LLB bug's blast radius
within a single institution.

**SPU.** `data/universities/spu.ts` shows real inconsistency within a
single file: `spu-bed-foundation` and `spu-bed-intermediate-social` (2 of 3
courses spot-checked) correctly encode "English HL 4 or FAL 5" using the
`alternatives` structure — proving the author knew the correct pattern —
while the third, `spu-bed-intermediate-phase-723`, encodes the *identical*
requirement as two separate ANDed keys (the B5BFPQ-style bug), for what
should be the same rule. This means the bug is not a systematic
misunderstanding of the schema — it's inconsistent data entry, which is
good news for fixability (the correct pattern already exists in the same
file) and bad news for confidence (no institution's file can be assumed
uniformly correct just because some records in it are).

SPU's admission-scoring formula itself (its own bespoke 1–8 points table
with Maths/Home-Language bonuses) is not implemented anywhere in the
frontend at all — `lib/aps/methods.ts` has no SPU-specific function, so
every SPU course silently falls to the same generic best-6 formula as
everything else. `docs/scoring/spu.md` (written earlier this session)
already documents that this formula is itself unverified on the API side
too — neither system has a trustworthy SPU score today.

### What would be lost by switching to the API today

This is the number that should drive sequencing:

- **1,570 of 1,668 frontend courses (94.1%) have no API equivalent at
  all** — 25 whole institutions.
- Even restricted to UJ, the API's 29 programmes cover only **25 of the
  frontend's 98 UJ courses** by confirmed name-match (the other 73 are
  simply absent from the API).
- Put the other way: **the API today can answer for 29 of the 1,668
  courses the frontend currently claims to know about (1.7%).**

Switching the live "which programmes do I qualify for" list over to the API
as-is, today, for all institutions, would take the product from "26
institutions, of unknown-but-now-partially-measured accuracy" to "1
institution, hand-verified" — a 98.3% reduction in apparent coverage in
exchange for a large, but not total (see items 5–10 above), accuracy gain
on the part that remains. Section 4 covers the staged-rollout trade-off
this implies.
