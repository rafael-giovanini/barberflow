import os
import sqlite3
import tempfile
import unittest

import database


class DatabaseMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        self.original_admin_email = os.environ.get("INITIAL_ADMIN_EMAIL")
        self.original_admin_password = os.environ.get("INITIAL_ADMIN_PASSWORD")
        database.DB_PATH = os.path.join(self.temp_dir.name, "barberflow-test.db")
        os.environ.pop("INITIAL_ADMIN_EMAIL", None)
        os.environ.pop("INITIAL_ADMIN_PASSWORD", None)

        # Simula banco legado já contendo um cliente antes da migração.
        conn = sqlite3.connect(database.DB_PATH)
        conn.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                phone TEXT,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'customer',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "INSERT INTO users (name, email, phone, password_hash, role) VALUES (?, ?, ?, ?, ?)",
            ("Cliente Existente", "cliente@example.com", "18999990000", "hash-legado", "customer")
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        for key, value in (
            ("INITIAL_ADMIN_EMAIL", self.original_admin_email),
            ("INITIAL_ADMIN_PASSWORD", self.original_admin_password),
        ):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp_dir.cleanup()

    def test_migration_preserves_users_and_adds_security_fields(self):
        database.init_db()
        conn = sqlite3.connect(database.DB_PATH)
        conn.row_factory = sqlite3.Row
        customer = conn.execute(
            "SELECT * FROM users WHERE email=?", ("cliente@example.com",)
        ).fetchone()
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        reset_table = conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='password_reset_tokens'
        """).fetchone()
        conn.close()

        self.assertIsNotNone(customer)
        self.assertEqual(customer["name"], "Cliente Existente")
        self.assertEqual(customer["password_hash"], "hash-legado")
        self.assertEqual(customer["active"], 1)
        self.assertEqual(customer["session_version"], 0)
        self.assertIn("active", columns)
        self.assertIn("session_version", columns)
        self.assertIn("cpf", columns)
        self.assertIn("address", columns)
        self.assertIn("first_access_required", columns)
        self.assertEqual(customer["first_access_required"], 0)
        self.assertIsNotNone(reset_table)


if __name__ == "__main__":
    unittest.main()
