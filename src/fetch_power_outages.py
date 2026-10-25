"""Stream county snapshots and construct observed utility outage events."""
import hashlib
import io
import re
import shutil
import zipfile
from pathlib import Path
import pandas as pd
from .config import FIPS, EIA_API_KEY
from .common import get, optional, write_csv
COLUMNS=['outage_event_id','source_dataset','city_key','fips_code','county_name','state','utility_name','start_timestamp_utc','end_timestamp_utc','duration_minutes','peak_customers_out','customer_hours_interrupted','reported_cause','record_type']

def normalize(frame,start,end):
    frame=frame.rename(columns={c:re.sub(r'[^a-z0-9]+','_',c.lower()).strip('_') for c in frame})
    aliases={'fips_code':['fips_code','fips','county_fips','county_fips_code'],'timestamp_utc':['timestamp_utc','run_start_time','timestamp','time','datetime','date_time'],'customers_out':['customers_out','sum','outage_count','customers_without_power']}
    for target,names in aliases.items():
        match=next((n for n in names if n in frame),None)
        if match is None: raise ValueError(f'Unsupported outage schema: missing {target}; columns={list(frame)}')
        if match!=target: frame=frame.rename(columns={match:target})
    frame['fips_code']=frame.fips_code.astype(str).str.replace(r'\.0$','',regex=True).str.zfill(5)
    frame=frame[frame.fips_code.isin(FIPS)].copy()
    frame['timestamp_utc']=pd.to_datetime(frame.timestamp_utc,utc=True,errors='coerce')
    frame['customers_out']=pd.to_numeric(frame.customers_out,errors='coerce')
    return frame[frame.timestamp_utc.ge(pd.Timestamp(start,tz='UTC')) & frame.timestamp_utc.lt(pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1))][['fips_code','timestamp_utc','customers_out']].dropna()

def read_chunks(handle,start,end):
    frames=[]
    for f in pd.read_csv(handle,chunksize=100000,dtype=str):
        selected=normalize(f,start,end)
        if not selected.empty: frames.append(selected)
    return pd.concat(frames,ignore_index=True) if frames else pd.DataFrame(columns=['fips_code','timestamp_utc','customers_out'])

def eagle(start,end):
    metadata=get('https://api.figshare.com/v2/articles/24237376').json()
    frames=[]
    for item in metadata['files']:
        years=re.findall(r'20\d{2}',item['name'])
        if years and not any(pd.Timestamp(start).year<=int(y)<=pd.Timestamp(end).year for y in years): continue
        if not re.fullmatch(r'eaglei_outages_20\d{2}\.csv(?:\.gz)?',item['name']): continue
        with get(item['download_url'],stream=True) as response:
            response.raw.decode_content=True
            if item['name'].endswith('.gz'):
                import gzip
                with gzip.GzipFile(fileobj=response.raw) as handle: frames.append(read_chunks(handle,start,end))
            else: frames.append(read_chunks(response.raw,start,end))
    if not frames:
        raise ValueError(f'EAGLE-I catalog contains no yearly files covering {start} through {end}')
    return pd.concat(frames,ignore_index=True)

