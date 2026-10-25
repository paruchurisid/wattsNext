"""Download restartable county-filtered EAGLE-I checkpoints before the full run."""

import logging
from src.common import configure_cache
from src.fetch_power_outages import eagle

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
configure_cache("data/cache")
frame = eagle("2015-01-01", "2025-12-31")
print("Downloaded real target-county snapshots:", len(frame), flush=True)
