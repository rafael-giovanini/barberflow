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
            ("short", "short", "A senha deve ter pelo menos 8 caracteres."),
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


    def test_security_headers_are_present_on_responses(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertEqual(response.headers["referrer-policy"], "strict-origin-when-cross-origin")
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_repeated_failed_logins_are_rate_limited(self):
        for _ in range(10):
            response = self._login("cliente@example.test", "senha-incorreta")
            self.assertEqual(response.status_code, 200)
        blocked = self._login("cliente@example.test", "SenhaTeste-123")
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Muitas tentativas de acesso", blocked.text)

    def test_successful_login_sets_http_only_lax_cookie(self):
        response = self._login("cliente@example.test")
        self.assertEqual(response.status_code, 303)
        cookie = response.headers.get("set-cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=lax", cookie)


    def test_cross_origin_state_changing_request_is_rejected(self):
        response = self.client.post(
            "/login",
            data={"email": "cliente@example.test", "password": "SenhaTeste-123"},
            headers={"Origin": "https://attacker.example"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("Origem da requisição não permitida", response.text)


    def test_successful_login_clears_prior_failed_attempts(self):
        for _ in range(3):
            self._login("cliente@example.test", "senha-incorreta")
        db = self.app_module.get_db()
        before = db.execute(
            "SELECT COUNT(*) AS total FROM auth_login_attempts "
            "WHERE email=? AND succeeded=0",
            ("cliente@example.test",),
        ).fetchone()["total"]
        db.close()
        self.assertEqual(before, 3)

        self.assertEqual(self._login("cliente@example.test").status_code, 303)
        db = self.app_module.get_db()
        after = db.execute(
            "SELECT COUNT(*) AS total FROM auth_login_attempts "
            "WHERE email=? AND client_ip=? AND succeeded=0",
            ("cliente@example.test", "testclient"),
        ).fetchone()["total"]
        db.close()
        self.assertEqual(after, 0)

    def test_password_hash_upgrade_keeps_legacy_hashes_verifiable(self):
        from auth import hash_password, verify_password
        legacy_hash = "pbkdf2$100000$73616c74$" + __import__("hashlib").pbkdf2_hmac(
            "sha256", b"SenhaTeste-123", b"73616c74", 100000
        ).hex()
        self.assertTrue(verify_password("SenhaTeste-123", legacy_hash))
        new_hash = hash_password("SenhaTeste-123")
        self.assertTrue(new_hash.startswith("pbkdf2$600000$"))
        self.assertTrue(verify_password("SenhaTeste-123", new_hash))


    def test_successful_login_upgrades_legacy_password_hash(self):
        import hashlib
        legacy_hash = "pbkdf2$100000$73616c74$" + hashlib.pbkdf2_hmac(
            "sha256", b"SenhaTeste-123", b"73616c74", 100000
        ).hex()
        db = self.app_module.get_db()
        db.execute(
            "UPDATE users SET password_hash=? WHERE email=?",
            (legacy_hash, "cliente@example.test"),
        )
        db.commit()
        db.close()

        response = self._login("cliente@example.test", "SenhaTeste-123")
        self.assertEqual(response.status_code, 303)

        db = self.app_module.get_db()
        stored_hash = db.execute(
            "SELECT password_hash FROM users WHERE email=?",
            ("cliente@example.test",),
        ).fetchone()["password_hash"]
        db.close()
        self.assertTrue(stored_hash.startswith("pbkdf2$600000$"))
        from auth import verify_password
        self.assertTrue(verify_password("SenhaTeste-123", stored_hash))


    def test_barber_cannot_change_global_settings(self):
        self._login("barber@example.test")
        before = self.app_module.get_settings().get("shop_name")
        response = self.client.post("/admin/configuracoes/salvar", data={"shop_name": "Alteração indevida"})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")
        self.assertEqual(self.app_module.get_settings().get("shop_name"), before)

    def test_barber_cannot_manage_barber_accounts(self):
        self._login("barber@example.test")
        response = self.client.post("/admin/barbeiros/salvar", data={
            "name": "Conta Indevida", "email": "novo-barber@example.test",
            "password": "SenhaNova-456", "work_days": ["1"],
        })
        self.assertEqual(response.status_code, 303)
        db = self.app_module.get_db()
        row = db.execute("SELECT id FROM users WHERE email=?", ("novo-barber@example.test",)).fetchone()
        db.close()
        self.assertIsNone(row)

    def test_appointment_status_rejects_invalid_values(self):
        self._login("admin@example.test")
        response = self.client.post("/admin/agenda/status", json={
            "appointment_id": 1, "status": "paid",
        })
        self.assertEqual(response.status_code, 400)

    def test_appointment_status_rejects_nonexistent_id(self):
        self._login("admin@example.test")
        response = self.client.post("/admin/agenda/status", json={
            "appointment_id": 999999, "status": "completed",
        })
        self.assertEqual(response.status_code, 404)

    def test_customer_cannot_view_another_customers_order(self):
        db = self.app_module.get_db()
        owner = db.execute("SELECT id FROM users WHERE email=?", ("outro@example.test",)).fetchone()
        db.execute(
            "INSERT INTO orders (user_id, customer_name, customer_phone, address, total, status) VALUES (?, ?, ?, ?, ?, ?)",
            (owner["id"], "Outro Cliente", "11999999999", "Endereço privado", 100, "pending"),
        )
        order_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()
        self._login("cliente@example.test")
        response = self.client.get(f"/pedido-confirmado/{order_id}")
        self.assertEqual(response.status_code, 404)

    def test_guest_order_receipt_requires_signed_receipt_cookie(self):
        db = self.app_module.get_db()
        db.execute(
            "INSERT INTO orders (user_id, customer_name, customer_phone, address, total, status) VALUES (NULL, ?, ?, ?, ?, ?)",
            ("Cliente Visitante", "11999999999", "Endereço privado", 100, "pending"),
        )
        order_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()
        response = self.client.get(f"/pedido-confirmado/{order_id}")
        self.assertEqual(response.status_code, 404)

    def test_cross_origin_rejection_still_has_security_headers(self):
        response = self.client.post(
            "/login",
            data={"email": "cliente@example.test", "password": "SenhaTeste-123"},
            headers={"Origin": "https://attacker.example"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")


    def test_password_reset_response_does_not_disclose_account_existence(self):
        unknown = self.client.post(
            "/esqueci-senha", data={"email": "nao-existe@example.test"}
        )
        known = self.client.post(
            "/esqueci-senha", data={"email": "cliente@example.test"}
        )
        self.assertEqual(unknown.status_code, 200)
        self.assertEqual(known.status_code, 200)
        self.assertEqual(unknown.text, known.text)
        self.assertIn("Se o endereço estiver cadastrado", unknown.text)

    def test_password_reset_with_unconfigured_smtp_does_not_create_token(self):
        response = self.client.post(
            "/esqueci-senha", data={"email": "cliente@example.test"}
        )
        self.assertEqual(response.status_code, 200)
        db = self.app_module.get_db()
        count = db.execute(
            """SELECT COUNT(*) AS total FROM password_reset_tokens
               WHERE email=?""",
            ("cliente@example.test",),
        ).fetchone()["total"]
        db.close()
        self.assertEqual(count, 0)

    def test_service_rejects_negative_price(self):
        self._login("admin@example.test")
        response = self.client.post("/admin/servicos/salvar", data={
            "name": "Servico invalido", "price": "-10", "duration_min": "30",
            "category": "Cabelo", "description": "",
        })
        self.assertEqual(response.status_code, 303)
        db = self.app_module.get_db()
        row = db.execute("SELECT id FROM services WHERE name=?", ("Servico invalido",)).fetchone()
        db.close()
        self.assertIsNone(row)

    def test_barber_cannot_change_another_barbers_appointment(self):
        db = self.app_module.get_db()
        barber_user = db.execute(
            "SELECT id FROM users WHERE email=?", ("barber@example.test",)
        ).fetchone()
        customer = db.execute(
            "SELECT id FROM users WHERE email=?", ("cliente@example.test",)
        ).fetchone()
        db.execute(
            "INSERT INTO barbers (user_id, name) VALUES (?, ?)",
            (barber_user["id"], "Barbeiro autenticado"),
        )
        own_barber_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO barbers (name) VALUES (?)", ("Outro barbeiro",))
        other_barber_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute(
            "INSERT INTO services (name, price, duration_min) VALUES (?, ?, ?)",
            ("Corte teste", 25, 30),
        )
        service_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute(
            """INSERT INTO appointments
               (user_id, barber_id, service_id, appointment_date, start_time, end_time)
               VALUES (?, ?, ?, '2099-01-01', '10:00', '10:30')""",
            (customer["id"], other_barber_id, service_id),
        )
        other_appointment_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute(
            """INSERT INTO appointments
               (user_id, barber_id, service_id, appointment_date, start_time, end_time)
               VALUES (?, ?, ?, '2099-01-01', '11:00', '11:30')""",
            (customer["id"], own_barber_id, service_id),
        )
        own_appointment_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()

        self._login("barber@example.test")
        denied = self.client.post("/admin/agenda/status", json={
            "appointment_id": other_appointment_id, "status": "completed",
        })
        allowed = self.client.post("/admin/agenda/status", json={
            "appointment_id": own_appointment_id, "status": "completed",
        })
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(allowed.status_code, 200)

        db = self.app_module.get_db()
        other_status = db.execute(
            "SELECT status FROM appointments WHERE id=?", (other_appointment_id,)
        ).fetchone()["status"]
        own_status = db.execute(
            "SELECT status FROM appointments WHERE id=?", (own_appointment_id,)
        ).fetchone()["status"]
        db.close()
        self.assertEqual(other_status, "scheduled")
        self.assertEqual(own_status, "completed")


    def test_cart_update_rejects_product_without_stock(self):
        db = self.app_module.get_db()
        db.execute(
            "INSERT INTO products (name, price, stock, active) VALUES (?, ?, ?, 1)",
            ("Produto sem estoque", 10.0, 0),
        )
        product_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()

        response = self.client.post(
            "/api/carrinho/update",
            json={"product_id": product_id, "qty": 1},
        )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.json()["ok"])
        self.assertIn("sem estoque", response.json()["error"])

    def test_product_rejects_negative_stock(self):
        self._login("admin@example.test")
        response = self.client.post("/admin/produtos/salvar", data={
            "name": "Produto estoque inválido", "price": "10",
            "stock": "-1", "category": "Teste", "description": "",
            "image_url": "",
        })
        self.assertEqual(response.status_code, 303)
        db = self.app_module.get_db()
        row = db.execute(
            "SELECT id FROM products WHERE name=?", ("Produto estoque inválido",)
        ).fetchone()
        db.close()
        self.assertIsNone(row)

    def test_product_rejects_non_http_image_url(self):
        self._login("admin@example.test")
        response = self.client.post("/admin/produtos/salvar", data={
            "name": "Produto URL inválida", "price": "10",
            "stock": "2", "category": "Teste", "description": "",
            "image_url": "javascript:alert(1)",
        })
        self.assertEqual(response.status_code, 303)
        db = self.app_module.get_db()
        row = db.execute(
            "SELECT id FROM products WHERE name=?", ("Produto URL inválida",)
        ).fetchone()
        db.close()
        self.assertIsNone(row)


    def test_financial_dashboard_is_admin_only(self):
        self._login("barber@example.test")
        response = self.client.get("/admin/financeiro")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")

        self.client.cookies.clear()
        self._login("admin@example.test")
        allowed = self.client.get("/admin/financeiro")
        self.assertEqual(allowed.status_code, 200)
        self.assertIn("Entradas recebidas", allowed.text)

    def test_financial_transaction_uses_cents_and_updates_summary(self):
        self._login("admin@example.test")
        response = self.client.post("/admin/financeiro/lancamento", data={
            "transaction_type": "income",
            "category": "Serviço",
            "description": "Recebimento teste",
            "amount": "125,90",
            "occurred_on": "2026-10-20",
            "payment_method": "Pix",
            "status": "paid",
        })
        self.assertEqual(response.status_code, 303)
        self.assertIn("salvo=1", response.headers["location"])

        db = self.app_module.get_db()
        row = db.execute(
            "SELECT amount_cents, transaction_type, status FROM financial_transactions "
            "WHERE description='Recebimento teste'"
        ).fetchone()
        db.close()
        self.assertEqual(dict(row), {
            "amount_cents": 12590, "transaction_type": "income", "status": "paid"
        })

        report = self.client.get("/admin/financeiro?inicio=2026-10-01&fim=2026-10-31")
        self.assertEqual(report.status_code, 200)
        self.assertIn("125.90", report.text)

    def test_financial_transaction_rejects_invalid_amount(self):
        self._login("admin@example.test")
        response = self.client.post("/admin/financeiro/lancamento", data={
            "transaction_type": "expense",
            "category": "Teste",
            "description": "Valor inválido",
            "amount": "-50",
            "occurred_on": "2026-10-20",
            "payment_method": "Dinheiro",
            "status": "paid",
        })
        self.assertEqual(response.status_code, 303)
        self.assertIn("erro=dados", response.headers["location"])
        db = self.app_module.get_db()
        row = db.execute(
            "SELECT id FROM financial_transactions WHERE description='Valor inválido'"
        ).fetchone()
        db.close()
        self.assertIsNone(row)

    def test_barber_cannot_create_financial_transaction(self):
        self._login("barber@example.test")
        response = self.client.post("/admin/financeiro/lancamento", data={
            "transaction_type": "expense",
            "category": "Teste",
            "description": "Despesa não autorizada",
            "amount": "10",
            "occurred_on": "2026-10-20",
            "payment_method": "Pix",
            "status": "paid",
        })
        self.assertEqual(response.status_code, 303)
        db = self.app_module.get_db()
        row = db.execute(
            "SELECT id FROM financial_transactions WHERE description='Despesa não autorizada'"
        ).fetchone()
        db.close()
        self.assertIsNone(row)

    def test_confirmed_financial_transaction_cannot_be_cancelled_without_reversal(self):
        db = self.app_module.get_db()
        db.execute("""
            INSERT INTO financial_transactions
                (transaction_type, category, description, amount_cents, occurred_on,
                 status, created_by)
            VALUES ('income', 'Serviços', 'Receita confirmada teste', 4550,
                    date('now'), 'paid', (SELECT id FROM users WHERE email='admin@example.test'))
        """)
        transaction_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()

        self._login("admin@example.test")
        response = self.client.post("/admin/financeiro/confirmar", data={
            "transaction_id": transaction_id, "status": "cancelled"
        })
        self.assertEqual(response.status_code, 303)
        self.assertIn("erro=estorno", response.headers["location"])

        db = self.app_module.get_db()
        row = db.execute(
            "SELECT status FROM financial_transactions WHERE id=?", (transaction_id,)
        ).fetchone()
        db.close()
        self.assertEqual(row["status"], "paid")

    def test_commission_rate_is_admin_only_and_validated(self):
        db = self.app_module.get_db()
        db.execute("INSERT INTO barbers (name, active) VALUES (?, 1)", ("Barbeiro financeiro",))
        barber_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()

        self._login("barber@example.test")
        denied = self.client.post("/admin/financeiro/comissao", data={
            "barber_id": barber_id, "commission_percent": "40"
        })
        self.assertEqual(denied.status_code, 303)

        self.client.cookies.clear()
        self._login("admin@example.test")
        invalid = self.client.post("/admin/financeiro/comissao", data={
            "barber_id": barber_id, "commission_percent": "150"
        })
        self.assertIn("erro=comissao", invalid.headers["location"])
        valid = self.client.post("/admin/financeiro/comissao", data={
            "barber_id": barber_id, "commission_percent": "40,5"
        })
        self.assertEqual(valid.status_code, 303)
        db = self.app_module.get_db()
        rate = db.execute(
            "SELECT commission_percent FROM barber_commission_settings WHERE barber_id=?",
            (barber_id,),
        ).fetchone()
        db.close()
        self.assertAlmostEqual(rate["commission_percent"], 40.5)


    def test_completed_appointment_creates_one_financial_income_and_can_be_reversed(self):
        db = self.app_module.get_db()
        db.execute("INSERT INTO barbers (name, active) VALUES ('Barbeiro Receita', 1)")
        barber_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("""
            INSERT INTO services (name, price, duration_min, active)
            VALUES ('Corte teste', 45.50, 30, 1)
        """)
        service_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("""
            INSERT INTO appointments
                (user_id, barber_id, service_id, appointment_date, start_time, end_time,
                 status, service_price_cents)
            VALUES ((SELECT id FROM users WHERE email='cliente@example.test'),
                    ?, ?, '2026-10-20', '10:00', '10:30', 'scheduled', 4550)
        """, (barber_id, service_id))
        appointment_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()

        self._login("admin@example.test")
        first = self.client.post("/admin/agenda/status", json={
            "appointment_id": appointment_id, "status": "completed"
        })
        second = self.client.post("/admin/agenda/status", json={
            "appointment_id": appointment_id, "status": "completed"
        })
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)

        db = self.app_module.get_db()
        rows = db.execute("""
            SELECT amount_cents, status, appointment_id
            FROM financial_transactions WHERE appointment_id=?
        """, (appointment_id,)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount_cents"], 4550)
        self.assertEqual(rows[0]["status"], "pending")
        db.close()

        cancelled = self.client.post("/admin/agenda/status", json={
            "appointment_id": appointment_id, "status": "cancelled"
        })
        self.assertEqual(cancelled.status_code, 200)
        db = self.app_module.get_db()
        row = db.execute(
            "SELECT status FROM financial_transactions WHERE appointment_id=?",
            (appointment_id,),
        ).fetchone()
        db.close()
        self.assertEqual(row["status"], "cancelled")


    def test_paid_appointment_income_cannot_be_cancelled_implicitly(self):
        db = self.app_module.get_db()
        db.execute("INSERT INTO barbers (name, active) VALUES ('Barbeiro Recebido', 1)")
        barber_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("""
            INSERT INTO services (name, price, duration_min, active)
            VALUES ('Corte recebido', 45.50, 30, 1)
        """)
        service_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("""
            INSERT INTO appointments
                (user_id, barber_id, service_id, appointment_date, start_time, end_time,
                 status, service_price_cents)
            VALUES ((SELECT id FROM users WHERE email='cliente@example.test'),
                    ?, ?, '2026-10-20', '10:00', '10:30', 'completed', 4550)
        """, (barber_id, service_id))
        appointment_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("""
            INSERT INTO financial_transactions
                (transaction_type, category, description, amount_cents, occurred_on,
                 status, barber_id, appointment_id)
            VALUES ('income', 'Serviços', 'Atendimento já recebido', 4550,
                    '2026-10-20', 'paid', ?, ?)
        """, (barber_id, appointment_id))
        db.commit()
        db.close()

        self._login("admin@example.test")
        response = self.client.post("/admin/agenda/status", json={
            "appointment_id": appointment_id, "status": "cancelled"
        })
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "recebimento_confirmado")

        db = self.app_module.get_db()
        appointment = db.execute(
            "SELECT status FROM appointments WHERE id=?", (appointment_id,)
        ).fetchone()
        transaction = db.execute(
            "SELECT status FROM financial_transactions WHERE appointment_id=?",
            (appointment_id,),
        ).fetchone()
        db.close()
        self.assertEqual(appointment["status"], "completed")
        self.assertEqual(transaction["status"], "paid")

    def test_barber_cannot_learn_paid_status_of_another_barbers_appointment(self):
        db = self.app_module.get_db()
        db.execute("INSERT INTO barbers (name, active) VALUES ('Outro barbeiro', 1)")
        barber_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("""
            INSERT INTO services (name, price, duration_min, active)
            VALUES ('Serviço reservado', 50.00, 30, 1)
        """)
        service_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("""
            INSERT INTO appointments
                (user_id, barber_id, service_id, appointment_date, start_time, end_time,
                 status, service_price_cents)
            VALUES ((SELECT id FROM users WHERE email='cliente@example.test'),
                    ?, ?, '2026-10-20', '10:00', '10:30', 'completed', 5000)
        """, (barber_id, service_id))
        appointment_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("""
            INSERT INTO financial_transactions
                (transaction_type, category, description, amount_cents, occurred_on,
                 status, barber_id, appointment_id)
            VALUES ('income', 'Serviços', 'Recebimento privado', 5000,
                    '2026-10-20', 'paid', ?, ?)
        """, (barber_id, appointment_id))
        db.commit()
        db.close()

        self._login("barber@example.test")
        response = self.client.post("/admin/agenda/status", json={
            "appointment_id": appointment_id, "status": "cancelled"
        })
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("recebimento confirmado", response.text.lower())

    def test_recompleting_paid_appointment_preserves_confirmed_income(self):
        db = self.app_module.get_db()
        db.execute("INSERT INTO barbers (name, active) VALUES ('Barbeiro Pagamento', 1)")
        barber_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("""
            INSERT INTO services (name, price, duration_min, active)
            VALUES ('Corte pago', 45.50, 30, 1)
        """)
        service_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("""
            INSERT INTO appointments
                (user_id, barber_id, service_id, appointment_date, start_time, end_time,
                 status, service_price_cents)
            VALUES ((SELECT id FROM users WHERE email='cliente@example.test'),
                    ?, ?, '2026-10-20', '10:00', '10:30', 'completed', 4550)
        """, (barber_id, service_id))
        appointment_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("""
            INSERT INTO financial_transactions
                (transaction_type, category, description, amount_cents, occurred_on,
                 status, barber_id, appointment_id)
            VALUES ('income', 'Serviços', 'Recebimento confirmado', 4550,
                    '2026-10-20', 'paid', ?, ?)
        """, (barber_id, appointment_id))
        db.commit()
        db.close()

        self._login("admin@example.test")
        response = self.client.post("/admin/agenda/status", json={
            "appointment_id": appointment_id, "status": "completed"
        })
        self.assertEqual(response.status_code, 200)

        db = self.app_module.get_db()
        row = db.execute("""
            SELECT status, amount_cents FROM financial_transactions
            WHERE appointment_id=?
        """, (appointment_id,)).fetchone()
        db.close()
        self.assertEqual(row["status"], "paid")
        self.assertEqual(row["amount_cents"], 4550)

    def test_paid_store_order_creates_one_financial_income(self):
        db = self.app_module.get_db()
        db.execute("""
            INSERT INTO orders (user_id, customer_name, customer_phone, address, total, status, payment_method)
            VALUES ((SELECT id FROM users WHERE email='cliente@example.test'),
                    'Cliente Teste', '', '', 79.90, 'pending', 'pix')
        """)
        order_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()

        self._login("admin@example.test")
        first = self.client.post("/admin/pedidos/status", data={"order_id": order_id, "status": "paid"})
        second = self.client.post("/admin/pedidos/status", data={"order_id": order_id, "status": "paid"})
        self.assertEqual(first.status_code, 303)
        self.assertEqual(second.status_code, 303)

        db = self.app_module.get_db()
        rows = db.execute(
            "SELECT amount_cents, status, order_id FROM financial_transactions WHERE order_id=?",
            (order_id,),
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount_cents"], 7990)
        self.assertEqual(rows[0]["status"], "paid")
        db.close()

    def test_barber_cannot_change_order_payment_status(self):
        db = self.app_module.get_db()
        db.execute("""
            INSERT INTO orders (customer_name, customer_phone, address, total, status, payment_method)
            VALUES ('Cliente Teste', '', '', 50.00, 'pending', 'dinheiro')
        """)
        order_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()

        self._login("barber@example.test")
        response = self.client.post("/admin/pedidos/status", data={"order_id": order_id, "status": "paid"})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")
        db = self.app_module.get_db()
        order = db.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()
        finance = db.execute("SELECT id FROM financial_transactions WHERE order_id=?", (order_id,)).fetchone()
        db.close()
        self.assertEqual(order["status"], "pending")
        self.assertIsNone(finance)


    def test_stock_purchase_updates_quantity_and_weighted_average_cost(self):
        db = self.app_module.get_db()
        db.execute("""
            INSERT INTO products (name, price, cost_price, stock, category, active)
            VALUES ('Pomada teste', 20.00, 5.00, 10, 'Modelagem', 1)
        """)
        product_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()

        self._login("admin@example.test")
        response = self.client.post("/admin/estoque/entrada", data={
            "product_id": product_id, "quantity": 10, "unit_cost": "7.00", "note": "Fornecedor teste"
        })
        self.assertEqual(response.status_code, 303)
        self.assertIn("entrada=1", response.headers["location"])

        db = self.app_module.get_db()
        product = db.execute("SELECT stock, cost_price FROM products WHERE id=?", (product_id,)).fetchone()
        movement = db.execute("""
            SELECT movement_type, quantity, unit_cost_cents, note
            FROM stock_movements WHERE product_id=? ORDER BY id DESC LIMIT 1
        """, (product_id,)).fetchone()
        db.close()
        self.assertEqual(product["stock"], 20)
        self.assertAlmostEqual(product["cost_price"], 6.00)
        self.assertEqual(movement["movement_type"], "purchase")
        self.assertEqual(movement["quantity"], 10)
        self.assertEqual(movement["unit_cost_cents"], 700)
        self.assertEqual(movement["note"], "Fornecedor teste")

    def test_barber_cannot_register_stock_purchase(self):
        db = self.app_module.get_db()
        db.execute("""
            INSERT INTO products (name, price, cost_price, stock, category, active)
            VALUES ('Gel teste', 15.00, 4.00, 3, 'Cabelo', 1)
        """)
        product_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()

        self._login("barber@example.test")
        response = self.client.post("/admin/estoque/entrada", data={
            "product_id": product_id, "quantity": 5, "unit_cost": "3.50", "note": "Não autorizado"
        })
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")
        db = self.app_module.get_db()
        product = db.execute("SELECT stock FROM products WHERE id=?", (product_id,)).fetchone()
        movement = db.execute("SELECT id FROM stock_movements WHERE product_id=?", (product_id,)).fetchone()
        db.close()
        self.assertEqual(product["stock"], 3)
        self.assertIsNone(movement)


    def test_finance_report_shows_product_sales_margin(self):
        db = self.app_module.get_db()
        db.execute("""
            INSERT INTO products (name, price, cost_price, stock, category, active)
            VALUES ('Pomada margem teste', 20.00, 6.00, 4, 'Modelagem', 1)
        """)
        product_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("""
            INSERT INTO orders (customer_name, customer_phone, address, total, status, payment_method)
            VALUES ('Cliente Relatório', '', '', 20.00, 'paid', 'pix')
        """)
        order_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("""
            INSERT INTO order_items (order_id, product_id, product_name, quantity, price)
            VALUES (?, ?, 'Pomada margem teste', 1, 20.00)
        """, (order_id, product_id))
        db.execute("""
            INSERT INTO stock_movements
                (product_id, movement_type, quantity, unit_cost_cents, note, order_id)
            VALUES (?, 'sale', -1, 600, 'Venda teste', ?)
        """, (product_id, order_id))
        db.execute("""
            INSERT INTO financial_transactions
                (transaction_type, category, description, amount_cents, occurred_on, status, order_id)
            VALUES ('income', 'loja', 'Pedido teste', 2000, date('now'), 'paid', ?)
        """, (order_id,))
        db.commit()
        db.close()

        self._login("admin@example.test")
        response = self.client.get("/admin/financeiro")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Desempenho dos produtos", response.text)
        self.assertIn("Pomada margem teste", response.text)
        self.assertIn("R$ 20.00", response.text)
        self.assertIn("R$ 6.00", response.text)
        self.assertIn("R$ 14.00", response.text)


    def test_cancelling_order_returns_stock_once_and_cancels_income(self):
        db = self.app_module.get_db()
        db.execute("""
            INSERT INTO products (name, price, cost_price, stock, category, active)
            VALUES ('Produto cancelamento', 10.00, 4.00, 2, 'Teste', 1)
        """)
        product_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("""
            INSERT INTO orders (customer_name, customer_phone, address, total, status, payment_method)
            VALUES ('Cliente Cancelamento', '', '', 20.00, 'pending', 'pix')
        """)
        order_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("""
            INSERT INTO order_items (order_id, product_id, product_name, quantity, price)
            VALUES (?, ?, 'Produto cancelamento', 2, 10.00)
        """, (order_id, product_id))
        db.execute("""
            INSERT INTO stock_movements
                (product_id, movement_type, quantity, unit_cost_cents, note, order_id)
            VALUES (?, 'sale', -2, 400, 'Venda teste', ?)
        """, (product_id, order_id))
        db.execute("""
            INSERT INTO financial_transactions
                (transaction_type, category, description, amount_cents, occurred_on, status, order_id)
            VALUES ('income', 'Loja', 'Pedido cancelamento', 2000, date('now'), 'paid', ?)
        """, (order_id,))
        db.commit()
        db.close()

        self._login("admin@example.test")
        for _ in range(2):
            response = self.client.post(
                "/admin/pedidos/status",
                data={"order_id": order_id, "status": "cancelled"},
            )
            self.assertEqual(response.status_code, 303)

        db = self.app_module.get_db()
        product = db.execute("SELECT stock FROM products WHERE id=?", (product_id,)).fetchone()
        returns = db.execute("""
            SELECT COUNT(*) AS total, SUM(quantity) AS quantity
            FROM stock_movements
            WHERE order_id=? AND product_id=? AND movement_type='return'
        """, (order_id, product_id)).fetchone()
        order = db.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()
        income = db.execute("SELECT status FROM financial_transactions WHERE order_id=?", (order_id,)).fetchone()
        db.close()
        self.assertEqual(product["stock"], 4)
        self.assertEqual(returns["total"], 1)
        self.assertEqual(returns["quantity"], 2)
        self.assertEqual(order["status"], "cancelled")
        self.assertEqual(income["status"], "cancelled")

    def test_cancelled_order_cannot_be_reopened_without_restocking(self):
        db = self.app_module.get_db()
        db.execute("""
            INSERT INTO orders (customer_name, customer_phone, address, total, status, payment_method)
            VALUES ('Cliente Final', '', '', 10.00, 'cancelled', 'pix')
        """)
        order_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()

        self._login("admin@example.test")
        response = self.client.post(
            "/admin/pedidos/status", data={"order_id": order_id, "status": "pending"}
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("erro=cancelado", response.headers["location"])
        db = self.app_module.get_db()
        order = db.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()
        db.close()
        self.assertEqual(order["status"], "cancelled")

    def test_cancelled_order_is_excluded_from_store_cost_and_margin_reports(self):
        db = self.app_module.get_db()
        db.execute("""
            INSERT INTO products (name, price, cost_price, stock, category, active)
            VALUES ('Produto cancelado relatório', 25.00, 8.00, 3, 'Teste', 1)
        """)
        product_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("""
            INSERT INTO orders (customer_name, customer_phone, address, total, status, payment_method)
            VALUES ('Cliente Cancelado Relatório', '', '', 25.00, 'cancelled', 'pix')
        """)
        order_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("""
            INSERT INTO order_items (order_id, product_id, product_name, quantity, price)
            VALUES (?, ?, 'Produto cancelado relatório', 1, 25.00)
        """, (order_id, product_id))
        db.execute("""
            INSERT INTO stock_movements
                (product_id, movement_type, quantity, unit_cost_cents, note, order_id)
            VALUES (?, 'sale', -1, 800, 'Venda posteriormente cancelada', ?)
        """, (product_id, order_id))
        db.commit()
        db.close()

        self._login("admin@example.test")
        today = datetime.now().strftime("%Y-%m-%d")
        response = self.client.get(f"/admin/financeiro?inicio={today}&fim={today}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Custo estimado dos produtos vendidos", response.text)
        self.assertNotIn("Produto cancelado relatório", response.text)
        self.assertIn("R$ 0.00", response.text)

    def test_finance_summary_counts_only_paid_income_and_expenses(self):
        db = self.app_module.get_db()
        db.execute("""
            INSERT INTO financial_transactions
                (transaction_type, category, description, amount_cents, occurred_on, status)
            VALUES
                ('income', 'Teste financeiro', 'Entrada paga', 1000, date('now'), 'paid'),
                ('income', 'Teste financeiro', 'Entrada pendente', 500, date('now'), 'pending'),
                ('income', 'Teste financeiro', 'Entrada cancelada', 300, date('now'), 'cancelled'),
                ('expense', 'Teste financeiro', 'Despesa paga', 200, date('now'), 'paid'),
                ('expense', 'Teste financeiro', 'Despesa pendente', 100, date('now'), 'pending')
        """)
        db.commit()
        db.close()

        self._login("admin@example.test")
        today = datetime.now().strftime("%Y-%m-%d")
        response = self.client.get(f"/admin/financeiro?inicio={today}&fim={today}")
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response.text, r'R\$ 10\.00</div><div class="stat-label">Entradas recebidas')
        self.assertRegex(response.text, r'R\$ 2\.00</div><div class="stat-label">Despesas pagas')
        self.assertRegex(response.text, r'R\$ 8\.00</div><div class="stat-label">Saldo do período')
        self.assertRegex(response.text, r'R\$ 6\.00</div><div class="stat-label">Lançamentos pendentes')

    def test_finance_csv_export_neutralizes_spreadsheet_formulas(self):
        db = self.app_module.get_db()
        db.execute("""
            INSERT INTO financial_transactions
                (transaction_type, category, description, amount_cents, occurred_on, status)
            VALUES ('expense', '=1+1', '  @SUM(A1:A2)', 500, date('now'), 'paid')
        """)
        db.commit()
        db.close()

        self._login("admin@example.test")
        today = datetime.now().strftime("%Y-%m-%d")
        response = self.client.get(
            f"/admin/financeiro/exportar.csv?inicio={today}&fim={today}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("'=1+1", response.text)
        self.assertIn("'  @SUM(A1:A2)", response.text)

    def test_finance_csv_export_rejects_invalid_or_oversized_period(self):
        self._login("admin@example.test")
        response = self.client.get(
            "/admin/financeiro/exportar.csv?inicio=2024-01-01&fim=2026-10-23"
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("erro=periodo", response.headers["location"])

        response = self.client.get(
            "/admin/financeiro/exportar.csv?inicio=2026-02-30&fim=2026-03-01"
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("erro=periodo", response.headers["location"])

    def test_finance_csv_export_requires_admin(self):
        response = self.client.get("/admin/financeiro/exportar.csv")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")

        self._login("barber@example.test")
        response = self.client.get("/admin/financeiro/exportar.csv")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")

    def test_admin_can_export_finance_csv_for_selected_period(self):
        db = self.app_module.get_db()
        db.execute("""
            INSERT INTO financial_transactions
                (transaction_type, category, description, amount_cents, occurred_on,
                 payment_method, status, created_by)
            VALUES ('income', 'serviço', 'Recebimento teste', 1250, date('now'),
                    'pix', 'paid', (SELECT id FROM users WHERE email='admin@example.test'))
        """)
        db.commit()
        db.close()

        self._login("admin@example.test")
        today = datetime.now().strftime("%Y-%m-%d")
        response = self.client.get(
            f"/admin/financeiro/exportar.csv?inicio={today}&fim={today}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers["content-type"])
        self.assertIn("attachment;", response.headers["content-disposition"])
        self.assertIn("Recebimento teste", response.text)
        self.assertIn("12.50", response.text)
        self.assertTrue(response.content.startswith(bytes([0xEF, 0xBB, 0xBF])))


if __name__ == "__main__":
    unittest.main()
