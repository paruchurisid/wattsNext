create table if not exists pipeline_csv_imports (
  dataset text primary key,
  run_key text not null,
  source_filename text not null,
  row_count integer not null default 0 check (row_count >= 0),
  imported_at timestamptz not null default now()
);
create table if not exists pipeline_csv_rows (
  dataset text not null references pipeline_csv_imports(dataset) on delete cascade,
  row_number integer not null check (row_number > 0),
  row_data jsonb not null,
  primary key (dataset, row_number)
);
