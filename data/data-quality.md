# County data product audit

Requested observations: 2015-01-01 through 2026-10-24 UTC.

| Product | Actual rows | Size (MB) |
| --- | ---: | ---: |
| historical_weather.csv | 517,800 | 105.7 |
| severe_weather_events.csv | 518,379 | 120.1 |
| power_outages.csv | 16,920 | 3.8 |
| weather_forecast.csv | 133,440 | 25.4 |

All rows in this audit are read from the output CSVs. Checksums identify the exact files audited.

See `validation_summary.json` for join-key and hourly-grid validation, `ingestion_status.json` for source failures and publication gaps, and `coverage_by_county_year.csv` for county/year counts.

An absent outage observation is unknown, never a verified zero. Forecast rows mix source-specific issue semantics; exact model initialization is not publication time. River threshold comparisons use current metadata, not a verified historical datum reconstruction.

A successful schema audit does not assert that an unpublished source year exists.
