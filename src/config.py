"""Canonical geography and units. County identifiers are always strings."""
from dataclasses import dataclass
import os

@dataclass(frozen=True)
class City:
    city_key: str
    state: str
    counties: dict
    asos_id: str
    ghcnd_id: str
    wfo_grid: str
    usgs_site: str
    lat: float
    lon: float
    iana_tz: str
    utility_name: str
    ba: str
    subba: str

CITIES = [
    City('ROA','VA',{'51770':'Roanoke City','51161':'Roanoke County'},'KROA','USW00013741','RNK/57,66','02055000',37.3169,-79.9741,'America/New_York','Appalachian Power (AEP)','PJM','AEP'),
    City('CMH','OH',{'39049':'Franklin County'},'KCMH','USW00014821','ILN/85,81','03227500',39.9980,-82.8819,'America/New_York','AEP Ohio','PJM','AEP'),
    City('CRW','WV',{'54039':'Kanawha County'},'KCRW','USW00013866','RLX/62,67','03198000',38.3731,-81.5932,'America/New_York','Appalachian Power (AEP)','PJM','AEP'),
    City('TUL','OK',{'40143':'Tulsa County'},'KTUL','USW00013968','TSA/43,66','07164500',36.1984,-95.8881,'America/Chicago','Public Service Co. of OK (PSO)','SWPP','CSWS'),
]
FIPS = {f:c for c in CITIES for f in c.counties}
NOAA_CDO_TOKEN = os.environ.get('NOAA_CDO_TOKEN')
EIA_API_KEY = os.environ.get('EIA_API_KEY')
NWS_USER_AGENT = os.environ.get('NWS_USER_AGENT','(PowerOutageModel, data-team@example.com)')
def fahrenheit_to_celsius(value): return (value - 32) * 5 / 9
def inches_to_mm(value): return value * 25.4
