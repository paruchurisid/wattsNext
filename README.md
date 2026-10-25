# Watt'sNext — AEP Outage Concierge

*Know what's next when the power goes out.*

A customer-facing chat assistant for a storm. Python computes every number
(risk, restoration time, alerts); the language model only interprets
questions, calls tools, and explains results in plain language.

## Run it

```bash
pip install -r requirements.txt
python3 server.py
# open http://127.0.0.1:8000
```

The default conversation engine is local **Ollama / `llama3.2:3b`**. Start
Ollama and ensure `ollama list` includes that model (install it with
`ollama pull llama3.2:3b` if needed). No cloud API key is required. Settings
shows the selected model and checks whether it is installed and reachable.
You can instead select Gemini and enter a key, or enable "Offline explanation
mode" to use verified rules without a model. Keys entered in Settings stay
in process memory and are never written to disk or logged.

Local-model configuration, read after the environment is loaded:

| Variable | Default | Purpose |
|---|---|---|
| `WATTSNEXT_PROVIDER` | `local` | `local` or `gemini` |
| `OLLAMA_MODEL` | `llama3.2:3b` | An installed Ollama model |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama HTTP endpoint |
| `OLLAMA_TIMEOUT` | `60` | Generation timeout in seconds (maximum 120) |

Legacy `OPENLLAMA_MODEL` and `OPENLLAMA_URL` are still accepted. Local tuning
uses temperature 0, a 4096-token context, a 180-token output budget, four
recent history messages, and ten-minute model residency. Python supplies the
facts, cards, uncertainty labels and safety instructions. Unsupported numbers,
conflicting risk labels, cut-off answers, or provider failures produce a
visibly labeled rule-based response. Preparation and completed-repair guidance
deliberately use rules. These checks are guardrails,
not a general semantic proof of every model sentence.

### AI connections on the hosted site

Open the engine control below the composer, or Settings. Choose **Local · Ollama**
to connect the browser directly to Ollama on your computer. Start Ollama, install
`llama3.2:3b`, and allow the site in `OLLAMA_ORIGINS` before starting Ollama:

```powershell
$env:OLLAMA_ORIGINS = "https://watts-next-phi.vercel.app"
ollama serve
```

Keep Ollama on its default localhost address; allow local network access if your
browser asks. The browser sends the server-prepared household context to Ollama,
then returns its answer for verification. Vercel never tries to reach your PC's
localhost. Model failures are shown explicitly; facts-only mode is an opt-in.

Choose **Cloud · Gemini** and enter your API key to use Gemini instead. The key
is checked without updating shared server settings, kept only in the current
tab's memory, and sent over HTTPS with each chat request. Reloading clears it.
The app identifies model-generated answers and any verification fallback.

Chat understands the same explicit replay actions as the what-if buttons,
including "What if access is blocked?" and "What if 2 more crews arrive?".
Explicit medical-device declarations affect only that conversation and never
modify the sample household. Requests are bounded and model work runs outside
the server event loop, so a slow model does not freeze Settings or other users.

The **Wiki** tab beside Ask and Storm Activity replaces the old quick-question
buttons. It collects household status, damage and repair work, restoration
ranges, computed duration percentiles, declared needs, preparation actions,
alert previews, FAQs and source limitations. `/api/wiki?session_id=...` returns
the versioned household snapshot. It computes the risk-model output and duration
simulation before chat generation; local and Gemini prompts receive relevant
facts from the same snapshot. Session creation and scenario updates return
`chat_ready` only after the statistics, Wiki answers, and model context are
prepared. The browser keeps chat disabled until then. Scenario, declared-need,
or source-data changes invalidate the snapshot and clear old chat history.
If data changes during generation, the stale answer is replaced with updated
household facts. This is per-request grounding, not model weight training.
Plain-language explanations and “Ask about this” buttons connect Wiki and Storm
Activity to chat.
The current risk model explicitly reports insufficient calibrated historical
signal: duration percentiles are available, but a validated outage probability
is not. Wiki labels this distinction rather than presenting a fabricated percentage.

Live local-model smoke check (requires Ollama):

```bash
python -m scripts.check_local_chat
```

