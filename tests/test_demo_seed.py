"""Testes do gerador de dados isolados para demonstração."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from auth import verify_password


ROOT = Path(__file__).resolve().parents[1]
SEED_SCRIPT = ROOT / "seed_demo.py"


class DemoSeedTests(unittest.TestCase):
    def test_demo_seed_isolated_repeatable_and_financially_consistent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            demo_db = temp / "barberflow.demo.db"
            operational_db = temp / "operational.db"
            env = os.environ.copy()
            env["DATABASE_PATH"] = str(operational_db)

            first = subprocess.run(
                [sys.executable, str(SEED_SCRIPT), "--db", str(demo_db), "--admin-email", "demo.admin@barberflow.local"],
                cwd=ROOT, env=env, text=True, capture_output=True, timeout=120,
            )
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertTrue(demo_db.exists())
            self.assertFalse(operational_db.exists())
            self.assertIn("BASE DE DEMONSTRAÇÃO CRIADA", first.stdout)

            password_line = next(
                line for line in first.stdout.splitlines()
                if line.startswith("Senha inicial (guarde agora): ")
            )
            password = password_line.split(": ", 1)[1]
            self.assertGreaterEqual(len(password), 20)

            conn = sqlite3.connect(demo_db)
            conn.row_factory = sqlite3.Row
            admin = conn.execute(
                "SELECT password_hash, role, first_access_required FROM users WHERE email=?",
                ("demo.admin@barberflow.local",),
            ).fetchone()
            self.assertIsNotNone(admin)
            self.assertEqual(admin["role"], "admin")
            self.assertEqual(admin["first_access_required"], 0)
            self.assertTrue(verify_password(password, admin["password_hash"]))

            orders_before = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            tx_before = conn.execute("SELECT COUNT(*) FROM financial_transactions").fetchone()[0]
            self.assertGreaterEqual(orders_before, 20)
            self.assertGreaterEqual(tx_before, 50)
            statuses = {
                row["status"] for row in conn.execute("SELECT DISTINCT status FROM orders")
            }
            self.assertEqual(statuses, {"paid", "pending", "cancelled"})

            # O saldo físico deve ser igual à soma da trilha de movimentações.
            mismatch = conn.execute("""
                SELECT p.id, p.stock, COALESCE(SUM(m.quantity),0) AS movement_balance
                FROM products p
                LEFT JOIN stock_movements m ON m.product_id=p.id
                GROUP BY p.id
                HAVING p.stock != movement_balance
            """).fetchall()
            self.assertEqual(mismatch, [])

            # Há lançamentos em seis meses fechados, não em datas futuras do mês atual.
            months = conn.execute("""
                SELECT COUNT(DISTINCT substr(occurred_on,1,7))
                FROM financial_transactions
            """).fetchone()[0]
            self.assertEqual(months, 6)
            purchase_months = conn.execute("""
                SELECT COUNT(DISTINCT substr(created_at,1,7))
                FROM stock_movements WHERE movement_type='purchase'
            """).fetchone()[0]
            self.assertEqual(purchase_months, 6)
            stock_purchase_expenses = conn.execute("""
                SELECT COUNT(*) FROM financial_transactions
                WHERE transaction_type='expense' AND category='Estoque' AND status='paid'
            """).fetchone()[0]
            self.assertEqual(stock_purchase_expenses, 6)
            exits = conn.execute("""
                SELECT COUNT(*) FROM stock_movements
                WHERE movement_type='sale' AND quantity < 0
            """).fetchone()[0]
            self.assertGreater(exits, 0)
            conn.close()

            second = subprocess.run(
                [sys.executable, str(SEED_SCRIPT), "--db", str(demo_db)],
                cwd=ROOT, env=env, text=True, capture_output=True, timeout=120,
            )
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertIn("já preenchida", second.stdout)

            conn = sqlite3.connect(demo_db)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0], orders_before)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM financial_transactions").fetchone()[0],
                tx_before,
            )
            conn.close()


if __name__ == "__main__":
    unittest.main()
