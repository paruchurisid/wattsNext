"""Stream county snapshots and construct observed utility outage events."""

import hashlib
import io
import re
import shutil
import zipfile
from pathlib import Path
import pandas as pd
from .config import FIPS, EIA_API_KEY
from .common import get, optional, write_csv

COLUMNS = [
    "outage_event_id",
    "source_dataset",
    "city_key",
    "fips_code",
    "county_name",
    "state",
    "utility_name",
    "start_timestamp_utc",
    "end_timestamp_utc",
    "duration_minutes",
    "peak_customers_out",
    "customer_hours_interrupted",
    "reported_cause",
    "record_type",
]


def normalize(frame, start, end):
    frame = frame.rename(
        columns={c: re.sub(r"[^a-z0-9]+", "_", c.lower()).strip("_") for c in frame}
    )
    aliases = {
        "fips_code": ["fips_code", "fips", "county_fips", "county_fips_code"],
        "timestamp_utc": [
            "timestamp_utc",
            "run_start_time",
            "timestamp",
            "time",
            "datetime",
            "date_time",
        ],
        "customers_out": [
            "customers_out",
            "sum",
            "outage_count",
            "customers_without_power",
        ],
    }
    for target, names in aliases.items():
        match = next((n for n in names if n in frame), None)
        if match is None:
            raise ValueError(
                f"Unsupported outage schema: missing {target}; columns={list(frame)}"
            )
        if match != target:
            frame = frame.rename(columns={match: target})
    frame["fips_code"] = (
        frame.fips_code.astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(5)
    )
    frame = frame[frame.fips_code.isin(FIPS)].copy()
    frame["timestamp_utc"] = pd.to_datetime(
        frame.timestamp_utc, utc=True, errors="coerce"
    )
    frame["customers_out"] = pd.to_numeric(frame.customers_out, errors="coerce")
    return frame[
        frame.timestamp_utc.ge(pd.Timestamp(start, tz="UTC"))
        & frame.timestamp_utc.lt(pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1))
    ][["fips_code", "timestamp_utc", "customers_out"]].dropna()


def read_chunks(handle, start, end):
    frames = []
    for f in pd.read_csv(handle, chunksize=100000, dtype=str):
        selected = normalize(f, start, end)
        if not selected.empty:
            frames.append(selected)
    return (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=["fips_code", "timestamp_utc", "customers_out"])
    )


def eagle(start, end):
    from concurrent.futures import ThreadPoolExecutor
    from . import common

    metadata = get("https://api.figshare.com/v2/articles/24237376").json()
    files = []
    for item in metadata["files"]:
        match = re.fullmatch(r"eaglei_outages_(20\d{2})\.csv(?:\.gz)?", item["name"])
        if (
            match
            and pd.Timestamp(start).year <= int(match[1]) <= pd.Timestamp(end).year
        ):
            files.append((int(match[1]), item))
    available = {year for year, _ in files}
    missing = sorted(
        set(range(pd.Timestamp(start).year, pd.Timestamp(end).year + 1)) - available
    )
    if missing:
        common.STATUS.append(
            {
                "source": "EAGLE-I coverage",
                "status": "coverage_gap",
                "missing_years": missing,
                "reason": "Years absent from publisher catalog",
            }
        )
    if not files:
        return pd.DataFrame()

    def fetch(item):
        year, info = item
        cache = (
            common.CACHE_ROOT / "eagle" / f"{year}-{info['id']}-{info['size']}.parquet"
        )
        if cache.exists():
            common.LOG.info("EAGLE-I %s: using filtered checkpoint", year)
            return pd.read_parquet(cache)
        common.LOG.info("EAGLE-I %s: streaming %.1f MB", year, info["size"] / 1e6)
        from .bulk import filtered_csv_ranges

        if (pd.Timestamp(end) - pd.Timestamp(start)).days < 32:
            common.LOG.info(
                "EAGLE-I %s: locating requested date window with HTTP ranges", year
            )
            return filtered_csv_ranges(
                info,
                year,
                common.CACHE_ROOT / "eagle",
                normalize,
                workers=4,
                block_size=1024 * 1024,
                window=(start, end),
            )

        frame = filtered_csv_ranges(info, year, common.CACHE_ROOT / "eagle", normalize)
        cache.parent.mkdir(parents=True, exist_ok=True)
        temp = cache.with_suffix(".tmp")
        frame.to_parquet(temp, index=False)
        temp.replace(cache)
        common.LOG.info(
            "EAGLE-I %s: checkpointed %s county snapshots", year, len(frame)
        )
        return frame

    # Only target-county rows survive each chunk, bounding memory and disk use.
    with ThreadPoolExecutor(max_workers=2) as pool:
        frames = list(pool.map(fetch, sorted(files)))
    frame = pd.concat(frames, ignore_index=True)
    return frame[
        frame.timestamp_utc.ge(pd.Timestamp(start, tz="UTC"))
        & frame.timestamp_utc.lt(pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1))
    ]


