"""Run, resume and verify the county weather/outage ingestion product."""

import argparse
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
from src import (
    fetch_historical_weather,
    fetch_severe_weather,
    fetch_power_outages,
    fetch_weather_forecasts,
)
from src.common import STATUS, configure_cache, get, manifest, atomic_json
from src.validation import validate, validate_directory
from src.reporting import build_report

MODULES = {
    "historical": fetch_historical_weather,
    "hazards": fetch_severe_weather,
    "outages": fetch_power_outages,
    "forecasts": fetch_weather_forecasts,
}


def execute(start, end, outdir, resolution, names=None, **options):
    complete = True
    coverage = {}
    require_samples = options.pop("require_samples", False)
    outdir.mkdir(parents=True, exist_ok=True)
    for name, module in MODULES.items():
        if names and name not in names:
            continue
        try:
            logging.info("%s: fetching %s through %s", name, start, end)
            staging = outdir / ".staging"
            staging.mkdir(exist_ok=True)
            status_start = len(STATUS)
            with TemporaryDirectory(prefix=name + "-", dir=staging) as directory:
                working = Path(directory)
                frame = module.run(
                    start,
                    end,
                    working,
                    resolution=resolution,
                    hazard_path=outdir / "severe_weather_events.csv",
                    **options,
                )
                coverage[name] = validate(name, frame, start, end)
                if require_samples and frame.empty:
                    raise ValueError(
                        f"Smoke test requires actual sample rows from {name}"
                    )
                if name in ("historical", "forecasts") and frame.empty:
                    raise ValueError(f"No {name} observations returned")
                for artifact in working.iterdir():
                    if artifact.is_file():
                        os.replace(artifact, outdir / artifact.name)
            atomic_json(
                outdir / "reports" / (name + ".json"),
                {"validation": coverage[name], "sources": STATUS[status_start:]},
            )
            print(f"\n{name}: {len(frame):,} actual rows", flush=True)
            print(frame.head(3).to_string(index=False), flush=True)
            print("Join keys: zero missing", flush=True)
            # Event-free windows are valid; historical hourly weather is mandatory.
            if name in ("historical", "forecasts") and frame.empty:
                raise ValueError(f"No {name} observations returned")
        except Exception as exc:
            logging.error("%s failed: %s", name, exc)
            STATUS.append({"source": name, "status": "failed", "error": str(exc)})
            coverage[name] = {"validation": "failed", "error": str(exc)}
            complete = False
        manifest(outdir / "ingestion_status.json")
        (outdir / "validation_summary.json").write_text(
            json.dumps(coverage, indent=2), encoding="utf-8"
        )
    return complete


def smoke_window(start, end):
    import re

    metadata = get("https://api.figshare.com/v2/articles/24237376").json()
    years = [
        int(m[1])
        for f in metadata["files"]
        if (m := re.fullmatch(r"eaglei_outages_(20\d{2})\.csv", f["name"]))
    ]
    usable = [
        y for y in years if pd.Timestamp(start).year <= y <= pd.Timestamp(end).year
    ]
    if not usable:
        return start, min(
            pd.Timestamp(end), pd.Timestamp(start) + pd.Timedelta(days=6)
        ).date().isoformat()
    # A deterministic historical week in a year actually published by all primary archives.
    a = max(pd.Timestamp(start), pd.Timestamp(max(usable), 1, 1))
    return a.date().isoformat(), min(
        pd.Timestamp(end), a + pd.Timedelta(days=6)
    ).date().isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--progress",
        action="store_true",
        help="Show durable outage download progress without network access",
    )
    parser.add_argument("--start-year", type=int, default=2015)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate existing CSVs without network access",
    )
    parser.add_argument(
        "--skip-smoke",
        action="store_true",
        help="Resume a previously validated backfill",
    )
    parser.add_argument(
        "--strict-coverage",
        action="store_true",
        help="Fail on documented publisher coverage gaps as well as source failures",
    )
    parser.add_argument("--resolution", choices=["event", "15min"], default="event")
    parser.add_argument(
        "--pipelines", nargs="+", choices=list(MODULES), default=list(MODULES)
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--forecast-runs",
        action="append",
        default=[],
        help="Additional exact UTC model initialization, repeatable (YYYY-MM-DDTHH:MM)",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    try:
        start = (
            pd.Timestamp(args.start_date or f"{args.start_year}-01-01")
            .date()
            .isoformat()
        )
        end = (
            min(
                pd.Timestamp(args.end_date or f"{args.end_year}-12-31"),
                pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
                - pd.Timedelta(days=1),
            )
            .date()
            .isoformat()
        )
    except ValueError as exc:
        parser.error(str(exc))
    if start > end:
        parser.error("Start date exceeds available end date")
    configure_cache(args.output_dir / "cache")
    if args.progress:
        from src.progress import progress

        print(json.dumps(progress(args.output_dir / "cache"), indent=2), flush=True)
        return 0
    if args.validate_only:
        try:
            report = validate_directory(args.output_dir, start, end)
            atomic_json(args.output_dir / "validation_summary.json", report)
            build_report(args.output_dir, start, end)
            print(json.dumps(report, indent=2), flush=True)
            return 0
        except (ValueError, OSError) as exc:
            logging.error("Validation failed: %s", exc)
            return 2
    if not args.skip_smoke or args.smoke_test:
        a, b = smoke_window(start, end)
        logging.info(
            "Smoke test uses common published archive week %s through %s", a, b
        )
        ok = execute(
            a,
            b,
            args.output_dir / "smoke",
            args.resolution,
            args.pipelines,
            forecast_runs=args.forecast_runs,
            require_samples=True,
        )
        if not ok:
            logging.error(
                "Smoke validation failed; see data/smoke/ingestion_status.json"
            )
            return 2
        if args.smoke_test:
            return 0
    STATUS.clear()
    ok = execute(
        start,
        end,
        args.output_dir,
        args.resolution,
        args.pipelines,
        forecast_runs=args.forecast_runs,
    )
    failures = any(s["status"] in ("failed", "unavailable") for s in STATUS)
    gaps = any(s["status"] == "coverage_gap" for s in STATUS)
    summary = {
        "schema_version": "1.0",
        "pipelines": args.pipelines,
        "all_products_built": len(args.pipelines) == len(MODULES),
        "start": start,
        "end": end,
        "validation_passed": ok,
        "source_failures": failures,
        "publisher_coverage_gaps": gaps,
        "status": "failed"
        if not ok or failures
        else ("complete_with_coverage_gaps" if gaps else "complete"),
    }
    (args.output_dir / "run_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    build_report(args.output_dir, start, end)
    print(json.dumps(summary, indent=2), flush=True)
    return 2 if not ok or failures or (args.strict_coverage and gaps) else 0


if __name__ == "__main__":
    raise SystemExit(main())
