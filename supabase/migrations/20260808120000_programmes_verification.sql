alter table programmes add column verification jsonb not null default '{}';

-- Named distinctly from the existing confidence-based
-- programmes_needs_review_idx (ON (confidence) WHERE confidence <>
-- 'verified') -- that index already serves a different, established
-- purpose and is left untouched; this one is scoped to per-field
-- extraction-ensemble disagreement, not overall record confidence.
create index programmes_verification_needs_review_idx on programmes (((verification->>'needs_review')::boolean))
  where (verification->>'needs_review')::boolean = true;
