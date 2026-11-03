"""Opt-in PostgreSQL smoke tests; require a dedicated local/CI database."""
import os
import sqlite3
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

from fastapi.testclient import TestClient
import psycopg
from psycopg import sql
from psycopg.rows import dict_row

import database as database_module
from migrate_sqlite_to_postgres import migrate_sqlite_connection


class PostgreSQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_url = os.getenv("BARBERFLOW_TEST_DATABASE_URL", "").strip()
        if not test_url:
            raise unittest.SkipTest("BARBERFLOW_TEST_DATABASE_URL is not configured")

        parsed = urlparse(test_url)
        database_name = parsed.path.lstrip("/")
        allowed_hosts = {"localhost", "127.0.0.1", "::1", "postgres"}
        if parsed.hostname not in allowed_hosts or not database_name.startswith("barberflow_test"):
            raise RuntimeError(
                "PostgreSQL tests require a dedicated barberflow_test database on a local/CI host"
            )

        cls.original_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = test_url
        import database
        cls.database = database
        database.init_db()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "original_database_url"):
            if cls.original_database_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = cls.original_database_url

    def test_postgres_schema_seed_and_hybrid_rows(self):
        conn = self.database.get_db()
        try:
            row = conn.execute("SELECT COUNT(*) AS total FROM services").fetchone()
            self.assertGreater(row["total"], 0)
            self.assertEqual(row["total"], row[0])
            self.assertIsNotNone(conn.execute(
                "SELECT value FROM settings WHERE key=?", ("shop_name",)
            ).fetchone())
        finally:
            conn.close()

    def test_parameter_adapter_preserves_question_marks_in_literals(self):
        conn = self.database.get_db()
        try:
            row = conn.execute("SELECT '?' AS literal, ? AS value", ("ok",)).fetchone()
            self.assertEqual(row["literal"], "?")
            self.assertEqual(row["value"], "ok")
        finally:
            conn.close()


    def test_sqlite_transaction_and_sqlite_integrity_error_compatibility(self):
        conn = self.database.get_db()
        email = f"pg-test-{uuid.uuid4().hex}@example.test"
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO users (name,email,password_hash,role) VALUES (?,?,?,?)",
                ("Integration Test", email, "not-a-real-password", "customer"),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO users (name,email,password_hash,role) VALUES (?,?,?,?)",
                    ("Duplicate", email, "not-a-real-password", "customer"),
                )
        finally:
            conn.rollback()
            conn.close()

    def test_sqlite_date_and_case_ordering_adapt_on_postgres(self):
        conn = self.database.get_db()
        try:
            today = conn.execute("SELECT date('now', 'localtime') AS today").fetchone()["today"]
            self.assertRegex(today, r"^\d{4}-\d{2}-\d{2}$")
            names = conn.execute("SELECT name FROM services ORDER BY name COLLATE NOCASE").fetchall()
            self.assertGreater(len(names), 0)
        finally:
            conn.close()


    def test_postgres_row_locks_used_by_booking_stock_and_order_flows(self):
        conn = self.database.get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("SELECT id FROM barbers WHERE id=? FOR UPDATE", (-1,)).fetchone()
            conn.execute("SELECT id FROM products WHERE id=? FOR UPDATE", (-1,)).fetchone()
            conn.execute("SELECT id FROM orders WHERE id=? FOR UPDATE", (-1,)).fetchone()
        finally:
            conn.rollback()
            conn.close()

    def test_postgresql_stock_purchase_and_order_payment_routes(self):
        """Exercise transactional write routes, not just SQL connectivity."""
        import app

        email = f"pg-route-{uuid.uuid4().hex}@example.test"
        checkout_customer = f"Cliente PostgreSQL {uuid.uuid4().hex[:8]}"
        conn = self.database.get_db()
        try:
            admin_id = conn.execute(
                "INSERT INTO users (name,email,password_hash,role) "
                "VALUES (?,?,?,?) RETURNING id",
                ("PostgreSQL Route Test", email, app.hash_password("Senha-PG-123"), "admin"),
            ).fetchone()["id"]
            product_id = conn.execute(
                "INSERT INTO products (name,price,cost_price,stock,category,active) "
                "VALUES (?,?,?,?,?,1) RETURNING id",
                (f"Produto teste {uuid.uuid4().hex[:8]}", 20, 5, 10, "Teste"),
            ).fetchone()["id"]
            order_id = conn.execute(
                "INSERT INTO orders (user_id,customer_name,customer_phone,address,total,status,payment_method) "
                "VALUES (?,?,?,?,?,?,?) RETURNING id",
                (admin_id, "Cliente PG", "", "", 79.90, "pending", "pix"),
            ).fetchone()["id"]
            conn.commit()
        finally:
            conn.close()

        with TestClient(app.app, follow_redirects=False) as client:
            login = client.post("/login", data={"email": email, "password": "Senha-PG-123"})
            self.assertIn(login.status_code, (302, 303))
            purchase = client.post(
                "/admin/estoque/entrada",
                data={"product_id": product_id, "quantity": 10, "unit_cost": "7.00", "note": "PG test"},
            )
            self.assertEqual(purchase.status_code, 303, purchase.text)
            first_payment = client.post(
                "/admin/pedidos/status", data={"order_id": order_id, "status": "paid"}
            )
            second_payment = client.post(
                "/admin/pedidos/status", data={"order_id": order_id, "status": "paid"}
            )
            self.assertEqual(first_payment.status_code, 303)
            self.assertEqual(second_payment.status_code, 303)
            client.cookies.set(app.CART_COOKIE, f'[{{"product_id":{product_id},"qty":2}}]')
            checkout = client.post(
                "/finalizar-pedido",
                data={
                    "customer_name": checkout_customer,
                    "customer_phone": "11999990000",
                    "address": "Rua de teste, 1",
                    "payment_method": "pix",
                },
            )
            self.assertEqual(checkout.status_code, 303, checkout.text)
            self.assertTrue(
                checkout.headers.get("location", "").startswith("/pedido-confirmado/"),
                checkout.headers.get("location"),
            )

        conn = self.database.get_db()
        try:
            product = conn.execute(
                "SELECT stock,cost_price FROM products WHERE id=?", (product_id,)
            ).fetchone()
            movement = conn.execute(
                "SELECT movement_type,quantity,unit_cost_cents FROM stock_movements "
                "WHERE product_id=? AND movement_type='purchase' ORDER BY id DESC LIMIT 1",
                (product_id,),
            ).fetchone()
            payments = conn.execute(
                "SELECT amount_cents,status FROM financial_transactions WHERE order_id=?",
                (order_id,),
            ).fetchall()
            self.assertEqual(product["stock"], 18)
            self.assertAlmostEqual(product["cost_price"], 6)
            self.assertEqual(movement["movement_type"], "purchase")
            self.assertEqual(movement["quantity"], 10)
            self.assertEqual(movement["unit_cost_cents"], 700)
            self.assertEqual(len(payments), 1)
            self.assertEqual(payments[0]["amount_cents"], 7990)
            self.assertEqual(payments[0]["status"], "paid")
            checkout_order = conn.execute(
                "SELECT id,total,status FROM orders WHERE customer_name=?",
                (checkout_customer,),
            ).fetchone()
            self.assertIsNotNone(checkout_order)
            self.assertEqual(checkout_order["status"], "pending")
            self.assertAlmostEqual(float(checkout_order["total"]), 40)
            sale = conn.execute(
                "SELECT movement_type,quantity,order_id FROM stock_movements "
                "WHERE order_id=? AND product_id=?",
                (checkout_order["id"], product_id),
            ).fetchone()
            self.assertIsNotNone(
                sale,
                f"expected product={product_id}; checkout order={checkout_order!r}; movements="
                f"{conn.execute('SELECT product_id,movement_type,quantity,order_id FROM stock_movements WHERE order_id=?', (checkout_order['id'],)).fetchall()!r}",
            )
            self.assertEqual(sale["movement_type"], "sale")
            self.assertEqual(sale["quantity"], -2)
        finally:
            conn.close()

    def test_concurrent_checkout_never_oversells_stock(self):
        import app

        product_name = f"Concorrente {uuid.uuid4().hex[:10]}"
        conn = self.database.get_db()
        try:
            product_id = conn.execute(
                "INSERT INTO products (name,price,cost_price,stock,category,active) "
                "VALUES (?,?,0,1,'Teste',1) RETURNING id",
                (product_name, 15),
            ).fetchone()["id"]
            conn.commit()
        finally:
            conn.close()

        def checkout(index):
            customer_name = f"Checkout concorrente {uuid.uuid4().hex[:8]}"
            with TestClient(app.app, follow_redirects=False) as client:
                client.cookies.set(
                    app.CART_COOKIE, f'[{{"product_id":{product_id},"qty":1}}]'
                )
                response = client.post(
                    "/finalizar-pedido",
                    data={
                        "customer_name": customer_name,
                        "customer_phone": f"1199999000{index}",
                        "address": "Endereço de teste",
                        "payment_method": "pix",
                    },
                )
                return response.status_code, customer_name, response.text

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(checkout, (1, 2)))

        self.assertCountEqual([result[0] for result in results], [303, 409])
        successful_customer = next(name for status, name, _ in results if status == 303)
        conn = self.database.get_db()
        try:
            product = conn.execute(
                "SELECT stock FROM products WHERE id=?", (product_id,)
            ).fetchone()
            orders = conn.execute(
                "SELECT id FROM orders WHERE customer_name=?", (successful_customer,)
            ).fetchall()
            movements = conn.execute(
                "SELECT quantity FROM stock_movements WHERE product_id=? AND movement_type='sale'",
                (product_id,),
            ).fetchall()
            self.assertEqual(product["stock"], 0)
            self.assertEqual(len(orders), 1)
            self.assertEqual(len(movements), 1)
            self.assertEqual(movements[0]["quantity"], -1)
        finally:
            conn.close()

    def test_concurrent_booking_serializes_on_barber(self):
        import app

        email = f"pg-booking-{uuid.uuid4().hex}@example.test"
        password = "Senha-PG-123"
        appointment_date = date.today() + timedelta(days=28)
        while appointment_date.isoweekday() == 7:
            appointment_date += timedelta(days=1)
        conn = self.database.get_db()
        try:
            customer_id = conn.execute(
                "INSERT INTO users (name,email,password_hash,role) "
                "VALUES (?,?,?,?) RETURNING id",
                ("Cliente Concurrente", email, app.hash_password(password), "customer"),
            ).fetchone()["id"]
            barber_id = conn.execute(
                "INSERT INTO barbers (name,active,work_days) VALUES (?,1,'[1,2,3,4,5,6]') RETURNING id",
                (f"Barbeiro concorrente {uuid.uuid4().hex[:8]}",),
            ).fetchone()["id"]
            service_id = conn.execute(
                "SELECT id FROM services WHERE active=1 ORDER BY id LIMIT 1"
            ).fetchone()["id"]
            conn.commit()
        finally:
            conn.close()

        def book(_):
            with TestClient(app.app, follow_redirects=False) as client:
                login = client.post("/login", data={"email": email, "password": password})
                if login.status_code not in (302, 303):
                    return login.status_code, login.text
                response = client.post(
                    "/api/agendar",
                    json={
                        "barber_id": barber_id,
                        "service_id": service_id,
                        "date": appointment_date.isoformat(),
                        "start_time": "10:00",
                    },
                )
                return response.status_code, response.text

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(book, (1, 2)))

        self.assertCountEqual([status for status, _ in results], [200, 409], results)
        conn = self.database.get_db()
        try:
            bookings = conn.execute(
                "SELECT COUNT(*) AS total FROM appointments "
                "WHERE barber_id=? AND appointment_date=? AND start_time='10:00' AND status='scheduled'",
                (barber_id, appointment_date.isoformat()),
            ).fetchone()["total"]
            self.assertEqual(bookings, 1)
        finally:
            conn.close()

    def test_sqlite_to_postgresql_import_preserves_rows_relations_and_sequences(self):
        """Migrate an isolated SQLite fixture; production databases are never used."""
        original_db_path = database_module.DB_PATH
        original_url = os.environ.pop("DATABASE_URL", None)
        original_admin_email = os.environ.pop("INITIAL_ADMIN_EMAIL", None)
        original_admin_password = os.environ.pop("INITIAL_ADMIN_PASSWORD", None)
        source_dir = tempfile.TemporaryDirectory()
        source_path = Path(source_dir.name) / "legacy.sqlite"
        target_schema = f"migration_test_{uuid.uuid4().hex[:12]}"
        target = psycopg.connect(
            os.environ["BARBERFLOW_TEST_DATABASE_URL"],
            connect_timeout=10,
            row_factory=dict_row,
        )
        try:
            database_module.DB_PATH = str(source_path)
            database_module.init_db()
            source = sqlite3.connect(source_path)
            source.row_factory = sqlite3.Row
            user_id = source.execute(
                "INSERT INTO users (name,email,password_hash,role) VALUES (?,?,?,?) RETURNING id",
                ("Migração Teste", f"migration-{uuid.uuid4().hex}@example.test", "legacy-hash", "customer"),
            ).fetchone()["id"]
            barber_user_id = source.execute(
                "INSERT INTO users (name,email,password_hash,role) VALUES (?,?,?,?) RETURNING id",
                ("Barbeiro Teste", f"barber-migration-{uuid.uuid4().hex}@example.test", "legacy-hash", "barber"),
            ).fetchone()["id"]
            barber_id = source.execute(
                "INSERT INTO barbers (user_id,name) VALUES (?,?) RETURNING id",
                (barber_user_id, "Barbeiro Teste"),
            ).fetchone()["id"]
            service_id = source.execute("SELECT id FROM services ORDER BY id LIMIT 1").fetchone()["id"]
            product_id = source.execute("SELECT id FROM products ORDER BY id LIMIT 1").fetchone()["id"]
            appointment_id = source.execute(
                """INSERT INTO appointments
                   (user_id,barber_id,service_id,appointment_date,start_time,end_time,status,service_price_cents)
                   VALUES (?,?,?,'2030-01-02','10:00','10:30','completed',3500) RETURNING id""",
                (user_id, barber_id, service_id),
            ).fetchone()["id"]
            order_id = source.execute(
                """INSERT INTO orders (user_id,customer_name,total,status)
                   VALUES (?, 'Migração Teste', 49.9, 'paid') RETURNING id""",
                (user_id,),
            ).fetchone()["id"]
            source.execute(
                """INSERT INTO order_items (order_id,product_id,product_name,quantity,price)
                   VALUES (?,?,?,?,?)""",
                (order_id, product_id, "Produto legado", 1, 49.9),
            )
            source.execute(
                """INSERT INTO stock_movements
                   (product_id,movement_type,quantity,unit_cost_cents,order_id)
                   VALUES (?,'sale',-1,1200,?)""",
                (product_id, order_id),
            )
            source.execute(
                """INSERT INTO financial_transactions
                   (transaction_type,category,description,amount_cents,occurred_on,status,
                    barber_id,appointment_id,created_by)
                   VALUES ('income','Serviços','Atendimento legado',3500,'2030-01-02',
                           'paid',?,?,?)""",
                (barber_id, appointment_id, user_id),
            )
            source.commit()
            source.close()

            source_counts = self._sqlite_table_counts(source_path)
            target.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(target_schema))
            )
            target.commit()
            target.execute(
                sql.SQL("SET search_path TO {}").format(sql.Identifier(target_schema))
            )
            target.commit()

            imported_counts = migrate_sqlite_connection(source_path, target)
            self.assertEqual(imported_counts, source_counts)
            appointment = target.execute(
                "SELECT user_id,barber_id,service_id,status,service_price_cents "
                "FROM appointments WHERE id=%s",
                (appointment_id,),
            ).fetchone()
            self.assertEqual(appointment["user_id"], user_id)
            self.assertEqual(appointment["barber_id"], barber_id)
            self.assertEqual(appointment["service_id"], service_id)
            self.assertEqual(appointment["status"], "completed")
            self.assertEqual(appointment["service_price_cents"], 3500)
            self.assertEqual(
                target.execute(
                    "SELECT COUNT(*) AS total FROM financial_transactions WHERE appointment_id=%s",
                    (appointment_id,),
                ).fetchone()["total"],
                1,
            )

            next_user_id = target.execute(
                "INSERT INTO users (name,email,password_hash,role) VALUES (%s,%s,%s,%s) RETURNING id",
                ("Depois da migração", f"after-{uuid.uuid4().hex}@example.test", "hash", "customer"),
            ).fetchone()["id"]
            self.assertGreater(next_user_id, max(user_id, barber_user_id))
            target.rollback()

            # Re-running must fail closed rather than merging/duplicating rows.
            with self.assertRaisesRegex(ValueError, "não está vazio"):
                migrate_sqlite_connection(source_path, target)
            self.assertEqual(
                target.execute(
                    "SELECT COUNT(*) AS total FROM appointments WHERE id=%s", (appointment_id,)
                ).fetchone()["total"],
                1,
            )
        finally:
            try:
                target.rollback()
                target.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        sql.Identifier(target_schema)
                    )
                )
                target.commit()
            finally:
                target.close()
                source_dir.cleanup()
                database_module.DB_PATH = original_db_path
                if original_url is not None:
                    os.environ["DATABASE_URL"] = original_url
                if original_admin_email is not None:
                    os.environ["INITIAL_ADMIN_EMAIL"] = original_admin_email
                if original_admin_password is not None:
                    os.environ["INITIAL_ADMIN_PASSWORD"] = original_admin_password

    @staticmethod
    def _sqlite_table_counts(path):
        source = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
        try:
            return {
                table: source.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                for (table,) in source.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                if table in {
                    "users", "services", "products", "barbers", "appointments",
                    "orders", "order_items", "settings", "stock_movements", "portfolio",
                    "auth_login_attempts", "password_reset_tokens",
                    "financial_transactions", "barber_commission_settings",
                }
            }
        finally:
            source.close()


if __name__ == "__main__":
    unittest.main()
