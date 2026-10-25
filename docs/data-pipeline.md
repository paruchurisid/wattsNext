# County weather/outage data product

This product fetches real observations for five county FIPS codes mapped to four
airport stations: Roanoke City 51770 and Roanoke County 51161 (KROA), Franklin OH
39049 (KCMH), Kanawha WV 54039 (KCRW), and Tulsa OK 40143 (KTUL). `src/config.py`
is the canonical geography. No production adapter generates synthetic records.

## Install and run

Python 3.13 is the workspace's supported runtime. Dependencies are pinned in
`requirements-pipeline.txt`; `requirements.txt` and `requirements-dev.txt` include
that lock. The application remains independently runnable.

```powershell
uv venv .venv-pipeline
uv pip install --python .venv-pipeline/Scripts/python.exe -r requirements-pipeline.txt
Copy-Item .env.example .env
.\.venv-pipeline\Scripts\python.exe run_all.py --smoke-test
.\.venv-pipeline\Scripts\python.exe run_all.py --start-year 2015 --end-year 2026
```

The smoke test selects January 1–7 of the newest outage archive year inside the
requested range. It uses a common published year rather than insisting on
unpublished current-year outage observations. All four products must return real
sample rows, pass schema checks, and have zero missing county/city/timestamp join
keys. Samples and their reports live under `data/smoke/`. Live forecasts always
refer to upcoming hours; the archived sample covers the requested historic week.
A regular run performs this smoke test first and then starts the full backfill.

```powershell
# Resume from successful HTTP, annual and byte-range checkpoints:
.\.venv-pipeline\Scripts\python.exe run_all.py --skip-smoke
# Selective repair or refresh:
.\.venv-pipeline\Scripts\python.exe run_all.py --skip-smoke --pipelines outages
# A precise date range:
.\.venv-pipeline\Scripts\python.exe run_all.py --start-date 2025-01-01 --end-date 2025-01-07
# Preserve the observed 15-minute outage snapshots instead of constructing events:
.\.venv-pipeline\Scripts\python.exe run_all.py --resolution 15min
# Inspect durable outage transfer progress without network access:
.\.venv-pipeline\Scripts\python.exe run_all.py --progress
# Verify existing outputs without contacting any source:
.\.venv-pipeline\Scripts\python.exe run_all.py --validate-only
# Treat publisher coverage gaps as failures:
.\.venv-pipeline\Scripts\python.exe run_all.py --strict-coverage
# Add an exact archived initialization to the standard forecast products:
.\.venv-pipeline\Scripts\python.exe run_all.py --skip-smoke --pipelines forecasts --forecast-runs 2025-01-01T00:00
```

`--output-dir` changes the destination. End dates are clipped to yesterday UTC;
future observations are never filled. The required outputs are:

1. `data/historical_weather.csv`
2. `data/severe_weather_events.csv`
3. `data/power_outages.csv`
4. `data/weather_forecast.csv`

The runner validates each staged file before replacing a previous good product.
`ingestion_status.json` records source success, download errors, skips and known
coverage gaps. `validation_summary.json` reports counts, county coverage, date
bounds and non-null measurements. `reports/PIPELINE.json` preserves each
pipeline's validation and source statuses. `data-quality.md`,
`coverage_by_county_year.csv`, and `artifact_checksums.json` provide a portable
audit and SHA-256 identities for the exact CSVs validated. `run_summary.json` reports `complete`,
`complete_with_coverage_gaps`, or `failed`. Exit 2 means an execution/validation
failure, or a publisher coverage gap when `--strict-coverage` is enabled. Known
publisher limitations do not prevent the available historical backfill.

## Credentials and source behavior

`NOAA_CDO_TOKEN` is documented but unnecessary for NCEI Access Data Service.
`EIA_API_KEY` enables optional load enrichment. `NWS_USER_AGENT` should identify
the application and a real contact. `.env` is loaded; the application's
`.env.local` is not read by this product. API keys are redacted from source errors.

Every HTTP request has connection/read timeouts and retries for transient
failures and rate limiting. Bounded historical responses are cached for 24 hours;
live forecasts are fetched fresh. Small annual NOAA files are cached. EAGLE-I
CSV exports are read with bounded HTTP byte ranges; complete CSV records are
retained exactly once across range boundaries. Each range is filtered to the
five counties and checkpointed as Parquet. Only small county subsets persist,
not the national raw CSVs. Annual checkpoints are keyed by publisher file ID
and size. A publisher revision therefore cannot silently reuse an older version.
The complete national transfer is roughly 12 GB before county filtering and can
take substantial time. Completed ranges survive interruption. Default concurrency
is eight range requests globally, with up to four annual files prefetched;
`EAGLE_RANGE_WORKERS=1..32` adjusts the global bound for bandwidth and memory.
The shared pool continues transferring while a particular year waits for a slow
range. `--progress` reports durable checkpoints, excluding bytes in flight. Short date ranges use conservatively
padded binary searches over the publisher's time-ordered CSV export, then filter
the exact requested dates. The downloader checks timestamp ordering at probes
and validates returned `Content-Range` and byte counts.

