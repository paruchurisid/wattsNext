from src.common import configure_cache
from src.fetch_power_outages import eagle
import logging
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
configure_cache('data/cache')
f=eagle('2024-01-01','2024-12-31')
print('2024 exact county snapshots:',len(f),flush=True)
print(f.groupby('fips_code').size().to_string(),flush=True)
