"""Meteorological hazards and weather damage, never utility outage counts."""

import io
import re
from datetime import timezone, timedelta
import pandas as pd
from .config import CITIES
from .common import get, optional, write_csv, chunks, download

COLUMNS = [
    "event_id",
    "city_key",
    "fips_code",
    "begin_timestamp_utc",
    "end_timestamp_utc",
    "record_type",
    "source_dataset",
    "event_type",
    "damage_property_usd",
    "damage_crops_usd",
    "gage_height_ft",
    "discharge_cfs",
]


def damage(value):
    if pd.isna(value) or str(value).strip() == "":
        return float("nan")
    m = re.fullmatch(r"\s*([\d.]+)\s*([KMB]?)\s*", str(value), re.I)
    return (
        float(m[1]) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m[2].upper()]
        if m
        else float("nan")
    )


def storm_time(value, zone):
    m = re.fullmatch(r"(?:EST|CST|MST|PST|AST|HST)([+-]\d+)", str(zone))
    if not m:
        raise ValueError(f"Unknown Storm Events timezone: {zone}")
    return (
        pd.to_datetime(value, format="%d-%b-%y %H:%M:%S")
        .tz_localize(timezone(timedelta(hours=int(m[1]))))
        .tz_convert("UTC")
    )


def county_zones(city):
    # Official many-to-many zone/county correlation, including split counties.
    table = get(
        "https://www.weather.gov/source/gis/Shapefiles/County/bp16ap26.dbx"
    ).text
    result = {fips: set() for fips in city.counties}
    for line in table.splitlines():
        fields = line.split("|")
        if len(fields) >= 7 and fields[6] in result:
            result[fields[6]].add(fields[0] + "Z" + fields[1].zfill(3))
    if any(not zones for zones in result.values()):
        raise ValueError("County missing from NOAA zone correlation")
    return result


def storms(start, end):
    listing = get("https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/").text
    rows = []
    zone_maps = {
        c.city_key: optional(
            "NWS county zones " + c.city_key, lambda c=c: county_zones(c)
        )
        for c in CITIES
    }
    for year in range(pd.Timestamp(start).year, pd.Timestamp(end).year + 1):
        names = sorted(
            set(
                re.findall(
                    r"StormEvents_details-ftp_v1\.0_d" + str(year) + r"_c\d+\.csv\.gz",
                    listing,
                )
            )
        )
        from . import common

        if not names:
            common.STATUS.append(
                {
                    "source": "NOAA Storm Events coverage",
                    "status": "coverage_gap",
                    "missing_year": year,
                }
            )
            continue
        common.LOG.info("NOAA Storm Events %s: processing official annual file", year)
        path = download(
            "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/" + names[-1],
            common.CACHE_ROOT / "storms" / names[-1],
        )
        for frame in pd.read_csv(
            path,
            compression="gzip",
            chunksize=50000,
            dtype={"STATE_FIPS": str, "CZ_FIPS": str},
            low_memory=False,
        ):
            frame = frame[frame.STATE_FIPS.str.zfill(2).isin(["51", "39", "54", "40"])]
            for _, r in frame.iterrows():
                for city in CITIES:
                    zones = zone_maps[city.city_key]
                    for fips in city.counties:
                        county = (
                            r.CZ_TYPE == "C"
                            and str(r.STATE_FIPS).zfill(2) + str(r.CZ_FIPS).zfill(3)
                            == fips
                        )
                        # The original event's named zone supplies historical geography.
                        token = (
                            city.counties[fips]
                            .replace(" County", "")
                            .replace(" City", "")
                            .upper()
                        )
                        historical_zone = (
                            r.CZ_TYPE == "Z"
                            and str(r.STATE_FIPS).zfill(2) == fips[:2]
                            and str(r.WFO) == city.wfo_grid.split("/")[0]
                            and re.search(
                                r"\b" + re.escape(token) + r"\b", str(r.CZ_NAME).upper()
                            )
                            is not None
                        )
                        current_zone = (
                            r.CZ_TYPE == "Z"
                            and year >= 2026
                            and isinstance(zones, dict)
                            and city.state + "Z" + str(r.CZ_FIPS).zfill(3)
                            in zones.get(fips, set())
                        )
                        zone = historical_zone or current_zone
                        if not (county or zone):
                            continue
                        begin = storm_time(r.BEGIN_DATE_TIME, r.CZ_TIMEZONE)
                        finish = storm_time(r.END_DATE_TIME, r.CZ_TIMEZONE)
                        if finish < pd.Timestamp(
                            start, tz="UTC"
                        ) or begin >= pd.Timestamp(end, tz="UTC") + pd.Timedelta(
                            days=1
                        ):
                            continue
                        rows.append(
                            dict(
                                event_id=str(r.EVENT_ID),
                                city_key=city.city_key,
                                fips_code=fips,
                                begin_timestamp_utc=begin,
                                end_timestamp_utc=finish,
                                event_type=r.EVENT_TYPE,
                                damage_property_usd=damage(r.DAMAGE_PROPERTY),
                                damage_crops_usd=damage(r.DAMAGE_CROPS),
                                record_type="METEOROLOGICAL_HAZARD_AND_WEATHER_DAMAGE",
                                source_dataset="NOAA_STORM_EVENTS",
                                geographic_match="county"
                                if county
                                else (
                                    "historical_event_zone_name"
                                    if historical_zone
                                    else "current_forecast_zone_crosswalk"
                                ),
                                source_zone_id=str(r.CZ_FIPS).zfill(3),
                                source_zone_name=r.CZ_NAME,
                            )
                        )
    return pd.DataFrame(rows)