def oedi(start, end, outdir):
    from .common import CACHE_ROOT

    cache = CACHE_ROOT
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / "outage-v2.zip"
    if not target.exists():
        temp = target.with_suffix(".partial")
        try:
            response = get(
                "https://data.openei.org/files/6458/Outage%20Dataset%20v2.zip",
                stream=True,
            )
        except Exception:
            response = get(
                "https://data.openei.org/files/6458/Outage_Dataset_R1.zip", stream=True
            )
        with response, temp.open("wb") as output:
            for block in response.iter_content(1024 * 1024):
                output.write(block)
        temp.replace(target)
    frames = []
    with zipfile.ZipFile(target) as archive:
        for name in archive.namelist():
            years = re.findall(r"20\d{2}", name)
            if years and not any(
                pd.Timestamp(start).year <= int(y) <= pd.Timestamp(end).year
                for y in years
            ):
                continue
            if name.lower().endswith("_merged.csv"):
                with archive.open(name) as handle:
                    for f in pd.read_csv(handle, chunksize=100000, dtype={"fips": str}):
                        if "fips" not in f or "start_time" not in f:
                            raise ValueError(f"Unexpected OEDI event schema in {name}")
                        f["fips_code"] = f.fips.str.zfill(5)
                        f = f[f.fips_code.isin(FIPS)].copy()
                        dates = pd.to_datetime(f.start_time, errors="coerce")
                        f = f[
                            dates.ge(pd.Timestamp(start))
                            & dates.lt(pd.Timestamp(end) + pd.Timedelta(days=1))
                        ]
                        if len(f):
                            frames.append(f.assign(archive_member=name))
    events = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    events.to_csv(outdir / "oedi_correlated_events.csv", index=False)
    # These pre-aggregated records cannot reconstruct the requested raw threshold definition.
    from .common import STATUS

    STATUS.append(
        {
            "source": "OEDI event archive",
            "status": "context_only",
            "rows": len(events),
            "reason": "Pre-aggregated events retained in sidecar; no 15-minute snapshots",
        }
    )
    return pd.DataFrame()


def aggregate(frame, resolution="event"):
    if frame.empty:
        return pd.DataFrame(columns=COLUMNS)
    # Archives overlap: identical county/timestamp records must never be added together.
    conflicts = frame.groupby(["fips_code", "timestamp_utc"]).customers_out.nunique()
    if conflicts.gt(1).any():
        raise ValueError("Conflicting county snapshots across archives")
    frame = frame.drop_duplicates(["fips_code", "timestamp_utc"]).sort_values(
        ["fips_code", "timestamp_utc"]
    )
    rows = []
    for fips, county in frame.groupby("fips_code"):
        city = FIPS[fips]
        active = county[county.customers_out >= 100].copy()
        active["group"] = (
            active.timestamp_utc.diff().ne(pd.Timedelta(minutes=15)).cumsum()
        )
        groups = (
            [group for _, group in active.groupby("group")]
            if resolution == "event"
            else [county.iloc[[i]] for i in range(len(county))]
        )
        for group in groups:
            if resolution == "event" and len(group) < 2:
                continue
            begin = group.timestamp_utc.iloc[0]
            end = group.timestamp_utc.iloc[-1] + pd.Timedelta(minutes=15)
            rows.append(
                dict(
                    outage_event_id=hashlib.sha256(
                        f"{fips}:{begin.isoformat()}:{resolution}".encode()
                    ).hexdigest()[:24],
                    source_dataset=group.source_dataset.iloc[0],
                    city_key=city.city_key,
                    fips_code=fips,
                    county_name=city.counties[fips],
                    state=city.state,
                    utility_name=city.utility_name,
                    start_timestamp_utc=begin,
                    end_timestamp_utc=end,
                    duration_minutes=(end - begin).total_seconds() / 60,
                    peak_customers_out=group.customers_out.max(),
                    customer_hours_interrupted=group.customers_out.sum() / 4,
                    reported_cause="UNKNOWN",
                    record_type="ACTUAL_UTILITY_OUTAGE",
                    boundary_semantics="observed_15min_bins",
                    left_censored=begin == county.timestamp_utc.min(),
                    right_censored=end > county.timestamp_utc.max(),
                )
            )
    return pd.DataFrame(rows)