For Docker, the model runs outside the app container: point `OLLAMA_BASE_URL`
at a reachable Ollama host (for Docker Desktop, typically
`http://host.docker.internal:11434`). Hosted Vercel cannot reach your laptop's
loopback address; choose a reachable provider or use the labeled rules mode.

To regenerate `data/*.json` from the raw AEP package (only needed if the
source package in `aep-data/` changes):

```bash
python3 scripts/build_data.py
```

Run tests:

```bash
pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
```

## Folder map

```
server.py                  Starlette routes, in-memory sessions, chat orchestration
concierge/
  engine.py                 Pure calculations: restoration effort, risk band, confidence, fallback
  cases.py                  Loads data/cases.json and data/sample.json
  customer_services.py      Preparation guidance and alert message generation
  tools.py                  The 4 tools exposed to the model, each evidence-tagged
  gemini.py                 Stdlib REST client: model listing, pinning, tool-call round trip
  local_llm.py              Ollama health checks and bounded local chat generation
  chat.py                   Context, fact checks, local/Gemini replies and rules
data/
  labor_reference.json      Install/removal hours by category, ILM, sourced from the AEP workbook
  cases.json                 4 real replay cases + 1 synthetic "no validated path" case
  sample.json                12 sample households, 3 per real case
scripts/
  build_data.py              One-time ETL from aep-data/ → data/*.json (no third-party deps)
  _dbf.py, _xlsx.py           Minimal stdlib readers for the raw shapefile/workbook formats
static/                      Plain HTML/CSS/JS, no build step
tests/                       unittest suite
aep-data/                    Organizer-supplied raw package (gitignored — not redistributed)
```

## Data provenance

The 4 real cases are grounded in the actual AEP HackOHI/O sample package
(`aep-data/`), not fully synthetic:

| Case | Station/Circuit | Cities | Why chosen |
|---|---|---|---|
| `transformer_roanoke` | STATION24/CIR114 | Roanoke, Hardy, Boones Mill | Real unrepaired transformer damage; 25 kVA is the modal size on this circuit |
| `wirepole_vinton` | STATION29/CIR6 | Vinton, Goodview, Blue Ridge | Real unrepaired primary-wire + pole damage |
| `wire_montvale` | STATION2/CIR60 | Montvale, Blue Ridge | Real unrepaired primary-wire damage |
| `calm_roanoke` | STATION10/CIR95 | Roanoke | Zero damage records — deliberately paired with the Roanoke transformer case to show risk follows the upstream path, not the city name |
| `no_path` | — | Roanoke | Synthetic: no validated upstream path, to exercise the cannot-predict fallback |

No premise IDs, addresses, equipment IDs, or precise coordinates reach the
browser — only city names and circuit-level damage summaries.

## Assumptions (shown in the UI as evidence tags)

- **Reference labor hours are crew-hours.** One crew per job; independent
  jobs run in parallel when crews are free (greedy list-scheduling across
  crews); the household's power returns only when every job on its path
  finishes.
- **Indirect labor multiplier = 4.5**, taken directly from the supplied
  workbook. It already covers drive time, safety briefing, and setup — not
  added again.
- **Scenario range = 75%–150%** of reference effort. Labeled "scenario
  range, not a confidence interval" everywhere it's shown.