def flood_metadata(city):
    j = get("https://api.water.noaa.gov/nwps/v1/gauges/" + city.usgs_site).json()
    if j.get("usgsId") != city.usgs_site:
        raise ValueError("NWPS/USGS gage mismatch")
    flood = j.get("flood", {})
    if flood.get("stageUnits") != "ft":
        raise ValueError("NWPS flood-stage units are not feet")
    categories = flood.get("categories", {})
    return {
        name: category.get("stage")
        for name, category in categories.items()
        if category.get("stage") is not None and category["stage"] > -9999
    }


def rivers(start, end):
    from . import common

    frames = []
    metadata = {
        c.usgs_site: optional(
            "NWPS threshold " + c.usgs_site, lambda c=c: flood_metadata(c)
        )
        for c in CITIES
    }
    for a, b in chunks(start, end):
        common.LOG.info("USGS: hourly peaks %s through %s", a, b)
        j = get(
            "https://waterservices.usgs.gov/nwis/iv/",
            params=dict(
                format="json",
                sites=",".join(c.usgs_site for c in CITIES),
                parameterCd="00060,00065",
                startDT=a + "T00:00:00Z",
                endDT=b + "T23:59:59Z",
                siteStatus="all",
            ),
        ).json()
        pieces = []
        for series in j["value"]["timeSeries"]:
            site = series["sourceInfo"]["siteCode"][0]["value"]
            code = series["variable"]["variableCode"][0]["value"]
            nodata = float(series["variable"].get("noDataValue", -999999))
            vals = [
                v
                for group in series["values"]
                for v in group["value"]
                if float(v["value"]) != nodata
            ]
            if not vals:
                continue
            f = pd.DataFrame(vals)
            f["timestamp"] = pd.to_datetime(f.dateTime, utc=True)
            f["value"] = pd.to_numeric(f.value)
            hourly = (
                f.set_index("timestamp")
                .value.resample("h")
                .max()
                .dropna()
                .rename("discharge_cfs" if code == "00060" else "gage_height_ft")
                .reset_index()
            )
            hourly["usgs_site"] = site
            pieces.append(hourly)
        if not pieces:
            continue
        f = (
            pd.concat(pieces, ignore_index=True)
            .groupby(["usgs_site", "timestamp"], as_index=False)
            .max()
        )
        for city in CITIES:
            g = f[f.usgs_site.eq(city.usgs_site)].copy()
            if g.empty:
                continue
            g = g.rename(columns={"timestamp": "begin_timestamp_utc"})
            g["end_timestamp_utc"] = g.begin_timestamp_utc + pd.Timedelta(hours=1)
            g["event_id"] = (
                "USGS-" + city.usgs_site + "-" + g.begin_timestamp_utc.astype(str)
            )
            g["city_key"] = city.city_key
            g["record_type"] = "RIVER_OBSERVATION"
            g["source_dataset"] = "USGS_IV"
            thresholds = metadata[city.usgs_site]
            g["is_river_flooding"] = pd.Series(pd.NA, index=g.index, dtype="boolean")
            g["flood_category"] = "UNKNOWN"
            g["threshold_reference"] = (
                "current_NWPS_metadata_not_historical_datum_verification"
            )
            if (
                isinstance(thresholds, dict)
                and "minor" in thresholds
                and "gage_height_ft" in g
            ):
                g["flood_stage_ft"] = thresholds["minor"]
                g["is_river_flooding"] = (
                    g.gage_height_ft.ge(thresholds["minor"])
                    .astype("boolean")
                    .mask(g.gage_height_ft.isna())
                )
                g.loc[g.gage_height_ft.notna(), "flood_category"] = "BELOW_FLOOD"
                for category in ["minor", "moderate", "major"]:
                    if category in thresholds:
                        g.loc[
                            g.gage_height_ft.ge(thresholds[category]), "flood_category"
                        ] = category.upper()
            for fips in city.counties:
                frames.append(g.assign(fips_code=fips))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def run(start, end, outdir, **kwargs):
    frames = [
        optional("NOAA Storm Events", lambda: storms(start, end)),
        optional("USGS IV", lambda: rivers(start, end)),
    ]
    return write_csv(
        pd.concat(frames, ignore_index=True),
        outdir / "severe_weather_events.csv",
        COLUMNS,
    )
