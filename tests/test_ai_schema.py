"""Schema tests. The DDL-shape assertions run without a database; the apply test
skips when Postgres is not reachable so the suite stays runnable on a laptop."""
import re
import unittest

from ai.schema import AI_MIGRATION_SQL, AI_TABLES, run_ai_migrations


def db_available() -> bool:
    try:
        from db.connection import is_connected
        return is_connected()
    except Exception:
        return False


class TestSchemaShape(unittest.TestCase):

    def test_all_nine_tables_are_defined(self):
        self.assertEqual(9, len(AI_TABLES))
        joined = "\n".join(AI_MIGRATION_SQL)
        for table in AI_TABLES:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", joined, table)

    def test_every_table_carries_tenant_id(self):
        """Global constraint: no ai_* table may exist without tenant scoping."""
        for ddl in AI_MIGRATION_SQL:
            if not ddl.startswith("CREATE TABLE"):
                continue
            table = re.search(r"CREATE TABLE IF NOT EXISTS (\w+)", ddl).group(1)
            self.assertIn("tenant_id", ddl, f"{table} has no tenant_id column")

    def test_tenant_id_defaults_to_default_and_is_not_null(self):
        for ddl in AI_MIGRATION_SQL:
            if ddl.startswith("CREATE TABLE") and "tenant_id" in ddl:
                self.assertRegex(ddl, r"tenant_id\s+VARCHAR\(64\)\s+NOT NULL DEFAULT 'default'")

    def test_all_ddl_is_idempotent(self):
        for ddl in AI_MIGRATION_SQL:
            self.assertTrue(
                ddl.startswith("CREATE TABLE IF NOT EXISTS")
                or ddl.startswith("CREATE INDEX IF NOT EXISTS")
                or ddl.startswith("CREATE UNIQUE INDEX IF NOT EXISTS"),
                ddl[:70],
            )

    def test_credentials_live_in_their_own_table(self):
        """A SELECT * on ai_providers must not be able to return a key."""
        providers = next(d for d in AI_MIGRATION_SQL if "CREATE TABLE IF NOT EXISTS ai_providers" in d)
        for forbidden in ("api_key", "ciphertext", "secret", "credential"):
            self.assertNotIn(forbidden, providers.lower())


@unittest.skipUnless(db_available(), "PostgreSQL not reachable")
class TestSchemaApplies(unittest.TestCase):

    def test_migrations_apply_and_are_repeatable(self):
        run_ai_migrations()
        run_ai_migrations()          # must not raise on a second run
        from db.connection import query_one
        for table in AI_TABLES:
            row = query_one(
                "SELECT to_regclass(%s) AS present", (f"public.{table}",)
            )
            self.assertIsNotNone(row["present"], table)


if __name__ == "__main__":
    unittest.main()
