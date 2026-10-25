"""Live forecasts and archived fixed-lead predictions with explicit issue semantics."""

import re
import pandas as pd
from .config import CITIES
from .common import get, optional, chunks, write_csv
from .fetch_historical_weather import RENAME, VARS

COLUMNS = [
    "forecast_source",
    "issue_timestamp_utc",
    "valid_timestamp_utc",
    "lead_time_hours",
    "city_key",
    "fips_code",
    "lat",
    "lon",
    "temp_c",
]


def nws(city):
    try:
        j = get(
            "https://api.weather.gov/gridpoints/" + city.wfo_grid + "/forecast/hourly"
        ).json()
    except Exception:
        point = get(f"https://api.weather.gov/points/{city.lat},{city.lon}").json()
        j = get(point["properties"]["forecastHourly"]).json()
    issue = pd.Timestamp(j["properties"]["updateTime"])
    rows = []
    for p in j["properties"]["periods"]:
        speed = [float(v) for v in re.findall(r"\d+(?:\.\d+)?", p["windSpeed"])]
        rows.append(
            dict(
                valid_timestamp_utc=pd.Timestamp(p["startTime"]).tz_convert("UTC"),
                issue_timestamp_utc=issue,
                temp_c=(p["temperature"] - 32) * 5 / 9
                if p["temperatureUnit"] == "F"
                else p["temperature"],
                wind_speed_kmh=max(speed) * 1.609344 if speed else None,
                short_forecast=p["shortForecast"],
                precipitation_probability_pct=p.get(
                    "probabilityOfPrecipitation", {}
                ).get("value"),
                forecast_source="NWS_NDFD",
                issue_time_semantics="provider_update_time",
            )
        )
    return pd.DataFrame(rows).query("valid_timestamp_utc >= issue_timestamp_utc")


def meteo(city, start, end, archived=False):
    frames = []
    windows = (
        chunks(max(start, "2024-01-01"), end, 366)
        if archived and end >= "2024-01-01"
        else ([] if archived else [(None, None)])
    )
    for a, b in windows:
        p = dict(latitude=city.lat, longitude=city.lon, timezone="UTC")
        if archived:
            p.update(
                start_date=a,
                end_date=b,
                hourly="temperature_2m_previous_day1,wind_gusts_10m_previous_day1,precipitation_previous_day1",
            )
        else:
            p.update(hourly=VARS + ",freezing_level_height", forecast_days=16)
        j = get(
            "https://"
            + ("previous-runs-api" if archived else "api")
            + ".open-meteo.com/v1/forecast",
            params=p,
        ).json()
        f = pd.DataFrame(j["hourly"])
        f = f.rename(
            columns={
                "time": "valid_timestamp_utc",
                **{
                    x: RENAME.get(
                        x.replace("_previous_day1", ""), x.replace("_previous_day1", "")
                    )
                    for x in f
                    if x != "time"
                },
            }
        )
        f["valid_timestamp_utc"] = pd.to_datetime(f.valid_timestamp_utc, utc=True)
        # Previous Runs supplies fixed offsets, not actual model initialization timestamps.
        f["issue_timestamp_utc"] = (
            f.valid_timestamp_utc - pd.Timedelta(hours=24) if archived else pd.NaT
        )
        f["issue_time_semantics"] = (
            "nominal_fixed_lead_24h" if archived else "initialization_unavailable"
        )
        f["retrieved_timestamp_utc"] = pd.Timestamp.now(tz="UTC")
        f["forecast_source"] = (
            "OPEN_METEO_ARCHIVED_DAY1" if archived else "OPEN_METEO_LIVE"
        )
        f = f.rename(columns={"freezing_level_height": "freezing_level_height_m"})
        frames.append(f)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def single_run(city, initialization):
    issue = pd.Timestamp(initialization, tz="UTC")
    j = get(
        "https://single-runs-api.open-meteo.com/v1/forecast",
        params=dict(
            latitude=city.lat,
            longitude=city.lon,
            models="ecmwf_ifs",
            run=issue.strftime("%Y-%m-%dT%H:%M"),
            hourly=VARS,
            forecast_days=2,
            timezone="UTC",
        ),
    ).json()
    frame = pd.DataFrame(j["hourly"]).rename(
        columns={"time": "valid_timestamp_utc", **RENAME}
    )
    frame["valid_timestamp_utc"] = pd.to_datetime(frame.valid_timestamp_utc, utc=True)
    frame["issue_timestamp_utc"] = issue
    frame["forecast_source"] = "OPEN_METEO_ARCHIVED_RUN"
    frame["forecast_model"] = "ecmwf_ifs"
    frame["issue_time_semantics"] = "model_initialization_not_publication"
    frame["retrieved_timestamp_utc"] = pd.Timestamp.now(tz="UTC")
    return frame


def run(start, end, outdir, **kwargs):
    from .common import STATUS

    if start < "2024-01-01":
        STATUS.append(
            {
                "source": "Open-Meteo Previous Runs coverage",
                "status": "coverage_gap",
                "start": start,
                "end": min(end, "2023-12-31"),
                "reason": "Publisher fixed-lead archive starts in 2024",
            }
        )
    runs = kwargs.get("forecast_runs", [])
    if not runs and end >= "2024-03-14":
        # Monthly exact-run samples complement the dense, hourly fixed-lead archive.
        first = max(pd.Timestamp(start), pd.Timestamp("2024-03-14"))
        runs = [
            d.strftime("%Y-%m-%dT00:00")
            for d in pd.date_range(first, pd.Timestamp(end), freq="MS")
        ]
        if not runs:
            runs = [first.strftime("%Y-%m-%dT00:00")]
    frames = []
    for city in CITIES:
        sources = [
            ("NWS", lambda: nws(city)),
            ("Open-Meteo live", lambda: meteo(city, start, end)),
            ("Open-Meteo previous runs", lambda: meteo(city, start, end, True)),
        ]
        sources.extend(
            (
                f"Open-Meteo exact run {initialization}",
                lambda initialization=initialization: single_run(city, initialization),
            )
            for initialization in runs
        )
        for source, fn in sources:
            f = optional(source + " " + city.city_key, fn)
            if f.empty:
                continue
            f["lead_time_hours"] = (
                pd.to_datetime(f.valid_timestamp_utc, utc=True)
                - pd.to_datetime(f.issue_timestamp_utc, utc=True)
            ).dt.total_seconds() / 3600
            f["city_key"] = city.city_key
            f["lat"] = city.lat
            f["lon"] = city.lon
            for fips in city.counties:
                frames.append(f.assign(fips_code=fips))
    return write_csv(
        pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(),
        outdir / "weather_forecast.csv",
        COLUMNS,
    )