def disturbances(start, end, outdir):
    from .common import CACHE_ROOT

    cache = CACHE_ROOT
    cache.mkdir(exist_ok=True, parents=True)
    frames = []
    for year in range(pd.Timestamp(start).year, min(pd.Timestamp(end).year, 2025) + 1):
        ext = "xlsx" if year >= 2024 else "xls"
        url = f"https://doe417.energy.gov/summaries/{year}_Annual_Summary.{ext}"
        path = cache / f"OE417_{year}.{ext}"
        if not path.exists():
            path.write_bytes(get(url).content)
        raw = pd.read_excel(path, header=None)
        header = next(
            (
                i
                for i, row in raw.iterrows()
                if row.astype(str)
                .str.contains("Date Began|Date Event Began", case=False, regex=True)
                .any()
            ),
            None,
        )
        if header is None:
            raise ValueError(f"Unrecognized OE-417 header for {year}")
        f = pd.read_excel(path, header=header)
        f.columns = [re.sub(r"[^a-z0-9]+", "_", str(c).lower()).strip("_") for c in f]
        f = f.rename(
            columns={
                "date_event_began": "date_began",
                "time_event_began": "time_began",
                "date_of_restoration": "date_restored",
                "time_of_restoration": "time_restored",
                "number_of_customers_affected": "customers_affected",
            }
        )
        f["source_year"] = year
        f["source_url"] = url
        frames.append(f)
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    result.to_csv(outdir / "doe_disturbances.csv", index=False)
    if pd.Timestamp(end).year > 2025:
        from .common import STATUS

        STATUS.append(
            {
                "source": "DOE-417 coverage",
                "status": "coverage_gap",
                "missing_years": list(
                    range(
                        max(2026, pd.Timestamp(start).year), pd.Timestamp(end).year + 1
                    )
                ),
            }
        )
    # Region-wide counts stay in a sidecar: allocating them to a county invents observations.
    return result


def eia_pages(route, start, end, facets):
    rows = []
    offset = 0
    while True:
        params = {
            "api_key": EIA_API_KEY,
            "frequency": "hourly",
            "data[0]": "value",
            "start": start + "T00",
            "end": end + "T23",
            "length": 5000,
            "offset": offset,
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
            **facets,
        }
        response = get(
            "https://api.eia.gov/v2/electricity/rto/" + route + "/data/", params=params
        ).json()["response"]
        data = response["data"]
        rows.extend(data)
        offset += len(data)
        if offset >= int(response["total"]):
            break
        if not data:
            raise ValueError("EIA pagination ended before advertised total")
    return pd.DataFrame(rows)


def load_anomalies(actual, forecast):
    """Join ONLY equal geography and valid times; forecasts must predate valid time."""
    keys = ["subba", "timestamp_utc"]
    if actual.duplicated(keys).any() or forecast.duplicated(keys).any():
        raise ValueError("Duplicate sub-BA load/forecast keys")
    forecast = forecast.copy()
    forecast["timestamp_utc"] = pd.to_datetime(forecast.timestamp_utc, utc=True)
    forecast["issue_timestamp_utc"] = pd.to_datetime(
        forecast.issue_timestamp_utc, utc=True
    )
    if forecast.issue_timestamp_utc.ge(forecast.timestamp_utc).any():
        raise ValueError("Load forecast must be issued before its valid hour")
    merged = actual.merge(forecast, on=keys, how="left", validate="one_to_one")
    merged["load_drop_mw"] = merged.actual_mw - pd.to_numeric(
        merged.forecast_mw, errors="coerce"
    )
    return merged


def eia(start, end, outdir):
    from .common import STATUS
    import os

    if not EIA_API_KEY:
        STATUS.append(
            {"source": "EIA", "status": "skipped", "reason": "EIA_API_KEY unset"}
        )
        return pd.DataFrame()
    raw = eia_pages(
        "region-sub-ba-data", start, end, {"facets[subba][]": ["AEP", "CSWS"]}
    )
    if raw.empty:
        return raw
    frame = raw.rename(columns={"value": "actual_mw"})
    frame["timestamp_utc"] = pd.to_datetime(frame.period, utc=True)
    frame["actual_mw"] = pd.to_numeric(frame.actual_mw, errors="coerce")
    forecast_path = os.environ.get("EIA_SUBBA_FORECAST_CSV")
    if forecast_path:
        forecast = pd.read_csv(forecast_path)
        frame = load_anomalies(frame, forecast)
    else:
        frame["forecast_mw"] = float("nan")
        frame["load_drop_mw"] = float("nan")
        STATUS.append(
            {
                "source": "EIA sub-BA forecasts",
                "status": "coverage_gap",
                "reason": "EIA publishes sub-BA actual demand, but forecasts at BA geography; no sub-BA forecast supplied",
            }
        )
    frame.to_csv(outdir / "eia_subba_load.csv", index=False)
    ba = eia_pages(
        "region-data",
        start,
        end,
        {"facets[respondent][]": ["PJM", "SWPP"], "facets[type][]": ["D", "DF"]},
    )
    if len(ba):
        ba["value"] = pd.to_numeric(ba.value, errors="coerce")
        ba = (
            ba.pivot(index=["period", "respondent"], columns="type", values="value")
            .reset_index()
            .rename(columns={"D": "actual_mw", "DF": "forecast_mw"})
        )
        for col in ["actual_mw", "forecast_mw"]:
            if col not in ba:
                ba[col] = float("nan")
        ba["load_drop_mw"] = ba.actual_mw - ba.forecast_mw
        ba["timestamp_utc"] = pd.to_datetime(ba.period, utc=True)
        ba.to_csv(outdir / "eia_ba_load_anomalies.csv", index=False)
    return frame


