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


if __name__ == "__main__":
    unittest.main()
