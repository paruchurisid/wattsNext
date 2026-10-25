"""Small, portable audit artifact derived from the four actual CSV products."""

from pathlib import Path
import hashlib
import pandas as pd
from .validation import FILES
from .common import atomic_json


def build_report(directory, start, end):
    directory = Path(directory)
    rows = []
    artifacts = {}
    for name, (filename, required) in FILES.items():
        path = directory / filename
        if not path.exists():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        artifacts[filename] = {
            "sha256": digest.hexdigest(),
            "bytes": path.stat().st_size,
        }
        timestamp = next(
            c
            for c in required
            if c.endswith("timestamp_utc") and c != "issue_timestamp_utc"
        )
        source_column = "forecast_source" if name == "forecasts" else "source_dataset"
        for chunk in pd.read_csv(
            path,
            chunksize=100000,
            dtype={"fips_code": str},
            usecols=["city_key", "fips_code", timestamp, source_column],
        ):
            chunk["year"] = pd.to_datetime(chunk[timestamp], utc=True).dt.year
            chunk["source"] = chunk[source_column]
            grouped = (
                chunk.groupby(["source", "city_key", "fips_code", "year"])
                .size()
                .rename("rows")
                .reset_index()
            )
            grouped["dataset"] = name
            rows.append(grouped)
    if rows:
        counts = (
            pd.concat(rows, ignore_index=True)
            .groupby(
                ["dataset", "source", "city_key", "fips_code", "year"], as_index=False
            )["rows"]
            .sum()
        )
    else:
        counts = pd.DataFrame(
            columns=["dataset", "source", "city_key", "fips_code", "year", "rows"]
        )
    counts.to_csv(directory / "coverage_by_county_year.csv", index=False)
    atomic_json(directory / "artifact_checksums.json", artifacts)
    lines = [
        "# County data product audit",
        "",
        f"Requested observations: {start} through {end} UTC.",
        "",
        "| Product | Actual rows | Size (MB) |",
        "| --- | ---: | ---: |",
    ]
    for name, (filename, _) in FILES.items():
        if filename in artifacts:
            lines.append(
                f"| {filename} | {int(counts.loc[counts.dataset.eq(name), 'rows'].sum()):,} | {artifacts[filename]['bytes'] / 1e6:.1f} |"
            )
    lines.extend(
        [
            "",
            "All rows in this audit are read from the output CSVs. Checksums identify the exact files audited.",
            "",
            "See `validation_summary.json` for join-key and hourly-grid validation, `ingestion_status.json` for source failures and publication gaps, and `coverage_by_county_year.csv` for county/year counts.",
            "",
            "An absent outage observation is unknown, never a verified zero. Forecast rows mix source-specific issue semantics; exact model initialization is not publication time. River threshold comparisons use current metadata, not a verified historical datum reconstruction.",
            "",
            "A successful schema audit does not assert that an unpublished source year exists.",
        ]
    )
    (directory / "data-quality.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return artifacts