def oedi(start,end,outdir):
    cache=outdir/'cache'; cache.mkdir(parents=True,exist_ok=True)
    target=cache/'outage-v2.zip'
    if not target.exists():
        temp=target.with_suffix('.partial')
        try:
            response=get('https://data.openei.org/files/6458/Outage%20Dataset%20v2.zip',stream=True)
        except Exception:
            response=get('https://data.openei.org/files/6458/Outage_Dataset_R1.zip',stream=True)
        with response, temp.open('wb') as output:
            for block in response.iter_content(1024*1024): output.write(block)
        temp.replace(target)
    frames=[]
    with zipfile.ZipFile(target) as archive:
        for name in archive.namelist():
            years=re.findall(r'20\d{2}',name)
            if years and not any(pd.Timestamp(start).year<=int(y)<=pd.Timestamp(end).year for y in years): continue
            if name.lower().endswith('_merged.csv'):
                with archive.open(name) as handle:
                    for f in pd.read_csv(handle,chunksize=100000,dtype={'fips':str}):
                        if 'fips' not in f or 'start_time' not in f:
                            raise ValueError(f'Unexpected OEDI event schema in {name}')
                        f['fips_code']=f.fips.str.zfill(5)
                        f=f[f.fips_code.isin(FIPS)].copy()
                        dates=pd.to_datetime(f.start_time,errors='coerce')
                        f=f[dates.ge(pd.Timestamp(start)) & dates.lt(pd.Timestamp(end)+pd.Timedelta(days=1))]
                        if len(f): frames.append(f.assign(archive_member=name))
    events=pd.concat(frames,ignore_index=True) if frames else pd.DataFrame()
    events.to_csv(outdir/'oedi_correlated_events.csv',index=False)
    # These pre-aggregated records cannot reconstruct the requested raw threshold definition.
    from .common import STATUS
    STATUS.append({'source':'OEDI event archive','status':'context_only','rows':len(events),'reason':'Pre-aggregated events retained in sidecar; no 15-minute snapshots'})
    return pd.DataFrame()

def aggregate(frame,resolution='event'):
    if frame.empty: return pd.DataFrame(columns=COLUMNS)
    # Archives overlap: identical county/timestamp records must never be added together.
    conflicts=frame.groupby(['fips_code','timestamp_utc']).customers_out.nunique()
    if conflicts.gt(1).any(): raise ValueError('Conflicting county snapshots across archives')
    frame=frame.drop_duplicates(['fips_code','timestamp_utc']).sort_values(['fips_code','timestamp_utc'])
    rows=[]
    for fips,county in frame.groupby('fips_code'):
        city=FIPS[fips]
        active=county[county.customers_out>=100].copy()
        active['group']=active.timestamp_utc.diff().ne(pd.Timedelta(minutes=15)).cumsum()
        groups=[group for _,group in active.groupby('group')] if resolution=='event' else [county.iloc[[i]] for i in range(len(county))]
        for group in groups:
            if resolution=='event' and len(group)<2: continue
            begin=group.timestamp_utc.iloc[0]; end=group.timestamp_utc.iloc[-1]+pd.Timedelta(minutes=15)
            rows.append(dict(outage_event_id=hashlib.sha256(f'{fips}:{begin.isoformat()}:{resolution}'.encode()).hexdigest()[:24],source_dataset=group.source_dataset.iloc[0],city_key=city.city_key,fips_code=fips,county_name=city.counties[fips],state=city.state,utility_name=city.utility_name,start_timestamp_utc=begin,end_timestamp_utc=end,duration_minutes=(end-begin).total_seconds()/60,peak_customers_out=group.customers_out.max(),customer_hours_interrupted=group.customers_out.sum()/4,reported_cause='UNKNOWN',record_type='ACTUAL_UTILITY_OUTAGE',boundary_semantics='observed_15min_bins',left_censored=begin==county.timestamp_utc.min(),right_censored=end>county.timestamp_utc.max()))
    return pd.DataFrame(rows)

def disturbances(start,end,outdir):
    cache=outdir/'cache'; cache.mkdir(exist_ok=True,parents=True)
    frames=[]
    for year in range(pd.Timestamp(start).year,min(pd.Timestamp(end).year,2025)+1):
        ext='xlsx' if year>=2024 else 'xls'
        url=f'https://doe417.energy.gov/summaries/{year}_Annual_Summary.{ext}'
        path=cache/f'OE417_{year}.{ext}'
        if not path.exists(): path.write_bytes(get(url).content)
        raw=pd.read_excel(path,header=None)
        header=next((i for i,row in raw.iterrows() if row.astype(str).str.contains('Date Began|Date Event Began',case=False,regex=True).any()),None)
        if header is None: raise ValueError(f'Unrecognized OE-417 header for {year}')
        f=pd.read_excel(path,header=header)
        f.columns=[re.sub(r'[^a-z0-9]+','_',str(c).lower()).strip('_') for c in f]
        f['source_year']=year; f['source_url']=url
        frames.append(f)
    result=pd.concat(frames,ignore_index=True) if frames else pd.DataFrame()
    result.to_csv(outdir/'doe_disturbances.csv',index=False)
    if not frames:
        raise ValueError('Official annual DOE-417 summaries currently end in 2025; no report for requested years')
    # Region-wide counts stay in a sidecar: allocating them to a county invents observations.
    return result

