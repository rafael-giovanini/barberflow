"""Testes de integração para autenticação e permissões do BarberFlow.

Usa um banco SQLite temporário por teste; nenhum banco de desenvolvimento/produção
é aberto ou alterado por esta suíte.
"""
import hashlib
import importlib
import os
import tempfile
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import database


class SecurityRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        database.DB_PATH = os.path.join(self.temp_dir.name, "barberflow-security-test.db")
        self.env = patch.dict(os.environ, {
            "SECRET_KEY": "test-secret-key-only-for-automated-tests",
            "INITIAL_ADMIN_EMAIL": "",
            "INITIAL_ADMIN_PASSWORD": "",
            "APP_BASE_URL": "",
            "SMTP_HOST": "",
            "SMTP_FROM": "",
        })
        self.env.start()

        # Importar/recarregar depois de apontar para o banco temporário faz a
        # inicialização da aplicação ocorrer isoladamente.
        import app as app_module
        self.app_module = importlib.reload(app_module)
        self.client = TestClient(self.app_module.app, follow_redirects=False)
        self._create_user("Admin de Teste", "admin@example.test", "admin")
        self._create_user("Barbeiro de Teste", "barber@example.test", "barber")
        self._create_user("Cliente de Teste", "cliente@example.test", "customer")
        self._create_user("Outro Cliente", "outro@example.test", "customer")

    def tearDown(self):
        self.client.close()
        database.DB_PATH = self.original_db_path
        self.env.stop()
        self.temp_dir.cleanup()

    def _create_user(self, name, email, role, password="SenhaTeste-123"):
        db = self.app_module.get_db()
        db.execute(
            """INSERT INTO users (name, email, phone, password_hash, role)
               VALUES (?, ?, '', ?, ?)""",
            (name, email, self.app_module.hash_password(password), role),
        )
        db.commit()
        db.close()

    def _login(self, email, password="SenhaTeste-123"):
        return self.client.post("/login", data={"email": email, "password": password})

    def test_admin_can_open_customer_management(self):
        self._login("admin@example.test")
        response = self.client.get("/admin/clientes")
        self.assertEqual(response.status_code, 200)

    def test_customer_cannot_open_admin_customer_management(self):
        self._login("cliente@example.test")
        response = self.client.get("/admin/clientes")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")

    def test_barber_cannot_open_admin_only_customer_management(self):
        self._login("barber@example.test")
        response = self.client.get("/admin/clientes")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")

    def test_unauthenticated_user_cannot_open_customer_management(self):
        response = self.client.get("/admin/clientes")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")

    def test_customer_cannot_create_customer_through_staff_route(self):
        self._login("cliente@example.test")
        response = self.client.post("/admin/clientes/novo", data={
            "name": "Cliente Indevido",
            "email": "indevido@example.test",
            "phone": "",
            "password": "SenhaTeste-123",
            "confirm_password": "SenhaTeste-123",
        })
        self.assertEqual(response.status_code, 303)
        db = self.app_module.get_db()
        row = db.execute("SELECT id FROM users WHERE email=?", ("indevido@example.test",)).fetchone()
        db.close()
        self.assertIsNone(row)

    def test_wrong_current_password_does_not_change_password(self):
        self._login("cliente@example.test")
        response = self.client.post("/minha-conta/senha", data={
            "current_password": "senha-incorreta",
            "new_password": "NovaSenha-123",
            "confirm_password": "NovaSenha-123",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("A senha atual está incorreta.", response.text)
        self.client.get("/logout")
        bad_login = self._login("cliente@example.test", "NovaSenha-123")
        self.assertEqual(bad_login.status_code, 200)
        good_login = self._login("cliente@example.test", "SenhaTeste-123")
        self.assertEqual(good_login.status_code, 303)

    def test_disabled_user_cannot_login(self):
        db = self.app_module.get_db()
        db.execute("UPDATE users SET active=0 WHERE email=?", ("cliente@example.test",))
        db.commit()
        db.close()
        response = self._login("cliente@example.test")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("barbearia_session", response.cookies)

    def test_password_reset_token_is_single_use_and_revokes_existing_session(self):
        self._login("cliente@example.test")
        db = self.app_module.get_db()
        user = db.execute("SELECT id FROM users WHERE email=?", ("cliente@example.test",)).fetchone()
        raw_token = "token-de-teste-nao-utilizar-em-producao"
        now = datetime.now(timezone.utc)
        db.execute(
            """INSERT INTO password_reset_tokens
               (user_id, email, token_hash, expires_at, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user["id"], "cliente@example.test",
             hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
             (now + timedelta(minutes=30)).isoformat(), now.isoformat()),
        )
        db.commit()
        db.close()

        response = self.client.post("/redefinir-senha", data={
            "token": raw_token,
            "new_password": "SenhaNova-456",
            "confirm_password": "SenhaNova-456",
        })
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?senha_redefinida=1")

        # A troca de senha deve invalidar a sessão que já estava aberta.
        account_page = self.client.get("/minha-conta")
        self.assertEqual(account_page.status_code, 303)
        self.assertEqual(account_page.headers["location"], "/login")

        # O token não pode ser reutilizado para uma segunda troca.
        reused = self.client.post("/redefinir-senha", data={
            "token": raw_token,
            "new_password": "OutraSenha-789",
            "confirm_password": "OutraSenha-789",
        })
        self.assertEqual(reused.status_code, 200)
        self.assertIn("O link é inválido, expirou ou já foi utilizado.", reused.text)

        self.client.get("/logout")
        self.assertEqual(self._login("cliente@example.test", "SenhaNova-456").status_code, 303)
        self.client.get("/logout")
        self.assertEqual(self._login("cliente@example.test", "OutraSenha-789").status_code, 200)

    def test_expired_password_reset_token_is_rejected(self):
        db = self.app_module.get_db()
        user = db.execute("SELECT id FROM users WHERE email=?", ("cliente@example.test",)).fetchone()
        raw_token = "token-expirado-de-teste"
        now = datetime.now(timezone.utc)
        db.execute(
            """INSERT INTO password_reset_tokens
               (user_id, email, token_hash, expires_at, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user["id"], "cliente@example.test",
             hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
             (now - timedelta(minutes=1)).isoformat(),
             (now - timedelta(minutes=31)).isoformat()),
        )
        db.commit()
        db.close()

        response = self.client.post("/redefinir-senha", data={
            "token": raw_token,
            "new_password": "SenhaNova-456",
            "confirm_password": "SenhaNova-456",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("O link é inválido, expirou ou já foi utilizado.", response.text)
        self.assertEqual(self._login("cliente@example.test", "SenhaTeste-123").status_code, 303)


    def test_successful_password_change_revokes_session_and_requires_new_login(self):
        self._login("cliente@example.test")
        response = self.client.post("/minha-conta/senha", data={
            "current_password": "SenhaTeste-123",
            "new_password": "SenhaNova-456",
            "confirm_password": "SenhaNova-456",
        })
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?senha_alterada=1")
        self.assertNotIn("barbearia_session", self.client.cookies)

        # A sessão anterior não deve continuar autorizada após a troca.
        account_page = self.client.get("/minha-conta")
        self.assertEqual(account_page.status_code, 303)
        self.assertEqual(account_page.headers["location"], "/login")

        # A senha nova funciona e a anterior deixa de funcionar.
        self.assertEqual(self._login("cliente@example.test", "SenhaNova-456").status_code, 303)
        self.client.get("/logout")
        self.assertEqual(self._login("cliente@example.test", "SenhaTeste-123").status_code, 200)


    def test_customer_cannot_change_another_customer_status(self):
        self._login("cliente@example.test")
        db = self.app_module.get_db()
        target = db.execute(
            "SELECT id, active FROM users WHERE email=?",
            ("outro@example.test",),
        ).fetchone()
        db.close()

        response = self.client.post("/admin/clientes/status", data={
            "customer_id": target["id"],
            "active": "0",
        })
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")

        db = self.app_module.get_db()
        unchanged = db.execute(
            "SELECT active FROM users WHERE id=?", (target["id"],)
        ).fetchone()
        db.close()
        self.assertEqual(unchanged["active"], target["active"])

    def test_admin_deactivation_revokes_existing_customer_session(self):
        self._login("admin@example.test")
        db = self.app_module.get_db()
        target = db.execute(
            "SELECT id FROM users WHERE email=?", ("cliente@example.test",)
        ).fetchone()
        db.close()

        # Confirma que o cliente tinha uma sessão válida antes da desativação.
        customer_client = TestClient(self.app_module.app, follow_redirects=False)
        try:
            customer_client.post(
                "/login",
                data={"email": "cliente@example.test", "password": "SenhaTeste-123"},
            )
            self.assertEqual(customer_client.get("/minha-conta").status_code, 200)

            response = self.client.post("/admin/clientes/status", data={
                "customer_id": target["id"],
                "active": "0",
            })
            self.assertEqual(response.status_code, 303)

            # A sessão já emitida também deve deixar de ser aceita.
            account_page = customer_client.get("/minha-conta")
            self.assertEqual(account_page.status_code, 303)
            self.assertEqual(account_page.headers["location"], "/login")
        finally:
            customer_client.close()


    def test_duplicate_email_does_not_overwrite_another_customer(self):
        self._login("admin@example.test")
        db = self.app_module.get_db()
        target = db.execute(
            "SELECT id, name, email, phone FROM users WHERE email=?",
            ("cliente@example.test",),
        ).fetchone()
        db.close()

        response = self.client.post("/admin/clientes/salvar", data={
            "customer_id": target["id"],
            "name": "Nome que não deve ser salvo",
            "email": "outro@example.test",
            "phone": "11999999999",
        })
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/clientes?erro=email")

        db = self.app_module.get_db()
        unchanged = db.execute(
            "SELECT name, email, phone FROM users WHERE id=?", (target["id"],)
        ).fetchone()
        db.close()
        self.assertEqual(dict(unchanged), {
            "name": target["name"],
            "email": target["email"],
            "phone": target["phone"],
        })

    def test_invalid_customer_data_is_rejected_without_changes(self):
        self._login("admin@example.test")
        db = self.app_module.get_db()
        target = db.execute(
            "SELECT id, name, email, phone FROM users WHERE email=?",
            ("cliente@example.test",),
        ).fetchone()
        db.close()

        response = self.client.post("/admin/clientes/salvar", data={
            "customer_id": target["id"],
            "name": "   ",
            "email": "email-invalido",
            "phone": "11999999999",
        })
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/clientes?erro=dados")

        db = self.app_module.get_db()
        unchanged = db.execute(
            "SELECT name, email, phone FROM users WHERE id=?", (target["id"],)
        ).fetchone()
        db.close()
        self.assertEqual(dict(unchanged), {
            "name": target["name"],
            "email": target["email"],
            "phone": target["phone"],
        })

    def test_customer_edit_route_cannot_modify_admin_or_barber_accounts(self):
        self._login("admin@example.test")
        db = self.app_module.get_db()
        targets = db.execute(
            "SELECT id, name, email, phone, role FROM users WHERE role IN ('admin', 'barber')"
        ).fetchall()
        db.close()

        for target in targets:
            with self.subTest(role=target["role"], email=target["email"]):
                response = self.client.post("/admin/clientes/salvar", data={
                    "customer_id": target["id"],
                    "name": "Conta alterada indevidamente",
                    "email": "alterada@example.test",
                    "phone": "11999999999",
                })
                self.assertEqual(response.status_code, 303)

                db = self.app_module.get_db()
                unchanged = db.execute(
                    "SELECT name, email, phone, role FROM users WHERE id=?",
                    (target["id"],),
                ).fetchone()
                db.close()
                self.assertEqual(dict(unchanged), {
                    "name": target["name"],
                    "email": target["email"],
                    "phone": target["phone"],
                    "role": target["role"],
                })


    def test_duplicate_email_on_customer_creation_does_not_create_account(self):
        self._login("admin@example.test")
        response = self.client.post("/admin/clientes/novo", data={
            "name": "Cadastro Duplicado",
            "email": " OUTRO@example.test ",
            "phone": "11988887777",
            "password": "SenhaNova-456",
            "confirm_password": "SenhaNova-456",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("Já existe uma conta cadastrada com esse e-mail.", response.text)

        db = self.app_module.get_db()
        rows = db.execute(
            "SELECT id FROM users WHERE email=?", ("outro@example.test",)
        ).fetchall()
        db.close()
        self.assertEqual(len(rows), 1)

    def test_customer_status_route_cannot_change_admin_or_barber_status(self):
        self._login("admin@example.test")
        db = self.app_module.get_db()
        targets = db.execute(
            "SELECT id, active, session_version, role FROM users WHERE role IN ('admin', 'barber')"
        ).fetchall()
        db.close()

        for target in targets:
            with self.subTest(role=target["role"]):
                response = self.client.post("/admin/clientes/status", data={
                    "customer_id": target["id"],
                    "active": "0" if target["active"] else "1",
                })
                self.assertEqual(response.status_code, 303)

                db = self.app_module.get_db()
                unchanged = db.execute(
                    "SELECT active, session_version, role FROM users WHERE id=?",
                    (target["id"],),
                ).fetchone()
                db.close()
                self.assertEqual(dict(unchanged), {
                    "active": target["active"],
                    "session_version": target["session_version"],
                    "role": target["role"],
                })

    def test_new_customer_rejects_short_or_mismatched_password(self):
        self._login("admin@example.test")
        cases = [
            ("short", "short", "A senha deve ter pelo menos 6 caracteres."),
            ("SenhaNova-456", "diferente", "A confirmação da senha não confere."),
        ]
        for index, (password, confirmation, message) in enumerate(cases):
            email = f"invalid-password-{index}@example.test"
            with self.subTest(email=email):
                response = self.client.post("/admin/clientes/novo", data={
                    "name": "Cliente Inválido",
                    "email": email,
                    "phone": "",
                    "password": password,
                    "confirm_password": confirmation,
                })
                self.assertEqual(response.status_code, 200)
                self.assertIn(message, response.text)

                db = self.app_module.get_db()
                row = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
                db.close()
                self.assertIsNone(row)


    def test_customer_edit_nonexistent_id_does_not_report_success(self):
        self._login("admin@example.test")
        db = self.app_module.get_db()
        nonexistent_id = db.execute("SELECT COALESCE(MAX(id), 0) + 1000 FROM users").fetchone()[0]
        db.close()

        response = self.client.post("/admin/clientes/salvar", data={
            "customer_id": nonexistent_id,
            "name": "Cliente Inexistente",
            "email": "inexistente@example.test",
            "phone": "",
        })
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/clientes?erro=nao_encontrado")

    def test_customer_status_nonexistent_id_does_not_change_any_account(self):
        self._login("admin@example.test")
        db = self.app_module.get_db()
        before = db.execute(
            "SELECT id, active, session_version FROM users ORDER BY id"
        ).fetchall()
        nonexistent_id = max(row["id"] for row in before) + 1000
        db.close()

        response = self.client.post("/admin/clientes/status", data={
            "customer_id": nonexistent_id,
            "active": "0",
        })
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/clientes?erro=nao_encontrado")

        db = self.app_module.get_db()
        after = db.execute(
            "SELECT id, active, session_version FROM users ORDER BY id"
        ).fetchall()
        db.close()
        self.assertEqual([dict(row) for row in after], [dict(row) for row in before])


if __name__ == "__main__":
    unittest.main()
