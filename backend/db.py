"""Small Postgres adapter for the Starlette runtime.

The pooled Neon URL is used for request traffic. The unpooled URL remains
available for migrations and administrative work.
"""
import os
from pathlib import Path

def _load_local_env():
    for name in (".env.local", ".env"):
        path = Path(name)
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"'))
            break

_load_local_env()

def database_url():
    return os.environ.get("DATABASE_URL")

def ping():
    url = database_url()
    if not url:
        return {"connected": False, "reason": "DATABASE_URL is not configured"}
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute("select 1")
                cur.fetchone()
        return {"connected": True, "driver": "psycopg", "connection": "pooled DATABASE_URL"}
    except Exception as exc:
        return {"connected": False, "reason": str(exc)}

def table_counts():
    url = database_url()
    if not url:
        return {"connected": False, "reason": "DATABASE_URL is not configured"}
    tables = ["substations", "circuits", "damage_records", "households", "replay_cases", "labor_references", "simulation_sessions", "simulation_runs", "alert_events", "governance_audit_log"]
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                counts = {}
                for table in tables:
                    cur.execute("select count(*) from " + table)
                    counts[table] = cur.fetchone()[0]
                cur.execute("select count(*) from damage_records where status='unrepaired' and repair_timestamp is not null")
                contradictory = cur.fetchone()[0]
                cur.execute("select count(*) from damage_records where quarantined=true")
                quarantined = cur.fetchone()[0]
        return {"connected": True, "counts": counts, "data_quality": {"contradictory_records": contradictory, "quarantined_records": quarantined}}
    except Exception as exc:
        return {"connected": False, "reason": str(exc)}

def import_readiness():
    result = table_counts()
    if not result.get("connected"):
        return result
    counts = result["counts"]
    blockers = []
    if counts["households"] and counts["replay_cases"] and counts["simulation_sessions"] == 0:
        blockers.append("households are not yet mapped to replay sessions at runtime")
    if result["data_quality"]["contradictory_records"] != result["data_quality"]["quarantined_records"]:
        blockers.append("all contradictory damage records must be quarantined")
    return {"ready_for_runtime_cutover": not blockers, "blockers": blockers, **result}
