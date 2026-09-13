# The bundle format

A **bundle** is the hand-typed input to this repository: one JSON file per
institution per academic year, holding a flat transcription of that
institution's prospectus admission tables. `scripts/ingest_bundle.py`
converts it (via `scripts/convert_bundle.py`), validates it, and loads it
into Postgres.

You write what the table *looks like*. The converter works out what it
*means*.

- **Schema:** `seeds/bundle.schema.json` — point your editor at it and it
  validates while you type.
- **Converter:** `scripts/convert_bundle.py`
- **Ingestion:** `scripts/ingest_bundle.py` — the real path into Postgres.
- **Output schema:** `seeds/programme.schema.json`

---

## Shape

```json
{
  "institution": {
    "id": "uj",
    "name": "University of Johannesburg",
    "scoring_strategy": "aps_best6_excl_lo",
    "scoring_config": { "subject_count": 6, "exclude_subjects": ["life_orientation"] }
  },
  "academic_year": 2027,
  "source": {
    "document": "uj_2027_prospectus.pdf",
    "retrieved_at": "2026-07-26"
  },
  "programmes": [ ... ]
}
```

`institution.id` must already be one of the 26 public universities listed
in `extract/institution_map.py` — ingestion never guesses or auto-creates
one; an unrecognised id is rejected with the list of known ids.

`source.document` should be the R2 key `scripts/archive_source.py` prints
after archiving the source PDF, so `source_doc` on every resulting record
resolves to a real, fetchable document — but ingestion doesn't enforce
that shape, since a bare filename is still meaningfully better than
nothing while an institution is mid-transcription.

One file per institution-year. Ship several by zipping them together:

```
bundles.zip
├── uj_2027.json
├── cput_2027.json
└── wits_2027.json
```

`ingest_bundle.py` (and `convert_bundle.py`) accept a `.zip` of these, a
plain directory of them, or a single bare `.json` file.

---

## A programme record

```json
{
  "qualification_code": "B8CD2Q",
  "programme": "BA (Communication Design)",
  "faculty": "Faculty of Art, Design and Architecture",
  "qualification_type": "Degree",
  "duration_years": 3,
  "campus": ["APB"],
  "source_page": 32,
  "scoreable": true,

  "minimum_aps": { "with_mathematics": 25, "with_mathematical_literacy": 26 },

  "requirements": {
    "english": 5,
    "mathematics": 3,
    "mathematical_literacy": 4,
    "technical_mathematics": "not_accepted"
  },

  "selection_notes": []
}
```

