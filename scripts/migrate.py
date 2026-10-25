"""Transactional, checksum-verified migrations using a direct connection."""
import hashlib
import os
from pathlib import Path
import psycopg

def load_env():
    for name in ('.env.local', '.env'):
        path = Path(name)
        if path.exists():
            for line in path.read_text().splitlines():
                if '=' in line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"'))
            return

def migrate(conn, directory=Path("migrations")):
    files = sorted(directory.glob("*.sql"))
    if not files:
        raise RuntimeError("No SQL migrations found")
    applied = []
    with conn.transaction():
        conn.execute("set local lock_timeout = '30s'")
        conn.execute("set local statement_timeout = '120s'")
        conn.execute("select pg_advisory_xact_lock(782913450)")
        conn.execute("""create table if not exists schema_migrations (
            name text primary key, checksum text not null,
            applied_at timestamptz not null default now())""")
        recorded = dict(conn.execute("select name, checksum from schema_migrations").fetchall())
        if set(recorded) - {path.name for path in files}:
            raise RuntimeError("Previously applied migration files are missing")
        for path in files:
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            if path.name in recorded:
                if recorded[path.name] != checksum:
                    raise RuntimeError(f"Applied migration was modified: {path.name}")
                continue
            conn.execute(sql)
            conn.execute("insert into schema_migrations (name, checksum) values (%s, %s)", (path.name, checksum))
            applied.append(path.name)
    return applied


def main():
    load_env()
    url = os.environ.get("DATABASE_URL_UNPOOLED")
    if not url:
        raise SystemExit("DATABASE_URL_UNPOOLED is required for migrations")
    from urllib.parse import urlparse
    if "-pooler" in (urlparse(url).hostname or ""):
        raise SystemExit("Migrations require a direct, non-pooled database URL")
    try:
        with psycopg.connect(url, connect_timeout=10, autocommit=True) as conn:
            applied = migrate(conn)
        print(f"Migrations verified; {len(applied)} newly applied")
    except Exception as exc:
        raise SystemExit(f"Migration failed ({type(exc).__name__}); check database access and migration history") from None


if __name__ == "__main__":
    main()
