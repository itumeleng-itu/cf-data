create table institutions (
  id               text primary key,
  name             text not null,
  scoring_strategy text not null,
  scoring_config   jsonb not null default '{}'
);

create table programmes (
  id                 uuid primary key default gen_random_uuid(),
  institution_id     text not null references institutions(id) on delete cascade,
  academic_year      int  not null,
  qualification_code text not null,
  name               text not null,
  faculty            text,
  campus             text[] not null default '{}',
  duration_years     numeric,
  extended           boolean not null default false,
  requirements       jsonb not null,
  selection_notes    text[] not null default '{}',
  career_text        text,
  source_doc         text,
  source_page        int,
  confidence         text not null default 'extracted'
                     check (confidence in ('verified','extracted','flagged')),
  updated_at         timestamptz not null default now(),
  unique (institution_id, academic_year, qualification_code)
);

create index programmes_inst_year_idx on programmes (institution_id, academic_year);
create index programmes_needs_review_idx on programmes (confidence)
  where confidence <> 'verified';