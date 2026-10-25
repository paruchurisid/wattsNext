"""Replace validated weather/outage CSV products in Neon."""
import argparse, csv, json, os
from pathlib import Path
import psycopg

DATASETS = ("historical_weather.csv", "severe_weather_events.csv", "power_outages.csv", "weather_forecast.csv")

def load_env(root):
    for name in (".env.local", ".env"):
        path = root / name
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"'))
            return

def import_file(conn, path, run_key):
    dataset = path.stem
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{path} has no CSV header")
        with conn.cursor() as cur:
            cur.execute("delete from pipeline_csv_rows where dataset = %s", (dataset,))
            cur.execute("insert into pipeline_csv_imports (dataset, run_key, source_filename, row_count) values (%s,%s,%s,0) on conflict (dataset) do update set run_key=excluded.run_key, source_filename=excluded.source_filename, row_count=0, imported_at=now()", (dataset, run_key, path.name))
            count = 0
            with cur.copy("copy pipeline_csv_rows (dataset, row_number, row_data) from stdin") as copy:
                for count, row in enumerate(reader, 1):
                    copy.write_row((dataset, count, json.dumps(row)))
            cur.execute("update pipeline_csv_imports set row_count=%s, imported_at=now() where dataset=%s", (count, dataset))
    return count

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--run-key", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    load_env(root)
    url = os.environ.get("DATABASE_URL_UNPOOLED") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL_UNPOOLED or DATABASE_URL is required")
    with psycopg.connect(url) as conn:
        counts = {name: import_file(conn, args.data_dir / name, args.run_key) for name in DATASETS}
        conn.commit()
    print(json.dumps(counts, sort_keys=True))

if __name__ == "__main__":
    main()
