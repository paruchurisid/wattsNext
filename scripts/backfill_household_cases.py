import csv, os
from pathlib import Path
import psycopg

for line in Path('.env.local').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"'))
rows = []
with Path('data/households.csv').open(newline='', encoding='utf-8-sig') as f:
    rows = [(r['case_key'], r['external_id']) for r in csv.DictReader(f)]
with psycopg.connect(os.environ['DATABASE_URL_UNPOOLED']) as conn:
    with conn.cursor() as cur:
        cur.executemany('update households set case_key=%s, updated_at=now() where external_id=%s', rows)
        conn.commit()
        cur.execute('select count(*) from households where case_key is not null')
        print({'updated_rows': len(rows), 'mapped_rows': cur.fetchone()[0]})
