-- Add design (experimental methodology) and decision (next-step) columns.
-- Idempotent: safe to run multiple times.

begin;

alter table public.nodes
    add column if not exists design   text not null default '',
    add column if not exists decision text not null default '';

commit;
