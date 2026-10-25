"""Shared retrying HTTP, bounded downloads, provenance and atomic CSV writes."""

import io
import json
import logging
import os
import hashlib
import time
import uuid
from pathlib import Path
import requests
import pandas as pd
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .config import NWS_USER_AGENT, EIA_API_KEY, NOAA_CDO_TOKEN

LOG = logging.getLogger(__name__)
SESSION = requests.Session()
SESSION.headers["User-Agent"] = NWS_USER_AGENT
SESSION.mount(
    "https://",
    HTTPAdapter(
        pool_connections=24,
        pool_maxsize=24,
        max_retries=Retry(
            total=4,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            respect_retry_after_header=True,
        ),
    ),
)
STATUS = []
CACHE_ROOT = Path("data/cache")


def configure_cache(path):
    global CACHE_ROOT
    CACHE_ROOT = Path(path)
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)


def get(url, **kwargs):
    # Cache bounded API responses, never large streaming bulk downloads. Live
    # forecasts remain uncached. The URL digest contains no credentials on disk.
    cacheable = not kwargs.get("stream") and not any(
        x in url
        for x in (
            "api.eia.gov",
            "/forecast/hourly",
            "api.open-meteo.com/v1/forecast",
            "api.weather.gov/points",
        )
    )
    key = requests.Request("GET", url, params=kwargs.get("params")).prepare().url
    path = CACHE_ROOT / "http" / (hashlib.sha256(key.encode()).hexdigest() + ".bin")
    if cacheable and path.exists() and time.time() - path.stat().st_mtime < 86400:
        response = requests.Response()
        response.status_code = 200
        response._content = path.read_bytes()
        response.encoding = "utf-8"
        response.url = url
        return response
    response = SESSION.get(url, timeout=(20, 180), **kwargs)
    response.raise_for_status()
    if cacheable:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_bytes(response.content)
        os.replace(temp, path)
    return response


def optional(source, fn):
    try:
        value = fn()
        STATUS.append(
            {
                "source": source,
                "status": "ok",
                "rows": len(value) if hasattr(value, "__len__") else None,
            }
        )
        return value
    except Exception as exc:
        error = str(exc)
        for secret in (EIA_API_KEY, NOAA_CDO_TOKEN):
            if secret:
                error = error.replace(secret, "[REDACTED]")
        LOG.warning("%s unavailable: %s", source, error)
        STATUS.append({"source": source, "status": "unavailable", "error": error})
        return pd.DataFrame()


def csv_response(response, **kwargs):
    return pd.read_csv(io.StringIO(response.text), **kwargs)


def download(url, path):
    """Restart a streamed file after a body-read failure and publish atomically."""
    from tenacity import (
        retry,
        stop_after_attempt,
        wait_exponential,
        retry_if_exception_type,
    )

    path = Path(path)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=30),
        retry=retry_if_exception_type((requests.RequestException, OSError)),
        reraise=True,
    )
    def transfer():
        tmp = path.with_suffix(".partial")
        with get(url, stream=True) as response, tmp.open("wb") as output:
            for block in response.iter_content(1024 * 1024):
                output.write(block)
        os.replace(tmp, path)

    transfer()
    return path


def write_csv(frame, path, columns):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    for col in columns:
        if col not in frame:
            frame[col] = pd.Series(dtype="object")
    if len(frame):
        for key in ("city_key", "fips_code"):
            if frame[key].isna().any() or frame[key].astype(str).eq("").any():
                raise ValueError(f"Missing join key: {key}")
        if not frame.fips_code.astype(str).str.fullmatch(r"\d{5}").all():
            raise ValueError("Invalid county FIPS")
        for key in (
            "timestamp_utc",
            "begin_timestamp_utc",
            "end_timestamp_utc",
            "valid_timestamp_utc",
            "start_timestamp_utc",
        ):
            if key in columns and (
                key not in frame
                or pd.to_datetime(frame[key], utc=True, errors="coerce").isna().any()
            ):
                raise ValueError(f"Missing or invalid timestamp join key: {key}")
    tmp = path.with_suffix(".csv.tmp")
    frame.to_csv(tmp, index=False)
    os.replace(tmp, path)
    return frame


def chunks(start, end, days=31):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    while start <= end:
        stop = min(start + pd.Timedelta(days=days - 1), end)
        yield start.date().isoformat(), stop.date().isoformat()
        start = stop + pd.Timedelta(days=1)


def manifest(path):
    atomic_json(path, STATUS)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    os.replace(tmp, path)