- **Blocked access adds a flat +3 h assumption** to both ends of the range
  (not a workbook rate — there wasn't one for this).
- **Primary-conductor repair hours** have no per-span rate in the supplied
  workbook; the closest documented proxy (Dead-End/conductor-termination
  category) is used and tagged `Assumption`, not `Source data`.
- **Household-to-case assignment is always a replay assumption** — this is
  why confidence never exceeds Medium for any of the real cases.
- **Risk band and confidence are demonstration rules**, not calibrated
  probabilities, and are labeled as such everywhere.

## What is and isn't verified

- **Verified against the acceptance tests in `tests/test_engine.py`:** the
  transformer case computes exactly 6.7–13.5 h baseline and 9.7–16.5 h with
  blocked access, matching the brief's required numbers.
- **Not verified:** a live Gemini call. `concierge/gemini.py` implements the
  list-models → pin-a-model → tool-call round trip against the real REST
  API, but this sandbox has no API key or outbound network access to
  exercise it end-to-end. Offline mode (fully tested) is the guaranteed
  fallback path and is what the demo should lean on if the live call is
  flaky.
- **Verified locally during the chat repair:** real generation with the installed
  `llama3.2:3b`, the primary 6.7–13.5 h replay, blocked-access estimates, alert
  explanations, explicit rule-based completion and safety paths, and recovery
  when the model is unavailable or returns an unsupported number. Warm local
  generations typically took about 4–7 seconds on this machine; hardware and
  cold starts affect latency. Unit/API tests mock providers and need no API key.
- **Interface verification:** the Apple-inspired rebuild covers Ask, Storm Activity,
  Wiki, evidence dialogs, and Settings. Desktop and 375px mobile layouts were
  checked in light and dark appearance. The composer stays visible while the
  chat scrolls; answer cards are grouped, checklist and evidence details are
  expandable, and the tab indicator uses an interruptible spring. Reduced-motion,
  reduced-transparency, contrast, focus, and keyboard behavior have explicit
  treatments. The supplied skill is retained at skills/apple-design/SKILL.md,
  with project-specific decisions in static/DESIGN.md.
- **Never implemented on purpose:** live weather/outage/crew-position data,
  shelter status, compensation/credit eligibility, or any inference of
  health information — all explicitly out of scope per the brief's hard
  rules. These questions get an honest "I don't have that" answer pointing
  to the official Appalachian Power and Red Cross sites.

## Deploying to Vercel

The repository includes `vercel.json` and `api/index.py` for Vercel's Python
runtime. Import the repository into Vercel, then configure these environment
variables in the Vercel project settings:

- `DATABASE_URL` — pooled Neon connection string
- `DATABASE_URL_UNPOOLED` — direct Neon connection string for migrations only
- `NEON_BRANCH` — production branch identifier
- `GEMINI_API_KEY` — optional server-side Gemini key
- `GEMINI_MODEL` — optional model override, default `gemini-2.5-flash`
- `WATTSNEXT_PROVIDER=gemini` — use Gemini on hosting without a reachable Ollama server
- `WATTSNEXT_USE_NEON=true`

Do not commit `.env.local` or API keys. Run migrations before the first
production deployment with `python scripts/migrate.py` using the direct Neon
URL. Vercel handles the Python function; it does not run the Dockerfile.

## Docker deployment

Build and run the included container with:

```bash
docker compose up --build
```

The container listens on port 8000 and uses `.env.local` only for local
development. For hosted Docker, inject secrets through the platform's secret
manager instead.

## CI/CD release process

Every pull request runs repository secret checks, Python compilation and
lint, Python and npm dependency audits, unit/API tests, migration integrity
and rollback tests against disposable Postgres, desktop/mobile Chromium tests,
and a production Docker smoke test. Browser reports are retained for seven days.
Dependabot keeps Python packages, npm packages, and GitHub Actions current.

Python requirements are generated lockfiles. Update them from the repository root:

```bash
python -m piptools compile --strip-extras --output-file requirements.txt requirements.in
python -m piptools compile --strip-extras --output-file requirements-dev.txt requirements-dev.in
```

The npm lockfile pins the deployment CLI. Targeted overrides patch its transitive
dependencies; review them when upgrading Vercel and verify `npm audit` and
`npx --no-install vercel --version` before removing them.

Production deployment is intentionally tag-gated. After the `production`
GitHub environment approval, pushing a tag such as `v1.0.0` deploys through
Vercel when `VERCEL_TOKEN`, `VERCEL_ORG_ID`, and `VERCEL_PROJECT_ID` are set as
repository or environment secrets. The pipeline applies versioned Neon migrations
using the `DATABASE_URL_UNPOOLED` production secret before deploying Vercel.
Configure required reviewers on the GitHub `production` environment to enforce
approval; the workflow's environment name alone does not enforce it. Release
runs are serialized and cannot cancel an active migration or deployment.
Use Actions' manual Run workflow on `main` to validate without deploying;
production jobs run only for version tags.

### Seasonal weather outlook

Storm Activity now offers independently switchable NWS alerts, seven-day weather
hazards, and an estimated outage-risk index at four sample locations (Roanoke,
Columbus, Charleston, Tulsa). `/api/weather/outlook` fetches Open-Meteo daily
forecasts and three complete years of historical reanalysis. Same-calendar-month
hazard frequency adjusts a transparent wind/precipitation/snow/temperature score.
The index is an uncalibrated screening heuristic, not a percentage probability
of losing power. Synthetic bundled damage records are not used as training labels.
Real outage timestamps, asset exposure, and held-out validation are required to
calibrate an outage probability. Missing history is labeled forecast-only; missing
forecasts produce no estimates. Successful results cache for 30 minutes and
provider failures retry after one minute. Point markers do not imply area coverage.
Source: https://open-meteo.com/en/docs/historical-weather-api

## Weather and outage training-data ingestion

The modular ingestion package lives in `src/` and is separate from the web
application. Install its dependencies and run a live seven-day check:

```powershell
uv venv .venv-pipeline
uv pip install --python .venv-pipeline/Scripts/python.exe -r requirements-pipeline.in
.\.venv-pipeline\Scripts\python.exe run_all.py --smoke-test
.\.venv-pipeline\Scripts\python.exe run_all.py --start-year 2015 --end-year 2026
```

A full run first writes a seven-day sample under `data/smoke/`. It starts the
backfill only if every pipeline returns records and all attempted sources pass.
An empty hazard or outage window can be legitimate, but cannot satisfy this
strict smoke gate. Exit code 2 means incomplete validation, not successful
coverage. `--smoke-test` writes directly to `data/`; `--output-dir PATH` changes
that destination. `--resolution 15min` retains all observed county snapshots,
including zero counts, instead of constructing events. Dates end no later than
2026-10-24 or yesterday UTC. All downloads use retrying HTTPS with timeouts;
IEM has a one-second pause between yearly station requests. Output CSVs are
atomically replaced. Failures and row counts are recorded in
`data/ingestion_status.json`; check this manifest before using the data.

Set optional keys in `.env` using `.env.example`. Supply an identifying contact
in `NWS_USER_AGENT`. The NCEI Access service does not need `NOAA_CDO_TOKEN`.
Without `EIA_API_KEY`, load enrichment is skipped. This pipeline does not read
or expose credentials from the application's `.env.local`.

| CSV | Grain and keys | Measurements and interpretation |
| --- | --- | --- |
| `historical_weather.csv` | County/station/hour; `city_key`, `fips_code`, `asos_id`, `ghcnd_id`, `timestamp_utc` | Reanalysis `temp_c`, `precipitation_mm`, `rain_mm`, `snowfall_cm`, `snow_depth_m`, `wind_speed_kmh`, `wind_gust_kmh`; ASOS `asos_temp_c`, `dewpoint_f`, `relative_humidity_pct`, `wind_direction_deg`, `wind_speed_knots`, `wind_gust_knots`, `peak_wind_gust_knots`, `precipitation_1hr_in`, `ice_accretion_1hr_in`, `ice_accretion_3hr_in`, `ice_accretion_6hr_in`, `asos_snow_depth_in`; GHCND `ghcnd_snowfall_in`, `ghcnd_snow_depth_in` |
| `severe_weather_events.csv` | Hazard event/county, or river parameter/gage/hour/county; `event_id`, `fips_code`, UTC begin/end | `event_type`, `damage_property_usd`, `damage_crops_usd`, `gage_height_ft`, `discharge_cfs`; `record_type` separates meteorological hazards from river observations |
| `power_outages.csv` | County/event or county/15-minute snapshot | Required event identifiers, city/county/state/primary utility metadata, UTC start/end, duration minutes, peak customers, customer-hours, reported cause, source and `ACTUAL_UTILITY_OUTAGE` type |
| `weather_forecast.csv` | Source/county/valid hour/issue reference | `forecast_source`, `issue_timestamp_utc`, `valid_timestamp_utc`, `lead_time_hours`, city/FIPS/coordinates and weather fields using the same unit suffixes |

FIPS is a five-character string: read CSVs with `dtype={'fips_code': str}`.
All timestamps carry UTC offsets. Blank measurements mean unavailable, never
zero. ASOS weather-code flags identify freezing rain/drizzle, snow, ice pellets
and thunderstorms. ASOS temperatures and humidity use hourly means; gusts,
rolling precipitation/ice accumulations and binary flags use maxima. Summing
rolling accumulations would double count sub-hourly reports. NOAA daily values
join by local calendar date, including the prior UTC day's local date. Daily
snowfall repeated across hours must not be summed. These daily aggregates and
post-event storm reports are retrospective labels and can leak future
information if used as predictors before their publication time.

Both Roanoke City (`51770`) and Roanoke County (`51161`) receive KROA weather,
but retain separate outage counts. Each city's station/reanalysis/gage series
is replicated across its target counties; these are not independent weather
samples. Use grouped time-based train/test splits. County outage observations
do not resolve feeders, circuits or household restoration. Public aggregation
also reflects infrastructure-security/CEII considerations; this pipeline does
not establish a particular archive's legal reason for aggregation. The
configured utility is the area's primary utility, not an observed provider
identity in a county-total snapshot.

An outage event requires at least two consecutive observations at or above
100 customers, exactly 15 minutes apart. Missing samples break an event.
Customer-hours integrate observed 15-minute bins; end time is the end of the
last observed bin, not a verified restoration timestamp. Boundary-censor flags
identify events touching the downloaded county series boundaries. Duplicate
county/timestamps are deduplicated; conflicting values fail rather than being
added. NOAA overlap labels explicitly say `TEMPORAL_ASSOCIATION`; they do not
prove outage causation. DOE association requires the county and state to be
named on the same start date. Region-wide DOE counts stay in
`doe_disturbances.csv` and are never allocated to counties.

### Source availability and limits

- The supplied OEDI v2 URL returned 404 in the live check. The downloader falls
  back to the archive currently linked from the official submission,
  `https://data.openei.org/files/6458/Outage_Dataset_R1.zip`. ZIP contents are
  filtered in CSV chunks after a cached download. Recognized pre-aggregated
  event records are retained in `oedi_correlated_events.csv`; they cannot
  reconstruct the requested 15-minute event threshold and stay out of the
  primary outage CSV.
- The Figshare catalog currently publishes EAGLE-I yearly county files through
  2025. The runner does not fabricate 2026 outage coverage. Yearly CSVs can be
  over a gigabyte; they are filtered in bounded chunks without saving the raw
  CSV. Only files named `eaglei_outages_YEAR.csv` are selected.
- The legacy OE-417 hostname failed DNS resolution. Annual Excel summaries are
  now downloaded from the official `https://doe417.energy.gov/summaries/` route,
  using XLS before 2024 and XLSX afterwards. Their time conventions and broad
  reported areas do not justify manufacturing county outage events.
- NCEI annual Storm Events files have publication lag. The current official
  April 2026 zone/county correlation file matches split zones to counties;
  historical zone-boundary changes need versioned crosswalks before a
  production historical zone study. The current crosswalk is not a historical
  boundary reconstruction. No annual file means no validated storm coverage.
- USGS stage/discharge are observations, not a flood declaration. A flood flag
  requires independently verified, station-specific flood stage thresholds.
- Open-Meteo Previous Runs fixed-offset history begins in 2024 for the default
  archive; it cannot supply 2021–2023 issued forecasts. Its `previous_day1`
  values have a nominal 24-hour reference (`issue_time_semantics`), not a known
  model initialization. Live Open-Meteo initialization and lead time remain
  blank; retrieval time is recorded separately. Use the Single Runs API with
  explicit model/run identifiers if exact initialization is required. NWS uses
  provider `updateTime`, and expired periods are omitted.
- EIA's sub-BA series provides actual load, written to `eia_subba_load.csv`.
  It does not supply a matching sub-BA forecast. Consequently the pipeline
  does not invent `actual_mw - forecast_mw`; that enrichment needs a separately
  verified forecast source at matching geography and issue time.

These limits mean source coverage through 2026, exact historical forecast
issuance, versioned historical zones, flood labels, and sub-BA load anomalies
are not currently complete. Review the source manifest and coverage before
training a model. No synthetic data is generated by the ingestion code.

Focused validation:

```powershell
.\.venv-pipeline\Scripts\python.exe -m unittest tests.test_ingestion_pipeline -v
```
