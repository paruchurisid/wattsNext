# Watt'sNext

**Know what's next when the power goes out.**

Watt'sNext is a customer-facing outage and storm-readiness experience. It helps a household understand a grounded outage scenario, see what is known and uncertain, explore repair what-ifs, prepare for an interruption, and ask follow-up questions in plain language.

The product is deliberately honest about its evidence. Python owns calculations, scenario state, source limitations, safety guidance, and validation. An AI provider may explain those prepared facts, but it is not allowed to invent restoration numbers, claim live utility knowledge, or replace the deterministic fallback.

> **Product status:** Watt'sNext is a working prototype and replay system. It is not a live utility outage map, SCADA system, crew tracker, emergency-alert service, or guaranteed restoration-time predictor.

## What is available today

### Ask

The chat experience answers questions about the currently selected household and scenario. It can use:

- A local Ollama model (`llama3.2:3b` by default).
- Cloud Gemini, configured in Settings or through the server environment.
- Offline, facts-only responses when no model is available or an AI response fails validation.

Every answer is grounded in the current prepared household snapshot. Unsupported numbers, stale scenario context, conflicting risk labels, cut-off answers, and provider failures fall back to a visibly labeled deterministic response.

### Household Wiki

Wiki prepares the facts before chat becomes available. It brings together the household summary, risk and confidence labels, repair-time percentiles, damage and repair context, preparation guidance, declared needs, alert previews, FAQs, and source limitations. The Wiki and Ask tabs use the same versioned snapshot.

Changing the household, scenario, declared need, or source catalog invalidates the old snapshot and chat history. This prevents an answer about an earlier scenario from being presented as current.

### Storm Activity

Storm Activity provides independently switchable:

- Active NWS alerts.
- Seven-day weather hazards.
- A transparent estimated weather-risk index for Roanoke, Columbus, Charleston, and Tulsa.

The weather index is a screening heuristic, not an outage probability. It combines forecast hazards with same-calendar-month historical hazard frequency; it does not claim that weather alone predicts a particular outage.

### Scenario replay and what-if controls

The current product supports replaying example repair situations and testing:

- Blocked access, which applies a documented `+3.0 h` assumption.
- Additional crews, which may shorten independent queues but cannot split one repair into multiple parallel jobs.
- Repairs complete, which ends work in the example.
- Reset, which returns to the original example.

The interface shows repair timelines, P10/P50/P90 duration estimates, risk, confidence, preparation steps, and alert previews. These are scenario outputs, not utility-confirmed messages.

### Governance and auditability

The app exposes data-quality, model-card, audit-log, import-readiness, database-health, and readiness endpoints. Scenario changes, estimate changes, and alert previews can be recorded for inspection. The model card and UI distinguish source data, assumptions, model estimates, and unavailable information.

## Evidence and safety boundaries

Watt'sNext currently uses replay cases, sample households, labor references, weather feeds, historical weather, outage-event data, and meteorological hazards. The product does not:

- Infer medical conditions or silently infer a household's needs.
- Promise priority restoration or a specific restoration time.
- Present a sample completion state as proof that a real address has power.
- Claim live crew position, live outage status, shelter availability, compensation eligibility, or planned maintenance unless a future verified source is explicitly integrated.
- Use synthetic damage records as training labels for the weather index.

If a user asks for current emergency, outage, or crew information that Watt'sNext does not have, the app says so and directs the user to official Appalachian Power, NWS, emergency, or Red Cross resources as appropriate.

Medical-equipment guidance is only activated by an explicit declaration in the current conversation. It reminds the user to arrange approved backup power with the device provider; it never changes restoration priority.

## Current data model and assumptions

The bundled replay data includes four source-grounded cases and one synthetic no-validated-path case, plus sample households. No premise IDs, addresses, equipment IDs, or precise coordinates are sent to the browser; the UI receives city and circuit-level summaries.

Important assumptions are shown in the product as evidence tags:

- Labor values are crew-hours. Independent jobs run in parallel when crews are available.
- The indirect labor multiplier is `4.5`, taken from the supplied workbook.
- Scenario ranges are `75%–150%` of reference effort and are not confidence intervals.
- Blocked access adds `+3 h` to both ends of the range; this is an explicit assumption, not a source rate.
- Primary-conductor repair uses the closest documented workbook proxy and is labeled as an assumption.
- Household-to-case assignment is a replay assumption, so confidence is never above Medium for real replay cases.
- Risk bands are demonstration rules, not calibrated probabilities.

The weather and outage pipeline separately builds historical weather, hazards, observed utility outage events, and forecasts for four counties/locations. Validation and leakage precautions are documented in [docs/data-pipeline.md](docs/data-pipeline.md).

## Quick start

### Requirements

- Python 3.11+ recommended.
- Node.js and npm for browser checks and the deployment CLI.
- Ollama, optional, for local AI chat.
- Docker, optional, for container deployment.

