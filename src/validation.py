"""Dataset contracts and independently computed coverage reports."""

from pathlib import Path
import pandas as pd
from .config import FIPS

FILES = {
    "historical": (
        "historical_weather.csv",
        ["city_key", "fips_code", "asos_id", "ghcnd_id", "timestamp_utc", "temp_c"],
    ),
    "hazards": (
        "severe_weather_events.csv",
        [
            "city_key",
            "fips_code",
            "event_id",
            "begin_timestamp_utc",
            "end_timestamp_utc",
            "record_type",
        ],
    ),
    "outages": (
        "power_outages.csv",
        [
            "city_key",
            "fips_code",
            "outage_event_id",
            "start_timestamp_utc",
            "end_timestamp_utc",
            "peak_customers_out",
            "customer_hours_interrupted",
            "record_type",
        ],
    ),
    "forecasts": (
        "weather_forecast.csv",
        [
            "city_key",
            "fips_code",
            "forecast_source",
            "issue_timestamp_utc",
            "valid_timestamp_utc",
            "lead_time_hours",
        ],
    ),
}


def validate(name, frame, start, end):
    _, required = FILES[name]
    missing = sorted(set(required) - set(frame))
    if missing:
        raise ValueError(f"{name}: missing columns {missing}")
    keys = ["city_key", "fips_code"]
    if frame[keys].isna().any().any():
        raise ValueError(f"{name}: missing county/city join key")
    for city, fips in frame[keys].drop_duplicates().itertuples(index=False, name=None):
        if fips not in FIPS or FIPS[fips].city_key != city:
            raise ValueError(f"{name}: inconsistent city/FIPS mapping: {city}/{fips}")
    times = [
        c
        for c in required
        if c.endswith("timestamp_utc") and c != "issue_timestamp_utc"
    ]
    for c in times:
        if pd.to_datetime(frame[c], utc=True, errors="coerce").isna().any():
            raise ValueError(f"{name}: missing timestamp join key {c}")
    if name == "historical":
        if frame.duplicated(["fips_code", "timestamp_utc"]).any():
            raise ValueError("Duplicate county/hour weather grid")
        expected = pd.date_range(
            start,
            pd.Timestamp(end) + pd.Timedelta(days=1),
            freq="h",
            inclusive="left",
            tz="UTC",
        )
        for fips in FIPS:
            actual = pd.DatetimeIndex(
                pd.to_datetime(
                    frame.loc[frame.fips_code.eq(fips), "timestamp_utc"], utc=True
                )
            )
            if not actual.sort_values().equals(expected):
                raise ValueError(f"Incomplete hourly weather grid for {fips}")
    if name == "outages" and len(frame):
        if not frame.record_type.eq("ACTUAL_UTILITY_OUTAGE").all():
            raise ValueError("Outage table includes a non-utility observation")
        if frame.outage_event_id.duplicated().any():
            raise ValueError("Duplicate outage event IDs")
        begin = pd.to_datetime(frame.start_timestamp_utc, utc=True)
        finish = pd.to_datetime(frame.end_timestamp_utc, utc=True)
        if finish.le(begin).any():
            raise ValueError("Outage end must follow start")
        if (
            (frame[["peak_customers_out", "customer_hours_interrupted"]] < 0)
            .any()
            .any()
        ):
            raise ValueError("Negative outage measurements")
    if name == "forecasts" and len(frame):
        issue = pd.to_datetime(frame.issue_timestamp_utc, utc=True)
        valid = pd.to_datetime(frame.valid_timestamp_utc, utc=True)
        known = issue.notna()
        difference = (valid[known] - issue[known]).dt.total_seconds() / 3600
        if (
            difference.lt(0).any()
            or ((difference - frame.loc[known, "lead_time_hours"]).abs() > 1e-6).any()
        ):
            raise ValueError(
                "Forecast lead time is inconsistent with issue/valid times"
            )
    return {
        "rows": len(frame),
        "missing_join_keys": 0,
        "counties_present": sorted(frame.fips_code.unique().tolist()),
        "requested_start": start,
        "requested_end": end,
        "timestamps": {
            c: {
                "min": str(frame[c].min()) if len(frame) else None,
                "max": str(frame[c].max()) if len(frame) else None,
            }
            for c in times
        },
        "nonnull_counts": {c: int(n) for c, n in frame.count().items()},
    }


def validate_directory(directory, start, end):
    report = {}
    for name, (filename, _) in FILES.items():
        frame = pd.read_csv(Path(directory) / filename, dtype={"fips_code": str})
        report[name] = validate(name, frame, start, end)
    return report
