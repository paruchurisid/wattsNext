"""Run an audited seven-day check before a historical backfill."""
import argparse
import json
import logging
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
load_dotenv()
from src import fetch_historical_weather, fetch_severe_weather, fetch_power_outages, fetch_weather_forecasts
from src.common import STATUS, manifest
MODULES=[fetch_historical_weather,fetch_severe_weather,fetch_power_outages,fetch_weather_forecasts]

def execute(start,end,outdir,resolution):
    complete=True
    coverage={}
    outdir.mkdir(parents=True,exist_ok=True)
    for module in MODULES:
        try:
            frame=module.run(start,end,outdir,resolution=resolution)
            print(f'\n{module.__name__}: {len(frame):,} actual rows',flush=True)
            print(frame.head(3).to_string(index=False),flush=True)
            coverage[module.__name__]={'rows':len(frame),'requested_start':start,'requested_end':end,'nonnull_counts':{k:int(v) for k,v in frame.count().items()}}
            if frame.empty:
                complete=False
                print('EMPTY: schema exists, but this is NOT evidence of source coverage.',flush=True)
            else:
                assert frame[['city_key','fips_code']].notna().all().all()
                print('Join keys: zero missing',flush=True)
        except Exception as exc:
            logging.exception('Pipeline failed: %s',module.__name__)
            STATUS.append({'source':module.__name__,'status':'failed','error':str(exc)})
            complete=False
        manifest(outdir/'ingestion_status.json')
        (outdir/'validation_summary.json').write_text(json.dumps(coverage,indent=2),encoding='utf-8')
    return complete and not any(s['status'] in ('failed','unavailable','unsupported_schema') for s in STATUS)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-year',type=int,default=2015)
    parser.add_argument('--end-year',type=int,default=2026)
    parser.add_argument('--smoke-test',action='store_true')
    parser.add_argument('--resolution',choices=['event','15min'],default='event')
    parser.add_argument('--output-dir',type=Path,default=Path('data'))
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s')
    start=f'{args.start_year}-01-01'
    end=min(pd.Timestamp(f'{args.end_year}-12-31'),pd.Timestamp.now(tz='UTC').tz_localize(None).normalize()-pd.Timedelta(days=1),pd.Timestamp('2026-10-24')).date().isoformat()
    if start>end: parser.error('Start year exceeds available end date')
    # Historical sample ends in requested range; forecasts always include live upcoming periods.
    smoke_start=max(pd.Timestamp(start),pd.Timestamp(end)-pd.Timedelta(days=6)).date().isoformat()
    smoke_dir=args.output_dir if args.smoke_test else args.output_dir/'smoke'
    ok=execute(smoke_start,end,smoke_dir,args.resolution)
    if args.smoke_test: return 0 if ok else 2
    if not ok:
        logging.error('Smoke validation incomplete; backfill was not started. See ingestion_status.json.')
        return 2
    STATUS.clear()
    return 0 if execute(start,end,args.output_dir,args.resolution) else 2
if __name__=='__main__': raise SystemExit(main())