def run(start, end, outdir, resolution="event", **kwargs):
    frames = []
    for name, fn in [
        ("EAGLE-I", lambda: eagle(start, end)),
        ("OEDI", lambda: oedi(start, end, outdir)),
    ]:
        frame = optional(name, fn)
        if not frame.empty:
            frames.append(frame.assign(source_dataset=name))
    doe = optional(
        "DOE OE-417 annual summaries", lambda: disturbances(start, end, outdir)
    )
    load = optional("EIA load", lambda: eia(start, end, outdir))
    result = (
        aggregate(pd.concat(frames, ignore_index=True), resolution)
        if frames
        else pd.DataFrame(columns=COLUMNS)
    )
    if (
        not doe.empty
        and not result.empty
        and {"date_began", "area_affected", "event_type"}.issubset(doe)
    ):
        state_names = {
            "VA": "Virginia",
            "OH": "Ohio",
            "WV": "West Virginia",
            "OK": "Oklahoma",
        }
        area = doe.area_affected.fillna("").str.replace(" ", "").str.lower()
        doe["parsed_date"] = pd.to_datetime(
            doe.date_began, errors="coerce", format="mixed"
        )
        for i, r in result.iterrows():
            # A report must name this county AND state. Multi-county totals are never copied.
            match = doe[
                area.str.contains(r.county_name.replace(" ", "").lower(), regex=False)
                & area.str.contains(
                    state_names[r.state].replace(" ", "").lower(), regex=False
                )
            ]
            dates = match.parsed_date
            local_start = (
                r.start_timestamp_utc.tz_convert(FIPS[r.fips_code].iana_tz)
                .tz_localize(None)
                .normalize()
            )
            match = match[dates.eq(local_start)]
            if len(match):
                result.loc[i, "reported_cause"] = (
                    "DOE_DATE_COUNTY_ASSOCIATION: "
                    + "; ".join(match.event_type.dropna().astype(str).unique())
                )
    if not result.empty:
        result["subba_load_drop_mw"] = float("nan")
        if not load.empty:
            for i, r in result.iterrows():
                selected = load[
                    load.subba.eq(FIPS[r.fips_code].subba)
                    & load.timestamp_utc.ge(r.start_timestamp_utc.floor("h"))
                    & load.timestamp_utc.lt(r.end_timestamp_utc)
                ]
                if len(selected):
                    result.loc[i, "subba_load_drop_mw"] = selected.load_drop_mw.min()
    hazard = Path(kwargs.get("hazard_path", outdir / "severe_weather_events.csv"))
    if hazard.exists() and not result.empty:
        storms = pd.read_csv(hazard, dtype={"fips_code": str})
        storms = storms[
            storms.record_type.eq("METEOROLOGICAL_HAZARD_AND_WEATHER_DAMAGE")
        ]
        storms["parsed_begin"] = pd.to_datetime(storms.begin_timestamp_utc, utc=True)
        storms["parsed_end"] = pd.to_datetime(storms.end_timestamp_utc, utc=True)
        for i, r in result.iterrows():
            match = storms[
                (storms.fips_code == r.fips_code)
                & (storms.parsed_begin <= r.end_timestamp_utc)
                & (storms.parsed_end >= r.start_timestamp_utc)
            ]
            if len(match) and result.loc[i, "reported_cause"] == "UNKNOWN":
                result.loc[i, "reported_cause"] = "TEMPORAL_ASSOCIATION: " + "; ".join(
                    sorted(set(match.event_type))
                )
    return write_csv(result, outdir / "power_outages.csv", COLUMNS)
