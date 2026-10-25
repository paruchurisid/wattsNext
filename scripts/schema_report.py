import os
from pathlib import Path
import psycopg

for line in Path('.env.local').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        key, value = line.split('=', 1)
        os.environ.setdefault(key, value.strip().strip('"'))
with psycopg.connect(os.environ['DATABASE_URL']) as conn:
    with conn.cursor() as cur:
        cur.execute("select table_name,column_name,data_type from information_schema.columns where table_schema='public' order by table_name,ordinal_position")
        for table, column, dtype in cur.fetchall():
            print(f'{table}.{column}: {dtype}')
        cur.execute('select external_id,display_name,city,declared_needs from households limit 3')
        print('households_sample:', cur.fetchall())
        cur.execute('select case_key,label,storm_setting,path_valid from replay_cases limit 3')
        print('cases_sample:', cur.fetchall())
