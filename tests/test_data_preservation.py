"""Testes de regressão para preservar agendamentos e pedidos existentes.

Os testes usam SQLite temporário e nunca acessam o banco de desenvolvimento/produção.
"""
import os
import tempfile
import unittest

import database


class ExistingDataPreservationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        self.original_admin_email = os.environ.get("INITIAL_ADMIN_EMAIL")
        self.original_admin_password = os.environ.get("INITIAL_ADMIN_PASSWORD")
        database.DB_PATH = os.path.join(self.temp_dir.name, "barberflow-preservation.db")
        os.environ.pop("INITIAL_ADMIN_EMAIL", None)
        os.environ.pop("INITIAL_ADMIN_PASSWORD", None)
        database.init_db()

        conn = database.get_db()
        conn.execute(
            """INSERT INTO users (name, email, phone, password_hash, role)
               VALUES (?, ?, ?, ?, ?)""",
            ("Cliente Legado", "legado@example.test", "", "hash-de-teste", "customer"),
        )
        self.user_id = conn.execute(
            "SELECT id FROM users WHERE email=?", ("legado@example.test",)
        ).fetchone()["id"]

        conn.execute(
            "INSERT INTO services (name, price, duration_min) VALUES (?, ?, ?)",
            ("Serviço legado", 35.0, 30),
        )
        self.service_id = conn.execute(
            "SELECT id FROM services WHERE name=?", ("Serviço legado",)
        ).fetchone()["id"]

        conn.execute(
            "INSERT INTO barbers (name, active) VALUES (?, 1)",
            ("Barbeiro legado",),
        )
        self.barber_id = conn.execute(
            "SELECT id FROM barbers WHERE name=?", ("Barbeiro legado",)
        ).fetchone()["id"]

        conn.execute(
            """INSERT INTO appointments
               (user_id, barber_id, service_id, appointment_date, start_time, end_time, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (self.user_id, self.barber_id, self.service_id,
             "2026-11-10", "10:00", "10:30", "scheduled"),
        )
        self.appointment_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        conn.execute(
            """INSERT INTO orders
               (user_id, customer_name, customer_phone, address, total, status, payment_method)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (self.user_id, "Cliente Legado", "", "", 49.90, "pending", "pix"),
        )
        self.order_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
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

    def test_database_initialization_preserves_existing_appointments_and_orders(self):
        # Reexecutar a inicialização simula a migração/atualização da aplicação.
        database.init_db()

        conn = database.get_db()
        appointment = conn.execute(
            "SELECT id, user_id, barber_id, service_id, status FROM appointments WHERE id=?",
            (self.appointment_id,),
        ).fetchone()
        order = conn.execute(
            "SELECT id, user_id, customer_name, total, status FROM orders WHERE id=?",
            (self.order_id,),
        ).fetchone()
        conn.close()

        self.assertIsNotNone(appointment)
        self.assertEqual(appointment["user_id"], self.user_id)
        self.assertEqual(appointment["barber_id"], self.barber_id)
        self.assertEqual(appointment["service_id"], self.service_id)
        self.assertEqual(appointment["status"], "scheduled")

        self.assertIsNotNone(order)
        self.assertEqual(order["user_id"], self.user_id)
        self.assertEqual(order["customer_name"], "Cliente Legado")
        self.assertAlmostEqual(order["total"], 49.90)
        self.assertEqual(order["status"], "pending")

    def test_customer_deactivation_fields_do_not_delete_related_records(self):
        conn = database.get_db()
        conn.execute(
            "UPDATE users SET active=0, session_version=session_version+1 WHERE id=?",
            (self.user_id,),
        )
        conn.commit()

        user = conn.execute(
            "SELECT active, session_version FROM users WHERE id=?", (self.user_id,)
        ).fetchone()
        appointment_count = conn.execute(
            "SELECT COUNT(*) FROM appointments WHERE user_id=?", (self.user_id,)
        ).fetchone()[0]
        order_count = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id=?", (self.user_id,)
        ).fetchone()[0]
        conn.close()

        self.assertEqual(user["active"], 0)
        self.assertEqual(user["session_version"], 1)
        self.assertEqual(appointment_count, 1)
        self.assertEqual(order_count, 1)


if __name__ == "__main__":
    unittest.main()
