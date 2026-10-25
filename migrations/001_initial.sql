-- Watt'sNext production schema. Safe to re-run.
create extension if not exists pgcrypto;

create table if not exists households (
  id uuid primary key default gen_random_uuid(),
  external_id text not null unique,
  display_name text not null,
  city text not null,
  declared_needs jsonb not null default '{}'::jsonb,
  alert_opt_in boolean not null default false,
  alert_channel text check (alert_channel in ('sms','email','push')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists substations (
  id uuid primary key default gen_random_uuid(),
  external_key text not null unique,
  name text not null,
  territory text,
  source_provenance text not null default '[SOURCE_DATA]'
);

create table if not exists circuits (
  id uuid primary key default gen_random_uuid(),
  external_key text not null unique,
  substation_id uuid references substations(id),
  feeder_prefix text,
  customer_count integer check (customer_count >= 0),
  asset_density jsonb not null default '{}'::jsonb,
  source_provenance text not null default '[SOURCE_DATA]'
);

create table if not exists replay_cases (
  id uuid primary key default gen_random_uuid(),
  case_key text not null unique,
  label text not null,
  storm_setting text not null check (storm_setting in ('calm','moderate','severe')),
  circuit_id uuid references circuits(id),
  path_valid boolean not null default true,
  source_note text,
  created_at timestamptz not null default now()
);

create table if not exists damage_records (
  id uuid primary key default gen_random_uuid(),
  source_record_key text unique,
  replay_case_id uuid references replay_cases(id),
  damage_circuit_id text,
  customer_circuit_id text,
  normalized_circuit_id text,
  asset_type text not null,
  quantity integer not null check (quantity > 0),
  size_kva numeric,
  status text not null check (status in ('repaired','unrepaired','unknown')),
  repair_timestamp timestamptz,
  quarantined boolean not null default false,
  quarantine_reason text,
  reconciliation_confidence text check (reconciliation_confidence in ('direct','feeder','substation','unresolved')),
  source_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  check (not (status = 'unrepaired' and repair_timestamp is not null) or quarantined = true)
);

create table if not exists labor_references (
  id uuid primary key default gen_random_uuid(),
  asset_type text not null,
  size_group text,
  size_kva numeric,
  install_hours numeric not null check (install_hours >= 0),
  removal_hours numeric not null check (removal_hours >= 0),
  indirect_multiplier numeric not null default 4.5 check (indirect_multiplier = 4.5),
  source_provenance text not null default '[SOURCE_DATA]',
  unique(asset_type, size_group, size_kva)
);

create table if not exists simulation_sessions (
  id uuid primary key default gen_random_uuid(),
  session_key text not null unique,
  household_id uuid references households(id),
  scenario jsonb not null default '{}'::jsonb,
  state text not null default 'PRE_STORM' check (state in ('PRE_STORM','OUTAGE_CONFIRMED','ETR_UPDATED','RESTORED')),
  deterministic_input_hash text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists simulation_runs (
  id uuid primary key default gen_random_uuid(),
  session_id uuid references simulation_sessions(id) on delete cascade,
  iterations integer not null default 2500 check (iterations > 0),
  p10_hours numeric check (p10_hours >= 0),
  p50_hours numeric check (p50_hours >= p10_hours),
  p90_hours numeric check (p90_hours >= p50_hours),
  access_blocked boolean not null default false,
  crew_count integer not null default 1 check (crew_count > 0),
  topology jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists alert_events (
  id uuid primary key default gen_random_uuid(),
  session_id uuid references simulation_sessions(id) on delete cascade,
  household_id uuid references households(id),
  stage text not null check (stage in ('PRE_STORM_ADVISORY','OUTAGE_CONFIRMED','ETR_UPDATED','POWER_RESTORED')),
  channel text,
  message text not null,
  triggered_at timestamptz not null default now(),
  metadata jsonb not null default '{}'::jsonb
);

create table if not exists governance_audit_log (
  id bigserial primary key,
  timestamp timestamptz not null default now(),
  household_id text,
  deterministic_input_hash text not null,
  raw_llm_output text,
  provider text not null default 'deterministic',
  validation_passed boolean not null,
  fallback_triggered boolean not null,
  latency_ms integer check (latency_ms >= 0),
  metadata jsonb not null default '{}'::jsonb
);

create table if not exists data_quality_reports (
  id uuid primary key default gen_random_uuid(),
  report_key text not null unique,
  quarantined_count integer not null default 0 check (quarantined_count >= 0),
  reconciliation_summary jsonb not null default '{}'::jsonb,
  generated_at timestamptz not null default now()
);

create index if not exists idx_damage_records_case on damage_records(replay_case_id);
create index if not exists idx_damage_records_quarantine on damage_records(quarantined);
create index if not exists idx_sessions_household on simulation_sessions(household_id);
create index if not exists idx_simulation_runs_session on simulation_runs(session_id, created_at desc);
create index if not exists idx_alert_events_session on alert_events(session_id, triggered_at desc);
create index if not exists idx_audit_timestamp on governance_audit_log(timestamp desc);

create or replace function prevent_audit_mutation() returns trigger language plpgsql as $$
begin raise exception 'governance_audit_log is append-only'; end;
$$;
drop trigger if exists governance_audit_immutable on governance_audit_log;
create trigger governance_audit_immutable before update or delete on governance_audit_log
for each row execute function prevent_audit_mutation();
