import os
from pathlib import Path
import psycopg

for name in (".env.local", ".env"):
    p = Path(name)
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))
        break
url = os.environ.get("DATABASE_URL_UNPOOLED") or os.environ["DATABASE_URL"]
with psycopg.connect(url) as conn:
    with conn.cursor() as cur:
        for table in ("substations", "circuits", "replay_cases", "damage_records", "households", "labor_references"):
            cur.execute(f"select count(*) from {table}")
            print(f"{table}={cur.fetchone()[0]}")
