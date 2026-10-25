import os
from pathlib import Path
import psycopg

for line in Path('.env.local').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        key, value = line.split('=', 1)
        os.environ.setdefault(key, value.strip().strip('"'))

with psycopg.connect(os.environ['DATABASE_URL']) as conn:
    with conn.cursor() as cur:
        cur.execute("select table_name from information_schema.tables where table_schema='public' order by table_name")
        tables = [row[0] for row in cur.fetchall()]
        print('tables:', tables)
        for table in tables:
            cur.execute('select count(*) from ' + psycopg.sql.Identifier(table).as_string(conn))
            print(table + ':', cur.fetchone()[0])
        cur.execute('select status, quarantined, count(*) from damage_records group by status, quarantined order by status, quarantined')
        print('damage_status:', cur.fetchall())
        cur.execute('select count(*) from damage_records where status=\'unrepaired\' and repair_timestamp is not null')
        print('contradictory_records:', cur.fetchone()[0])
