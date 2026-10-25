"""Meteorological hazards and weather damage, never utility outage counts."""
import io
import re
from datetime import timezone, timedelta
import pandas as pd
from .config import CITIES
from .common import get, optional, write_csv, chunks

COLUMNS=['event_id','city_key','fips_code','begin_timestamp_utc','end_timestamp_utc','record_type','source_dataset','event_type','damage_property_usd','damage_crops_usd','gage_height_ft','discharge_cfs']
def damage(value):
    if pd.isna(value) or str(value).strip()=='': return float('nan')
    m=re.fullmatch(r'\s*([\d.]+)\s*([KMB]?)\s*',str(value),re.I)
    return float(m[1])*{'':1,'K':1e3,'M':1e6,'B':1e9}[m[2].upper()] if m else float('nan')

def storm_time(value,zone):
    m=re.fullmatch(r'(?:EST|CST|MST|PST|AST|HST)([+-]\d+)',str(zone))
    if not m: raise ValueError(f'Unknown Storm Events timezone: {zone}')
    return pd.to_datetime(value,format='%d-%b-%y %H:%M:%S').tz_localize(timezone(timedelta(hours=int(m[1])))).tz_convert('UTC')

def county_zones(city):
    # Official many-to-many zone/county correlation, including split counties.
    table=get('https://www.weather.gov/source/gis/Shapefiles/County/bp16ap26.dbx').text
    result={fips:set() for fips in city.counties}
    for line in table.splitlines():
        fields=line.split('|')
        if len(fields)>=7 and fields[6] in result:
            result[fields[6]].add(fields[0]+'Z'+fields[1].zfill(3))
    if any(not zones for zones in result.values()):
        raise ValueError('County missing from NOAA zone correlation')
    return result

def storms(start,end):
    listing=get('https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/').text
    rows=[]
    zone_maps={c.city_key:optional('NWS county zones '+c.city_key,lambda c=c:county_zones(c)) for c in CITIES}
    for year in range(pd.Timestamp(start).year,pd.Timestamp(end).year+1):
        names=sorted(set(re.findall(r'StormEvents_details-ftp_v1\.0_d'+str(year)+r'_c\d+\.csv\.gz',listing)))
        if not names: continue
        response=get('https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/'+names[-1],stream=True)
        response.raw.decode_content=True
        for frame in pd.read_csv(response.raw,compression='gzip',chunksize=50000,dtype={'STATE_FIPS':str,'CZ_FIPS':str},low_memory=False):
            frame=frame[frame.STATE_FIPS.str.zfill(2).isin(['51','39','54','40'])]
            for _,r in frame.iterrows():
                for city in CITIES:
                    zones=zone_maps[city.city_key]
                    for fips in city.counties:
                        county=r.CZ_TYPE=='C' and str(r.STATE_FIPS).zfill(2)+str(r.CZ_FIPS).zfill(3)==fips
                        zone=r.CZ_TYPE=='Z' and isinstance(zones,dict) and city.state+'Z'+str(r.CZ_FIPS).zfill(3) in zones.get(fips,set())
                        if not (county or zone): continue
                        begin=storm_time(r.BEGIN_DATE_TIME,r.CZ_TIMEZONE); finish=storm_time(r.END_DATE_TIME,r.CZ_TIMEZONE)
                        if finish<pd.Timestamp(start,tz='UTC') or begin>=pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1): continue
                        rows.append(dict(event_id=str(r.EVENT_ID),city_key=city.city_key,fips_code=fips,begin_timestamp_utc=begin,end_timestamp_utc=finish,event_type=r.EVENT_TYPE,damage_property_usd=damage(r.DAMAGE_PROPERTY),damage_crops_usd=damage(r.DAMAGE_CROPS),record_type='METEOROLOGICAL_HAZARD_AND_WEATHER_DAMAGE',source_dataset='NOAA_STORM_EVENTS',geographic_match='county' if county else 'forecast_zone'))
        response.close()
    return pd.DataFrame(rows)

def rivers(start,end):
    rows=[]
    for a,b in chunks(start,end):
        j=get('https://waterservices.usgs.gov/nwis/iv/',params=dict(format='json',sites=','.join(c.usgs_site for c in CITIES),parameterCd='00060,00065',startDT=a+'T00:00:00Z',endDT=b+'T23:59:59Z',siteStatus='all')).json()
        for series in j['value']['timeSeries']:
            site=series['sourceInfo']['siteCode'][0]['value']; code=series['variable']['variableCode'][0]['value']; nodata=float(series['variable'].get('noDataValue',-999999))
            city=next(c for c in CITIES if c.usgs_site==site)
            vals=[v for group in series['values'] for v in group['value'] if float(v['value'])!=nodata]
            if not vals: continue
            f=pd.DataFrame(vals); f['timestamp']=pd.to_datetime(f.dateTime,utc=True); f['value']=pd.to_numeric(f.value)
            for ts,val in f.set_index('timestamp').value.resample('h').max().dropna().items():
                for fips in city.counties:
                    rows.append(dict(event_id=f'USGS-{site}-{code}-{ts.isoformat()}',city_key=city.city_key,fips_code=fips,begin_timestamp_utc=ts,end_timestamp_utc=ts+pd.Timedelta(hours=1),record_type='RIVER_OBSERVATION',source_dataset='USGS_IV',usgs_site=site,**{('gage_height_ft' if code=='00065' else 'discharge_cfs'):val}))
    # Gage height alone cannot identify flooding without a station-specific flood-stage threshold.
    return pd.DataFrame(rows)

def run(start,end,outdir,**kwargs):
    frames=[optional('NOAA Storm Events',lambda:storms(start,end)),optional('USGS IV',lambda:rivers(start,end))]
    return write_csv(pd.concat(frames,ignore_index=True),outdir/'severe_weather_events.csv',COLUMNS)
