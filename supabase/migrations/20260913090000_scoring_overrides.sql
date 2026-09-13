-- Generalises scoring per-programme, not just per-institution.
--
-- scoring_override merges over institutions.scoring_config for one
-- specific programme's score calculation -- e.g. a faculty that adjusts
-- the standard formula's parameters (UCT's Science faculty doubles
-- Mathematics/Physical Sciences within an otherwise-normal APS).
--
-- scoring_strategy_override replaces the institution's scoring_strategy
-- outright for one programme, because some faculties use a different
-- ALGORITHM, not just different parameters of the same one (UCT and
-- Wits both fold National Benchmark Test results into a Faculty
-- Points/Composite Index for Health Sciences specifically -- see
-- docs/scoring/uct.md and wits.md). Kept as a separate column rather
-- than overloading scoring_override, because "same algorithm, different
-- config" and "different algorithm entirely" are different failure modes
-- for whoever reads this data later.
--
-- Both nullable: absent means "use the institution's own scoring
-- unchanged", the overwhelmingly common case.
alter table programmes add column scoring_override jsonb;
alter table programmes add column scoring_strategy_override text;

-- scoreable=false marks a programme the API cannot compute a score for
-- at all -- not "scores low", but "no formula we have produces a
-- trustworthy number" (the Wits/UCT Health Sciences Composite Index
-- case: it needs National Benchmark Test results the API never
-- collects, deliberately -- see docs/scoring/uct.md and wits.md).
-- /v1/qualify buckets these separately (requires_additional_assessment),
-- never as qualified, near-miss, or scored.
alter table programmes add column scoreable boolean not null default true;
