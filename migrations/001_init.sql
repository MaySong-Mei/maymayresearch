-- Research harness schema (mirror of git-backed thesis tree).
-- git is the source of truth; this is a publish target for the live dashboard.

begin;

-- Multi-repo support: every row carries a `repo` slug so multiple research
-- repos can share one Supabase project. The harness defaults to the repo dir
-- basename if not configured.
create table if not exists public.nodes (
    repo            text not null,
    sha             text not null,
    short           text generated always as (substring(sha, 1, 7)) stored,
    parents         text[] not null default '{}',
    type            text not null check (type in ('root','narrow','rigor','reframe','pivot','synthesis','unknown')),
    status          text not null check (status in ('pending','supported','not-detected','refuted','ceiling-bound','exhausted')),
    claim           text not null,
    prediction      text not null default '',
    evidence        text not null default '',
    notes           text not null default '',
    review_comments text[] not null default '{}',
    committed_at    timestamptz not null,
    published_at    timestamptz not null default now(),
    primary key (repo, sha)
);

create index if not exists nodes_repo_committed_idx on public.nodes (repo, committed_at);
create index if not exists nodes_repo_type_idx       on public.nodes (repo, type);

create table if not exists public.branches (
    repo         text not null,
    name         text not null,
    tip_sha      text not null,
    updated_at   timestamptz not null default now(),
    primary key (repo, name)
);

-- Reviews are pulled out so subsequent reviewer revisions can append rather
-- than overwrite the node row.
create table if not exists public.reviews (
    id           bigserial primary key,
    repo         text not null,
    sha          text not null,
    comments     text[] not null default '{}',
    reviewer     text not null default 'auto',
    created_at   timestamptz not null default now()
);

create index if not exists reviews_repo_sha_idx on public.reviews (repo, sha);

-- ── Row Level Security ─────────────────────────────────────────────────────
-- anon: read-only on all three tables
-- service role: bypasses RLS automatically (no policy needed)

alter table public.nodes    enable row level security;
alter table public.branches enable row level security;
alter table public.reviews  enable row level security;

drop policy if exists nodes_anon_read    on public.nodes;
drop policy if exists branches_anon_read on public.branches;
drop policy if exists reviews_anon_read  on public.reviews;

create policy nodes_anon_read    on public.nodes    for select using (true);
create policy branches_anon_read on public.branches for select using (true);
create policy reviews_anon_read  on public.reviews  for select using (true);

-- ── Realtime ───────────────────────────────────────────────────────────────
-- Add tables to the realtime publication so the dashboard receives push events.
do $$
begin
    if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
        execute 'alter publication supabase_realtime add table public.nodes';
        execute 'alter publication supabase_realtime add table public.branches';
        execute 'alter publication supabase_realtime add table public.reviews';
    end if;
exception when duplicate_object then
    -- already part of the publication; ignore
    null;
end $$;

commit;
