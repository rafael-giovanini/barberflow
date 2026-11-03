import sqlite3
import tempfile
import unittest
from pathlib import Path

from migrate_sqlite_to_postgres import audit_sqlite_file


class SQLiteMigrationToolTests(unittest.TestCase):
    def test_audit_reports_counts_without_modifying_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "barberflow.sqlite"
            source = sqlite3.connect(path)
            source.execute("CREATE TABLE services (id INTEGER PRIMARY KEY, name TEXT)")
            source.executemany(
                "INSERT INTO services (name) VALUES (?)",
                [("Corte",), ("Barba",)],
            )
            source.commit()
            source.close()

            self.assertEqual(audit_sqlite_file(path), {"services": 2})
            reopened = sqlite3.connect(path)
            self.assertEqual(reopened.execute("SELECT COUNT(*) FROM services").fetchone()[0], 2)
            reopened.close()

    def test_rejects_empty_file_instead_of_treating_it_as_valid_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            empty_path = Path(temp_dir) / "empty.db"
            empty_path.touch()
            with self.assertRaisesRegex(ValueError, "não contém tabelas reconhecidas"):
                audit_sqlite_file(empty_path)

    def test_rejects_database_without_barberflow_tables(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "unrelated.sqlite"
            source = sqlite3.connect(path)
            source.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
            source.commit()
            source.close()
            with self.assertRaisesRegex(ValueError, "não contém tabelas reconhecidas"):
                audit_sqlite_file(path)


if __name__ == "__main__":
    unittest.main()
