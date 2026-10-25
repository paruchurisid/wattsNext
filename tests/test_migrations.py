"""Integration checks use only an explicitly configured disposable database."""
import os
from pathlib import Path
import tempfile
import unittest
import psycopg
from scripts.migrate import migrate


@unittest.skipUnless(os.environ.get("CI_TEST_DATABASE_URL"), "Disposable Postgres is not configured")
class Migrations(unittest.TestCase):
    def test_reapply_integrity_and_transaction_rollback(self):
        with psycopg.connect(os.environ["CI_TEST_DATABASE_URL"], autocommit=True) as conn:
            migrate(conn)
            self.assertEqual(migrate(conn), [])
            count = conn.execute("select count(*) from schema_migrations").fetchone()[0]
            self.assertEqual(count, len(list(Path("migrations").glob("*.sql"))))
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for source in Path("migrations").glob("*.sql"):
                    (root / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
                first = sorted(root.glob("*.sql"))[0]
                first.write_text(first.read_text(encoding="utf-8") + "\n-- changed", encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "modified"):
                    migrate(conn, root)
                first.write_text(Path("migrations", first.name).read_text(encoding="utf-8"), encoding="utf-8")
                (root / "999_failure.sql").write_text("create table ci_rollback_probe (id int); select * from ci_missing_table;", encoding="utf-8")
                with self.assertRaises(psycopg.Error):
                    migrate(conn, root)
                self.assertIsNone(conn.execute("select to_regclass('ci_rollback_probe')").fetchone()[0])
                self.assertEqual(conn.execute("select count(*) from schema_migrations").fetchone()[0], count)
