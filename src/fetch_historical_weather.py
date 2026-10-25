"""Airport observations, reanalysis and daily GHCND measurements."""

import time
import numpy as np
import pandas as pd
from .config import CITIES, fahrenheit_to_celsius
from .common import get, optional, csv_response, chunks, write_csv

VARS = "temperature_2m,precipitation,rain,snowfall,snow_depth,weather_code,wind_speed_10m,wind_gusts_10m"
RENAME = dict(
    zip(
        VARS.split(","),
        [
            "temp_c",
            "precipitation_mm",
            "rain_mm",
            "snowfall_cm",
            "snow_depth_m",
            "weather_code",
            "wind_speed_kmh",
            "wind_gust_kmh",
        ],
    )
)
IEM = "tmpf,dwpf,relh,drct,sknt,gust,p01i,wxcodes,ice_accretion_1hr,ice_accretion_3hr,ice_accretion_6hr,peak_wind_gust,snowdepth".split(
    ","
)


def circular_degrees(values):
    radians=np.deg2rad(values.dropna())
    if not len(radians): return float('nan')
    return float(np.rad2deg(np.arctan2(np.sin(radians).mean(),np.cos(radians).mean()))%360)


def archive(city, start, end):
    frames = []
    for a, b in chunks(start, end, 366):
        j = get(
            "https://archive-api.open-meteo.com/v1/archive",
            params=dict(
                latitude=city.lat,
                longitude=city.lon,
                start_date=a,
                end_date=b,
                hourly=VARS,
                timezone="UTC",
            ),
        ).json()
        frames.append(
            pd.DataFrame(j["hourly"]).rename(
                columns={"time": "timestamp_utc", **RENAME}
            )
        )
    frame = pd.concat(frames, ignore_index=True)
    frame.timestamp_utc = pd.to_datetime(frame.timestamp_utc, utc=True)
    return frame


def asos(city, start, end):
    frames = []
    for year in range(pd.Timestamp(start).year, pd.Timestamp(end).year + 1):
        a = max(pd.Timestamp(start), pd.Timestamp(year, 1, 1))
        b = min(pd.Timestamp(end) + pd.Timedelta(days=1), pd.Timestamp(year + 1, 1, 1))
        p = dict(
            station=city.asos_id[1:],
            data=IEM,
            tz="UTC",
            format="onlycomma",
            latlon="yes",
            missing="M",
            trace="0.0001",
            report_type=[3, 4],
            year1=a.year,
            month1=a.month,
            day1=a.day,
            year2=b.year,
            month2=b.month,
            day2=b.day,
        )
        f = csv_response(
            get("https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py", params=p),
            na_values=["M"],
            comment="#",
        )
        f["timestamp_utc"] = pd.to_datetime(f.valid, utc=True).dt.floor("h")
        codes = f.wxcodes.fillna("")
        for flag, pattern in [
            ("is_freezing_rain", "FZRA|FZDZ"),
            ("is_snow", "SN"),
            ("is_ice_pellets", "PL"),
            ("is_thunderstorm", "TS"),
        ]:
            f[flag] = codes.str.contains(pattern).astype(int)
        names = {
            "tmpf": "asos_temp_f",
            "dwpf": "dewpoint_f",
            "relh": "relative_humidity_pct",
            "drct": "wind_direction_deg",
            "sknt": "wind_speed_knots",
            "gust": "wind_gust_knots",
            "p01i": "precipitation_1hr_in",
            "snowdepth": "asos_snow_depth_in",
            "peak_wind_gust": "peak_wind_gust_knots",
            **{x: x + "_in" for x in IEM if x.startswith("ice_")},
        }
        f = f.rename(columns=names)
        numeric = list(names.values()) + [x for x in f if x.startswith("is_")]
        for col in numeric:
            f[col] = pd.to_numeric(f[col], errors="coerce")
        # Precipitation and ice are rolling accumulations: maxima avoid double counting METAR/SPECI.
        agg = {
            c: (
                "max"
                if any(s in c for s in ["gust", "ice_", "precipitation", "is_"])
                else "mean"
            )
            for c in numeric
        }
        agg["wind_direction_deg"]=circular_degrees
        frames.append(f.groupby("timestamp_utc").agg(agg).reset_index())
        time.sleep(1)
    f = pd.concat(frames).drop_duplicates("timestamp_utc")
    f["asos_temp_c"] = fahrenheit_to_celsius(f.pop("asos_temp_f"))
    return f


def daily(city, start, end):
    start = (pd.Timestamp(start) - pd.Timedelta(days=1)).date().isoformat()
    f = csv_response(
        get(
            "https://www.ncei.noaa.gov/access/services/data/v1",
            params=dict(
                dataset="daily-summaries",
                stations=city.ghcnd_id,
                startDate=start,
                endDate=end,
                dataTypes="TMAX,TMIN,PRCP,SNOW,SNWD,AWND,WSF2,WSF5,WT03,WT04,WT06",
                format="csv",
                units="standard",
            ),
        )
    )
    f["local_date"] = f.DATE
    return f[["local_date"] + [c for c in ["SNOW", "SNWD"] if c in f]].rename(
        columns={"SNOW": "ghcnd_snowfall_in", "SNWD": "ghcnd_snow_depth_in"}
    )


def run(start, end, outdir, **kwargs):
    frames = []
    for city in CITIES:
        base = optional(
            "Open-Meteo archive " + city.city_key, lambda: archive(city, start, end)
        )
        if base.empty:
            continue
        obs = optional("IEM " + city.city_key, lambda: asos(city, start, end))
        if not obs.empty:
            base = base.merge(
                obs, on="timestamp_utc", how="left", validate="one_to_one"
            )
        base["local_date"] = base.timestamp_utc.dt.tz_convert(city.iana_tz).dt.strftime(
            "%Y-%m-%d"
        )
        snow = optional("GHCND " + city.city_key, lambda: daily(city, start, end))
        if not snow.empty:
            base = base.merge(snow, on="local_date", how="left", validate="many_to_one")
        base["city_key"] = city.city_key
        base["asos_id"] = city.asos_id
        base["ghcnd_id"] = city.ghcnd_id
        base["source_dataset"] = "OPEN_METEO_REANALYSIS+IEM+GHCND"
        for fips in city.counties:
            frames.append(base.assign(fips_code=fips))
    return write_csv(
        pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(),
        outdir / "historical_weather.csv",
        ["timestamp_utc", "city_key", "fips_code", "asos_id", "ghcnd_id", "temp_c"],
    )
