alter table households add column if not exists case_key text;
create index if not exists idx_households_case_key on households(case_key);