The OEDI v2 URL supplied in the original specification returned 404. The adapter
falls back to the current official submission's `Outage_Dataset_R1.zip`. Its
pre-aggregated event table is county/date filtered into
`oedi_correlated_events.csv`; its aggregation cannot reconstruct the requested
100-customer snapshot definition. It is kept as context rather than mixed into
the primary threshold-defined events. The old DOE hostname no longer resolves;
annual XLS/XLSX summaries now come from `doe417.energy.gov/summaries/`.
`doe_disturbances.csv` preserves the reports without allocating region-wide
customer totals to counties.

## Data dictionary

Read FIPS as strings, for example `pd.read_csv(path, dtype={'fips_code': str})`.
Timestamps have UTC offsets. Blank measurements mean missing, never zero.
`city_key` and five-digit `fips_code` are present in every primary file. Roanoke
weather and gage measurements are intentionally replicated for both counties;
outage customers remain separate. These replicated weather rows are not
independent observations.

### Historical weather: one row per county/hour

Keys: `city_key`, `fips_code`, `timestamp_utc`, `asos_id`, `ghcnd_id`.

| Fields | Units/source |
| --- | --- |
| `temp_c`, `precipitation_mm`, `rain_mm` | Open-Meteo reanalysis, Celsius/mm |
| `snowfall_cm`, `snow_depth_m` | Reanalysis, cm/m |
| `weather_code`, `wind_speed_kmh`, `wind_gust_kmh` | WMO weather code; km/h |
| `asos_temp_c`, `dewpoint_f`, `relative_humidity_pct` | IEM observations; Celsius/Fahrenheit/percent |
| `wind_direction_deg`, `wind_speed_knots`, `wind_gust_knots`, `peak_wind_gust_knots` | IEM direction and winds |
| `precipitation_1hr_in`, `ice_accretion_1hr_in`, `ice_accretion_3hr_in`, `ice_accretion_6hr_in`, `asos_snow_depth_in` | IEM, inches |
| `is_freezing_rain`, `is_snow`, `is_ice_pellets`, `is_thunderstorm` | Binary flags from METAR codes |
| `local_date`, `ghcnd_snowfall_in`, `ghcnd_snow_depth_in` | Local-day NOAA GHCND daily snow, inches |

Reanalysis supplies the complete hourly grid. IEM observations join by UTC hour;
NOAA daily snow joins by local date, including the preceding local calendar day.
Hourly temperatures/humidity use means; wind direction uses a circular mean;
gusts, rolling accumulations and weather flags use maxima. Summing repeated
rolling precipitation or ice values would double count METAR/SPECI reports.
Daily snow values repeated across hours must not be summed.

### Hazards: storm event/county or river gage/hour/county

Keys: `event_id`, `city_key`, `fips_code`, `begin_timestamp_utc`,
`end_timestamp_utc`, `record_type`, `source_dataset`.

| Fields | Meaning |
| --- | --- |
| `event_type`, `source_zone_id`, `source_zone_name`, `geographic_match` | Original NOAA hazard and matching method |
| `damage_property_usd`, `damage_crops_usd` | Parsed monetary damage; never outage counts |
| `usgs_site`, `gage_height_ft`, `discharge_cfs` | Hourly maxima of observed stage/flow |
| `flood_stage_ft`, `is_river_flooding`, `flood_category` | Comparisons to verified NOAA NWPS minor/moderate/major stage thresholds |
| `threshold_reference` | Current NWPS metadata; historical datum changes are not asserted verified |

Storm rows carry `METEOROLOGICAL_HAZARD_AND_WEATHER_DAMAGE`; river rows carry
`RIVER_OBSERVATION`. County records match exact state/county FIPS. Forecast-zone
records match the named county in the original event's state and WFO, preserving
historical zone names, plus the current official county/zone correlation for
recent records. A zone event can cover more than one county; its reported damage
is not a county allocation. Historical unnamed/combined zones may require a
versioned GIS crosswalk for a finer geographic study. The matching method remains
visible per record. NWPS thresholds are obtained by exact USGS ID and feet units;
unknown thresholds produce unknown flood labels. Historical flood labels compare
observed stage to current thresholds and require datum review before use as
verified historical flood declarations.

### Outages: county event or observed 15-minute interval

Required fields: `outage_event_id`, `source_dataset`, `city_key`, `fips_code`,
`county_name`, `state`, `utility_name`, `start_timestamp_utc`,
`end_timestamp_utc`, `duration_minutes`, `peak_customers_out`,
`customer_hours_interrupted`, `reported_cause`, `record_type`.

Events require at least two adjacent observations at or above 100 customers,
exactly 15 minutes apart. Missing intervals break an event. Customer-hours
integrate observed bins (`sum(customers_out) / 4`); event end is the end of the
last bin, not a confirmed restoration time. Boundary-censor flags identify events
at the edges of observed county series. Duplicate county/timestamps are removed;
conflicting observations fail validation.