### Run locally

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python server.py
```

Open <http://127.0.0.1:8000>.

The default provider is local Ollama. To use it:

```bash
ollama pull llama3.2:3b
ollama serve
```

Without Ollama, choose **Offline explanation mode** in Settings. This mode is a supported, deterministic fallback and requires no cloud API key.

### Environment variables

The main local AI settings are:

| Variable | Default | Purpose |
|---|---|---|
| `WATTSNEXT_PROVIDER` | `local` | `local` or `gemini` |
| `OLLAMA_MODEL` | `llama3.2:3b` | Installed Ollama model |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama endpoint |
| `OLLAMA_TIMEOUT` | `60` | Generation timeout in seconds, capped at 120 |
| `GEMINI_API_KEY` | — | Optional server-side Gemini key |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model override |
| `WATTSNEXT_USE_NEON` | — | Enable Neon-backed workflows |
| `DATABASE_URL` | — | Pooled Neon connection string |
| `DATABASE_URL_UNPOOLED` | — | Direct connection for migrations |
| `NEON_BRANCH` | — | Neon production branch identifier |

Copy [.env.example](.env.example) as a starting point. Never commit `.env.local`, database URLs, or API keys. Browser-entered Gemini keys stay in the current tab's memory and are cleared on reload.

For the hosted site, the browser can connect directly to a local Ollama instance if Ollama allows the site's origin:

```powershell
$env:OLLAMA_ORIGINS = "https://wattsnext.vercel.app"
ollama serve
```

Vercel cannot reach a laptop's `localhost`; use a reachable provider for hosted server-side generation.

## Test and verification commands

Run the Python suite:

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Run JavaScript syntax validation and browser tests:

```bash
npm install
npm run build
npx playwright install chromium
npm run test:browser
```

Run the local-model smoke check when Ollama is available:

```bash
python -m scripts.check_local_chat
```

The test suite covers the calculation engine, chat and provider fallbacks, AI connections, Wiki snapshots, weather outlook behavior, API routes, migration integrity, ingestion, and desktop/mobile browser flows.

## Weather and outage data pipeline

The pipeline is independent from the interactive server and can be run as a smoke test or a full historical load:

```powershell
uv venv .venv-pipeline
uv pip install --python .venv-pipeline/Scripts/python.exe -r requirements-pipeline.txt
.\\.venv-pipeline\\Scripts\\python.exe run_all.py --smoke-test
.\\.venv-pipeline\\Scripts\\python.exe run_all.py --start-year 2015 --end-year 2026
```

Use [the data-pipeline runbook](docs/data-pipeline.md) for source coverage, schemas, resume behavior, validation, backfills, and CI operation. Regenerate the small replay data package from the raw AEP package with:

```bash
python scripts/build_data.py
```

The raw `aep-data/` package is intentionally gitignored and is not redistributed.

## Project layout

```text
server.py                 Starlette app, routes, sessions, orchestration
api/index.py              Vercel Python entry point
concierge/                Chat, Wiki, tools, cases, providers, calculations
backend/                  Database, restoration, risk, weather, audit, pipeline logic
static/                   Plain HTML/CSS/JavaScript frontend; no frontend build step
data/                     Bundled replay data and pipeline outputs
src/                      Historical weather, hazards, outages, forecasts, validation
migrations/               Versioned Neon/Postgres migrations
scripts/                  Data generation, imports, migrations, smoke checks
tests/                    Unit, API, pipeline, and browser tests
docs/                     Product workflows, pitch/runbook, and pipeline documentation
```

The API currently includes endpoints for households, sessions, chat, Wiki, what-if actions, dashboard/replay data, settings, provider connections, governance, health/readiness, NWS alerts, and weather outlooks. See `/api/docs` while the server is running.

## Deployment

### Vercel

The repository includes `vercel.json` and `api/index.py`. Configure the production environment with the Neon and optional Gemini variables above, then run migrations with the direct database URL before the first deployment:

```bash
python scripts/migrate.py
```

Production deployment is tag-gated in CI. After the GitHub `production` environment approval, pushing a version tag such as `v1.0.0` deploys through Vercel when `VERCEL_TOKEN`, `VERCEL_ORG_ID`, and `VERCEL_PROJECT_ID` are configured. The pipeline applies versioned Neon migrations before deployment.

### Docker

```bash
docker compose up --build
```

The container listens on port `8000`. Inject secrets through the hosting platform rather than baking them into the image.

## Product roadmap

The following are planned extensions, not current capabilities:

1. **Verified live utility updates** — ingest official outage status, planned maintenance, and restoration notices with source timestamps and household matching.
2. **Event-specific storm experiences** — hurricane, tornado, and severe-thunderstorm workflows with official warning links and stronger safety routing.
3. **Calibrated outage probability** — combine real outage timestamps, asset exposure, weather, and held-out validation before presenting any probability.
4. **Production notification delivery** — turn alert previews into opt-in, auditable notifications with delivery status and quiet hours.
5. **Broader household and utility coverage** — improve geographic coverage, source reconciliation, and verified circuit/household matching.
6. **Operational integrations** — expose role-specific views for customer-service teams while preserving the same evidence and safety boundaries.

Planned features must preserve the central product rule: a current, source-labeled fact is different from a scenario estimate, and neither should be presented as a guarantee.

## More documentation

- [Pitch and three-minute demo runbook](docs/PITCH_AND_MVP.md)
- [Personas and product workflows](docs/product-user-workflows.md)
- [Weather and outage data-pipeline runbook](docs/data-pipeline.md)
- [Interface design decisions](static/DESIGN.md)
- [Local Apple-inspired interaction skill](skills/apple-design/SKILL.md)

## License and source data

This repository contains organizer-supplied sample and derived data for the Watt'sNext prototype. Review the terms and redistribution permissions for any upstream utility, weather, outage, or emergency-data source before publishing a production dataset.

