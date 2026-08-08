create table ingestions (
  id                 uuid primary key default gen_random_uuid(),
  institution_id     text not null references institutions(id) on delete cascade,
  academic_year      int  not null,
  source_filename    text not null,
  content_sha256     text not null unique,
  r2_key             text,
  status             text not null default 'pending'
                     check (status in ('pending','needs_profile','classifying',
                                        'extracting','verifying','review_ready','failed')),
  page_count         int,
  table_pages        int[] not null default '{}',
  stats              jsonb not null default '{}',
  error              text,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create index ingestions_status_idx on ingestions (status);
create index ingestions_inst_year_idx on ingestions (institution_id, academic_year);