The publisher omits zero-outage rows. An absent row can mean either zero outages
or a reporting gap. The product never fills absent intervals with zero and never
creates negative training labels from those absences. `--resolution 15min` means
observed snapshots only. `utility_name` is configured primary-utility context,
not an observed utility identity within a county aggregate. County totals do not
identify feeders/circuits or customer restoration. Public geographic aggregation
also reflects infrastructure-security considerations, including CEII; the product
does not establish a legal reason for a particular archive's aggregation.

`reported_cause` distinguishes unknown causes, date/county DOE associations, and
temporal NOAA hazard associations. These associations do not prove causation.
Broad DOE customer counts are never copied into county events.

### Forecasts: source/county/valid hour/issue reference

Keys: `forecast_source`, `city_key`, `fips_code`, `valid_timestamp_utc`;
`issue_timestamp_utc`, `lead_time_hours`, `issue_time_semantics`, `forecast_model`,
`retrieved_timestamp_utc`, `lat`, `lon` preserve time/geography provenance.

| Source | Issue/lead interpretation |
| --- | --- |
| `NWS_NDFD` | Provider `updateTime`; expired periods omitted; grid lookup falls back through `/points` |
| `OPEN_METEO_LIVE` | Live stitched forecast; initialization/lead remain unknown, with retrieval time separate |
| `OPEN_METEO_ARCHIVED_DAY1` | Nominal valid-minus-24-hour fixed-offset reference, explicitly labeled; not a model initialization |
| `OPEN_METEO_ARCHIVED_RUN` | Exact ECMWF initialization and resulting lead hours; initialization precedes public availability |

The dense Previous Runs archive is supplemented by two-day exact-run samples
from the first day of each available month. `--forecast-runs` selects explicit
initializations instead of default monthly samples. The exact-run model is
`ecmwf_ifs`. Standard weather units match the historical table; freezing-level
height is meters. Live issuance cannot be inferred from retrieval time.

## Load enrichment

EIA actual sub-BA demand is paginated into `eia_subba_load.csv` for AEP and CSWS.
The matching BA actual demand and demand forecast produce
`eia_ba_load_anomalies.csv` for PJM and SWPP. They stay at BA geography. The EIA
sub-BA endpoint does not publish sub-BA forecasts. To compute a verified sub-BA
`load_drop_mw = actual_mw - forecast_mw`, set `EIA_SUBBA_FORECAST_CSV` to a CSV
with columns `subba`, `timestamp_utc`, `forecast_mw`, `issue_timestamp_utc`.
Keys must be unique, and forecasts must predate valid hours. This adapter never
subtracts an entire BA's forecast from a sub-BA actual value. Without a supplied
sub-BA forecast, those anomalies remain blank; without an API key, EIA is skipped.

## Coverage, model use and reproducibility

The requested observation window begins in 2015. EAGLE-I and current annual DOE
summaries publish through 2025; the product explicitly reports 2026 outage gaps.
NOAA annual storms and GHCND daily summaries have publication lag. Previous Runs
history starts in 2024; exact ECMWF runs start March 14, 2024. The specified
sources cannot provide 2021–2023 forecasts with exact original initialization.
These are publisher limitations, not generated or silently imputed data.

Use grouped chronological train/test splits. Daily summaries, final reanalysis,
post-event storm reports, future rolling accumulations and retrospective cause
associations can leak future information into a real-time predictor. The four
CSV products preserve source data and labels; they do not by themselves prove
an operational model's accuracy or publication-time availability. County
reporting coverage changes across years, and customers represent metered accounts,
not necessarily people. Avoid estimating county reliability denominators without
independently verified customer coverage.

Tests exercise join identity, exact hourly grids, damage units, fixed timezone
offsets, outage gaps and integrals, conflicting archives, byte-boundary assembly,
forecast initialization, EIA pagination and same-geography load math:

```powershell
.\.venv-pipeline\Scripts\python.exe -m unittest tests.test_ingestion_pipeline -v
```

Existing CI installs the ingestion lock and runs these tests. The manually
triggered `County data pipeline` GitHub workflow can run a smoke test or full
backfill and uploads the CSVs and validation reports. It is not scheduled and
has not been triggered remotely by this implementation.

Primary references: [ORNL dataset and zero-row semantics](https://pmc.ncbi.nlm.nih.gov/articles/PMC10915145/),
[Figshare source](https://api.figshare.com/v2/articles/24237376),
[OEDI submission](https://data.openei.org/submissions/6458),
[DOE annual reports](https://doe417.energy.gov/),
[NOAA county/zone correlation](https://www.weather.gov/gis/ZoneCounty),
[NWPS API](https://api.water.noaa.gov/nwps/v1/docs/),
[Open-Meteo exact runs](https://open-meteo.com/en/docs/single-runs-api),
[EIA demand and forecast geography](https://www.eia.gov/electricity/930-content/about.html).
