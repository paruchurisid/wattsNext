"""Shared retrying HTTP, bounded downloads, provenance and atomic CSV writes."""
import io
import json
import logging
import os
from pathlib import Path
import requests
import pandas as pd
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .config import NWS_USER_AGENT, EIA_API_KEY, NOAA_CDO_TOKEN

LOG = logging.getLogger(__name__)
SESSION = requests.Session()
SESSION.headers['User-Agent'] = NWS_USER_AGENT
SESSION.mount('https://', HTTPAdapter(max_retries=Retry(total=4, backoff_factor=1, status_forcelist=[429,500,502,503,504], allowed_methods=['GET'], respect_retry_after_header=True)))
STATUS = []
def get(url, **kwargs):
    response = SESSION.get(url, timeout=(20,180), **kwargs)
    response.raise_for_status()
    return response

def optional(source, fn):
    try:
        value = fn()
        STATUS.append({'source':source,'status':'ok','rows':len(value) if hasattr(value,'__len__') else None})
        return value
    except Exception as exc:
        error=str(exc)
        for secret in (EIA_API_KEY,NOAA_CDO_TOKEN):
            if secret: error=error.replace(secret,'[REDACTED]')
        LOG.warning('%s unavailable: %s', source, error)
        STATUS.append({'source':source,'status':'unavailable','error':error})
        return pd.DataFrame()

def csv_response(response, **kwargs):
    return pd.read_csv(io.StringIO(response.text), **kwargs)

def write_csv(frame, path, columns):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    for col in columns:
        if col not in frame: frame[col] = pd.Series(dtype='object')
    if len(frame):
        for key in ('city_key','fips_code'):
            if frame[key].isna().any() or frame[key].astype(str).eq('').any():
                raise ValueError(f'Missing join key: {key}')
        if not frame.fips_code.astype(str).str.fullmatch(r'\d{5}').all():
            raise ValueError('Invalid county FIPS')
        for key in ('timestamp_utc','begin_timestamp_utc','end_timestamp_utc','valid_timestamp_utc','start_timestamp_utc'):
            if key in columns and (key not in frame or pd.to_datetime(frame[key],utc=True,errors='coerce').isna().any()):
                raise ValueError(f'Missing or invalid timestamp join key: {key}')
    tmp = path.with_suffix('.csv.tmp')
    frame.to_csv(tmp, index=False)
    os.replace(tmp,path)
    return frame

def chunks(start, end, days=31):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    while start <= end:
        stop = min(start + pd.Timedelta(days=days-1),end)
        yield start.date().isoformat(),stop.date().isoformat()
        start = stop + pd.Timedelta(days=1)

def manifest(path):
    Path(path).write_text(json.dumps(STATUS,indent=2),encoding='utf-8')
