"""Seasonal weather hazard screening; deliberately not an outage probability model."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import math
import threading
import time
import urllib.parse
import urllib.request
import json

SITES = [("Roanoke, VA", 37.27, -79.94), ("Columbus, OH", 39.96, -83.0),
         ("Charleston, WV", 38.35, -81.63), ("Tulsa, OK", 36.15, -95.99)]
FIELDS = "wind_gusts_10m_max,precipitation_sum,snowfall_sum,temperature_2m_max,temperature_2m_min"
_cache = {}
_lock = threading.Lock()


def fetch_daily(historical=False):
    today = date.today()
    params = dict(latitude=",".join(str(s[1]) for s in SITES),
                  longitude=",".join(str(s[2]) for s in SITES), daily=FIELDS, timezone="auto")
    if historical:
        params.update(start_date=f"{today.year - 3}-01-01", end_date=f"{today.year - 1}-12-31")
        base = "https://archive-api.open-meteo.com/v1/archive"
    else:
        params["forecast_days"] = 7
        base = "https://api.open-meteo.com/v1/forecast"
    request = urllib.request.Request(base + "?" + urllib.parse.urlencode(params),
                                     headers={"User-Agent": "WattsNext/1.0"})
    with urllib.request.urlopen(request, timeout=18) as response:
        payload = json.load(response)
    if not isinstance(payload, list) or len(payload) != len(SITES):
        raise ValueError("Incomplete weather response")
    return payload


def rows(daily):
    for i, day in enumerate(daily.get("time", [])):
        values = [daily.get(key, [])[i] if i < len(daily.get(key, [])) else None for key in FIELDS.split(",")]
        if all(isinstance(v, (float, int)) and math.isfinite(v) for v in values):
            yield dict(zip(["date", "gust", "rain", "snow", "high", "low"], [day] + values))


def hazards(row):
    # Transparent engineering screening thresholds, not fitted outage coefficients.
    return {"Wind": min(100, max(0, (row["gust"] - 30) * 2)),
            "Heavy precipitation": min(100, row["rain"] * 2),
            "Snow": min(100, row["snow"] * 8),
            "Temperature stress": min(100, max(0, row["high"] - 32, -10 - row["low"]) * 6)}


def score_day(row, history):
    month = date.fromisoformat(row["date"]).month
    sample = [r for r in history if date.fromisoformat(r["date"]).month == month]
    signals = hazards(row)
    raw = max(signals.values())
    # Seasonality enters through same-calendar-month historical hazard frequency.
    frequency = sum(max(hazards(r).values()) >= 40 for r in sample) / len(sample) if sample else None
    score = round(min(100, raw * (1 + .2 * frequency))) if frequency is not None else round(raw)
    return {"date": row["date"], "index": score,
            "band": "High" if score >= 70 else "Elevated" if score >= 40 else "Low",
            "drivers": [k for k, v in signals.items() if v >= 40],
            "conditions": row, "history_days": len(sample),
            "historical_hazard_day_fraction": round(frequency, 3) if frequency is not None else None}


def outlook():
    now = time.monotonic()
    with _lock:
        if _cache.get("expires", 0) > now:
            return _cache["payload"]
    errors = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = {name: pool.submit(fetch_daily, historical) for name, historical in [("forecast", False), ("history", True)]}
        data = {}
        for name, job in jobs.items():
            try:
                data[name] = job.result()
            except (OSError, ValueError, TimeoutError):
                data[name] = []
                errors.append(f"{name} unavailable")
    features = []
    for i, (name, lat, lon) in enumerate(SITES):
        forecast = list(rows(data["forecast"][i].get("daily", {}))) if data["forecast"] else []
        history = list(rows(data["history"][i].get("daily", {}))) if data["history"] else []
        days = [score_day(row, history) for row in forecast]
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                         "properties": {"name": name, "days": days}})
    payload = {"type": "FeatureCollection", "features": features,
               "generated_at": datetime.now(timezone.utc).isoformat(), "errors": errors,
               "source": "Open-Meteo forecast and historical reanalysis", "is_calibrated": False,
               "method": "v1: maximum weather hazard score × (1 + 0.2 × same-month historical hazard-day frequency), capped at 100. Three previous calendar years. Index is not an outage probability; local infrastructure and outage history are not included.",
               "coverage": "Four sample locations; markers represent point forecasts, not regional boundaries."}
    with _lock:
        _cache.update(payload=payload, expires=now + (60 if errors else 1800))
    return payload