def eia(start,end,outdir):
    if not EIA_API_KEY:
        from .common import STATUS
        STATUS.append({'source':'EIA','status':'skipped','reason':'EIA_API_KEY unset'})
        return pd.DataFrame()
    rows=[]; offset=0
    while True:
        p={'api_key':EIA_API_KEY,'frequency':'hourly','data[0]':'value','facets[subba][]':['AEP','CSWS'],'start':start+'T00','end':end+'T23','length':5000,'offset':offset,'sort[0][column]':'period','sort[0][direction]':'asc'}
        response=get('https://api.eia.gov/v2/electricity/rto/region-sub-ba-data/data/',params=p).json()['response']
        rows.extend(response['data']); offset+=len(response['data'])
        if offset>=int(response['total']) or not response['data']: break
    frame=pd.DataFrame(rows)
    if not frame.empty: frame.to_csv(outdir/'eia_subba_load.csv',index=False)
    # Sub-BA endpoint provides actual demand; no forecast is fabricated to compute an anomaly.
    return frame

def run(start,end,outdir,resolution='event',**kwargs):
    frames=[]
    for name,fn in [('EAGLE-I',lambda:eagle(start,end)),('OEDI',lambda:oedi(start,end,outdir))]:
        frame=optional(name,fn)
        if not frame.empty: frames.append(frame.assign(source_dataset=name))
    doe=optional('DOE OE-417 annual summaries',lambda:disturbances(start,end,outdir))
    optional('EIA load',lambda:eia(start,end,outdir))
    result=aggregate(pd.concat(frames,ignore_index=True),resolution) if frames else pd.DataFrame(columns=COLUMNS)
    if not doe.empty and not result.empty and {'date_began','area_affected','event_type'}.issubset(doe):
        state_names={'VA':'Virginia','OH':'Ohio','WV':'West Virginia','OK':'Oklahoma'}
        for i,r in result.iterrows():
            area=doe.area_affected.fillna('').str.replace(' ','').str.lower()
            # A report must name this county AND state. Multi-county totals are never copied.
            match=doe[area.str.contains(r.county_name.replace(' ','').lower(),regex=False)&area.str.contains(state_names[r.state].replace(' ','').lower(),regex=False)]
            dates=pd.to_datetime(match.date_began,errors='coerce')
            local_start=r.start_timestamp_utc.tz_convert(FIPS[r.fips_code].iana_tz).tz_localize(None).normalize()
            match=match[dates.eq(local_start)]
            if len(match): result.loc[i,'reported_cause']='DOE_DATE_COUNTY_ASSOCIATION: '+'; '.join(match.event_type.dropna().astype(str).unique())
    hazard=outdir/'severe_weather_events.csv'
    if hazard.exists() and not result.empty:
        storms=pd.read_csv(hazard,dtype={'fips_code':str})
        storms=storms[storms.record_type.eq('METEOROLOGICAL_HAZARD_AND_WEATHER_DAMAGE')]
        for i,r in result.iterrows():
            match=storms[(storms.fips_code==r.fips_code)&(pd.to_datetime(storms.begin_timestamp_utc,utc=True)<=r.end_timestamp_utc)&(pd.to_datetime(storms.end_timestamp_utc,utc=True)>=r.start_timestamp_utc)]
            if len(match) and result.loc[i,'reported_cause']=='UNKNOWN':
                result.loc[i,'reported_cause']='TEMPORAL_ASSOCIATION: '+ '; '.join(sorted(set(match.event_type)))
    return write_csv(result,outdir/'power_outages.csv',COLUMNS)