| Field | Notes |
|---|---|
| `qualification_code` | Required. Must be unique within the institution-year. |
| `programme` | Required. The programme's title. |
| `duration_years` | **Required, and never guessed from the name.** "BEng" is 4 years, "BEngTech" is 3, and neither says so. Read it off the section heading. |
| `minimum_aps` | Required. A plain integer, or a variants object — see below. |
| `requirements` | Required. One entry per subject column in the source table. |
| `qualification_type` | Optional. The section heading the row sat under. A value starting `Extended` sets `extended: true`. |
| `extended` | Optional. Overrides the value derived from `qualification_type`. |
| `faculty`, `campus`, `source_page`, `career_text`, `selection_notes` | Optional, carried through as-is. |
| `excluded_subjects` | Optional. Exclusions stated in prose *under* the table rather than in a column. Merged with those derived from `not_accepted`. |
| `confidence` | Optional. Ignored on ingestion — see [Confidence is never yours to set](#confidence-is-never-yours-to-set) below. |
| `scoring_override` | Optional. Merges over the institution's `scoring_config` for this one programme — see below. |
| `scoring_strategy_override` | Optional. Replaces the institution's `scoring_strategy` outright for this one programme — see below. |
| `scoreable` | Optional, defaults `true`. `false` means no formula produces a trustworthy score for this programme at all — see below. |

---

## The three things this format must get right

These are documented individually, with a worked example each, because
they are where a transcription silently goes wrong — the mistake produces
a structurally valid bundle that means something different from what the
prospectus actually says.

### (a) `"not_accepted"` is not `null`

```json
"mathematical_literacy": "not_accepted"   // -> excluded_subjects entry
"physical_science": null                   // -> nothing at all
(key omitted entirely)                     // -> nothing at all
```

These are **opposite** in the target schema and **identical to the eye**
on the printed page — several UJ tables render both as a plain dash.

- **B34CAQ** (Bachelor of Accounting) — Mathematical Literacy's cell
  reads *"Not accepted"*. A learner offering it instead of Mathematics is
  actively barred. This must become an `excluded_subjects` entry, or a
  Maths-Lit candidate the university rejects would silently qualify.
- **B2I02Q** — Physical Science's column reads *"Not applicable"*. The
  programme simply doesn't ask for it. This must produce **nothing**.

The retired PDF extractor could not tell these apart from the page and
had to restore the distinction from a hand-maintained correction table
after the fact. A human transcriber CAN tell them apart, by reading the
sentence under the table — so the format demands you say which, and the
converter trusts that answer literally.

```json
{ "english": 4, "mathematics": 5,
  "mathematical_literacy": "not_accepted", "technical_mathematics": "not_accepted" }
```
→
```json
{
  "score": [{ "min_score": 33, "requires_subject": "mathematics" }],
  "subjects": { "kind": "all", "rules": [
    { "kind": "subject", "language": "english", "min_level": 4 },
    { "kind": "subject", "subject": "mathematics", "min_level": 5 }
  ]},
  "excluded_subjects": ["mathematical_literacy", "technical_mathematics"]
}
```
Note what did **not** happen: Mathematics and Mathematical Literacy are in
the same national subject-choice group (see (b) below) and both appear in
the record, yet the result stays a plain `all` with Mathematics required
— because Mathematical Literacy was excluded, not levelled. Turning this
into "Mathematics OR Mathematical Literacy" would admit exactly the
learners UJ rejects.

### (b) AND vs OR

A flat `requirements` dict is **AND by default** — every key present must
be satisfied. There are two ways a requirement becomes OR instead, and
only one of them is automatic:

**Automatic** — Mathematics / Mathematical Literacy / Technical
Mathematics is one national NSC subject-choice group: no South African
university requires two of them, because a learner picks between them in
matric and can never hold two. Whenever **two or more of them carry a
level in the same record**, the converter merges them into one `any` node
on its own, whether or not the table prints an "OR":

```json
"mathematics": 3, "mathematical_literacy": 4
```
→ `any(mathematics 3, mathematical_literacy 4)` *(this is B8CD2Q)*

Three of them merge into one flat three-way `any`, not nested pairs:

```json
"mathematics": 4, "technical_mathematics": 4, "mathematical_literacy": 5
```
→ `any(mathematics 4, technical_mathematics 4, mathematical_literacy 5)`
*(this is B34HRQ)*

**Manual** — everything else is NOT automatic. Physical Sciences /
Technical Sciences, for instance, can genuinely both be held at once
(unlike Mathematics/Maths Lit), so a programme that accepts either has to
say so explicitly, with an `any_of` block:

```json
"any_of": [{ "physical_science": 5 }, { "technical_science": 5 }]
```

**Worked example — B6CV3Q**, which needs BOTH kinds of OR in one record,
as two sibling `any` nodes inside one `all`:

```json
{
  "qualification_code": "B6CV3Q",
  "programme": "Bachelor of Engineering Technology in Civil Engineering",
  "faculty": "Engineering and the Built Environment",
  "campus": ["DFC"],
  "duration_years": 3,
  "source_page": 60,
  "minimum_aps": { "with_mathematics": 28, "with_technical_mathematics": 28 },
  "requirements": {
    "english": 4,
    "mathematics": 5,
    "technical_mathematics": 5,
    "any_of": [{ "physical_science": 5 }, { "technical_science": 5 }]
  }
}
```
→
```json
{
  "kind": "all",
  "rules": [
    { "kind": "subject", "language": "english", "min_level": 4 },
    { "kind": "any", "rules": [
      { "kind": "subject", "subject": "mathematics", "min_level": 5 },
      { "kind": "subject", "subject": "technical_mathematics", "min_level": 5 }
    ]},
    { "kind": "any", "rules": [
      { "kind": "subject", "subject": "physical_sciences", "min_level": 5 },
      { "kind": "subject", "subject": "technical_sciences", "min_level": 5 }
    ]}
  ]
}
```

Mathematics/Technical Mathematics needed no special syntax at all —
naming both was enough. Physical/Technical Science needed `any_of`,
because there is no national convention saying a learner can only hold
one.

Only **one** `any_of` block is supported per programme — no record in the
180-programme UJ dataset this format was built against ever needed a
second manual OR group. A future institution that does will need this
extended, not worked around with a second key.

### (c) Language bands

```json
"english": 5
```
→ one level, the same for HL and FAL candidates.

```json
"english": { "home_language": 5, "first_additional_language": 6 }
```
→ `min_level: 5, min_level_fal: 6` — different thresholds depending on
which the learner actually took.

Every BEd programme uses the banded form. Flattening it to a single
number makes every one of them unscoreable for First-Additional-Language
candidates — which is most of the country, since Home Language English is
the minority case nationally. Languages are always written as the
**family** (`english`, `isizulu`, …), never as `english_hl`/`english_fal`
— the band object is how the HL/FAL split gets expressed.

---

## Scoring: per-institution, sometimes per-programme

`institution.scoring_strategy` and `scoring_config` pick the algorithm and
its parameters for every programme at that institution by default — see
`api/src/app/scoring.py` for the registered algorithms (`aps_best6_excl_lo`,
`percentage_sum_div_10`, `weighted_levels`) and what each one's config
accepts.

Two escape hatches exist for a programme that genuinely departs from its
own institution's default, because that happens at the FACULTY level, not
just the institution level — UCT's Faculty of Science doubles Mathematics
and Physical Sciences within an otherwise-standard APS; its Commerce
faculty doesn't (`docs/scoring/uct.md`):

- **`scoring_override`** — a config dict merged *over* the institution's
  own `scoring_config` for this one programme. Use this when the
  ALGORITHM is the same but a parameter differs (e.g. a faculty-specific
  `subject_count`).
- **`scoring_strategy_override`** — replaces the institution's
  `scoring_strategy` outright. Use this when the faculty uses a genuinely
  different algorithm, not just different parameters of the same one.

Both are rare. Leave them out unless a specific programme's prospectus
states a different formula than the rest of its institution.

A `scoring_strategy` that is registered in `SCORERS` but has no verified
worked example yet (recorded as UNVERIFIED in `docs/scoring/{id}.md` —
`weighted_levels` currently) loads fine, with a loud warning in the
ingestion report. An unregistered strategy is rejected outright.

### `scoreable: false` — when no formula applies at all

Some programmes cannot be scored by any formula this dataset implements,
because admission depends on an input `/v1/qualify` deliberately never
collects. The known case: Wits's and UCT's Faculty of Health Sciences
fold National Benchmark Test (NBT) results into a Composite Index /
Weighted Points Score (`docs/scoring/wits.md`, `uct.md`) — most learners
have no NBT results, so the request schema was deliberately never given
an NBT field for the sake of a handful of programmes at two institutions.

Set `"scoreable": false` on such a programme and `/v1/qualify` reports it
in its own `requires_additional_assessment` bucket — carrying only its
name and `selection_notes`, never a score, never in `qualified` or
`near_misses`. Put the human-readable explanation of what else the
learner needs (e.g. "Composite Index includes NBT results — see
wits.ac.za/nbt") in `selection_notes`, since that's the only field this
bucket carries.

`minimum_aps` and `requirements` are still required even when
`scoreable: false` — `/v1/qualify` never evaluates them for such a
programme, but this format doesn't yet have a shape for "admission
depends on something other than an NSC score and subject tree" beyond
"mark it unscoreable and explain in selection_notes." A best-effort
transcription of the printed NSC-side requirements (if any) is fine.

---

## `requirements`: levels, not percentages

Every value in `requirements` (other than `any_of`) is an **NSC
achievement level, 1–7**. The prospectus prints cells like `5 (60%+)`;
the number you want is the **5**. Typing `60` is the single likeliest
transcription slip, so the validator rejects any level outside 1–7 rather
than quietly accepting it as a percentage.

Four value forms in total:

| Value | Meaning |
|---|---|
| `5` | Required at level 5. |
| `"not_accepted"` | **Excluded** — see (a) above. |
| `null`, or the key omitted | Not mentioned. Bars nobody. |
| `{"home_language": 5, "first_additional_language": 6}` | A language band — see (c) above. |

### Subject keys

Use the canonical subject name (`mathematics`, `physical_sciences`,
`life_sciences`, `accounting`, …). Common prospectus spellings are
accepted too — `physical_science`, `technical_science`, `life_science`,
`maths`, `technical_maths`, `maths_literacy`.

`additional_language` means "any recognised additional language", and the
converter always places it last in the tree so a named language rule is
consumed first.

The vocabulary is **closed**: an unrecognised key is an error, never
silently dropped, because a dropped column is a lost requirement.

---

## `minimum_aps`

A plain integer:

```json
"minimum_aps": 26
```

Or, when the published APS depends on which maths subject the learner
offers:

```json
"minimum_aps": {
  "with_mathematics": 31,
  "with_mathematical_literacy": 32
}
```

Valid variant keys are `with_mathematics`, `with_technical_mathematics`
and `with_mathematical_literacy`. Each becomes its own threshold, and the
API picks the one matching the learner's actual subjects.

There is one further shape, for programmes keying the APS off the
**English rating** rather than a subject — the schema has no equivalent,
so the converter encodes the strictest printed value and records the
original in `selection_notes`:

```json
"minimum_aps": {
  "with_english_rating_5": 24,
  "with_english_rating_5_upper": 26,
  "with_english_rating_4": 27
}
```
→ `min_score: 27`, plus a note. Under-qualifying a few learners is safer
than over-promising.

---

## Confidence is never yours to set

`confidence` is a bundle field the schema accepts but ingestion **always
ignores**. Every record ingestion writes — new or changed — is stamped
`confidence: 'extracted'`, never `'verified'`, no matter what the bundle
says. Nothing reaches `'verified'` except a human, editing the row
directly after reading the ingestion report. `export_data.py`'s CI
default (`--verified-only`) means an unreviewed bundle cannot reach
production by being loaded, full stop — see the README's operator flow.

A record that WAS `'verified'` and that this bundle actually CHANGES
drops back to `'extracted'` automatically, and is listed prominently in
the ingestion report: a human verified the old value, and hasn't seen the
new one yet. A record the bundle repeats UNCHANGED keeps whatever
confidence it already had — re-ingesting the same bundle twice never
downgrades anything, because nothing about it changed.

---

## Working on a bundle

```bash
# 1. Archive the source PDF; keep the key it prints.
uv run python scripts/archive_source.py --institution uj --year 2027 \
    --pdf data/downloads/uj_2027.pdf

# 2. Type the bundle(s), with seeds/bundle.schema.json wired into your editor.
#    Zip them together if there's more than one institution.

# 3. Dry run: validate and see the diff against Postgres, write nothing.
uv run python scripts/ingest_bundle.py bundles.zip --dry-run

# 4. Read the report, fix what it flags, repeat step 3.

# 5. Ingest for real.
uv run python scripts/ingest_bundle.py bundles.zip

# 6. Review the report's flagged/changed records in Studio or by hand,
#    and set confidence='verified' on the ones you've actually checked.
#    Nothing reaches production without this step -- see above.
```

The dry run in step 3 runs every stage except the actual write: unpack,
identify the institution, structural checks, conversion, the same
semantic validator `seeds/` itself is checked with (swapped
Mathematics/Maths-Literacy columns, implausible APS, missing English,
missing duration — see the README's Validation section), and a diff
against whatever is already in Postgres for that institution-year. Those
checks **report**; they never repair, and a bundle that fails any of them
is rejected whole — no half-loaded institution.

For UJ specifically there is a second opinion available:
`tools/uj_extract.py` reads the 2027 prospectus directly and prints its
own numbers. It is UJ-only and its output is not a bundle, but it is a
free cross-check on a page you have just typed.

`scripts/export_bundle.py` does the reverse conversion — an already-
loaded institution's tree-shaped records back to this flat format. It
exists as a template generator (export an institution close to the one
you're transcribing, to see the shape) and as the mechanism behind this
format's own round-trip test (`tests/test_export_bundle.py`): the 29
hand-verified UJ records, exported to flat and converted straight back,
must reproduce their exact original trees. If a real record can't survive
that trip, the format is missing something.
