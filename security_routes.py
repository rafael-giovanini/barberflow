"""Rotas incrementais para clientes e segurança de conta do BarberFlow.

A integração é registrada pelo app principal para reaproveitar o banco,
templates e os helpers de autenticação existentes.
"""
import hashlib
import os
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlencode

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse


def register_security_routes(app, templates, get_db, get_current_user,
                             hash_password, verify_password):
    """Registra as rotas sem substituir a aplicação nem o esquema atual."""

    def render(request, template, user, **context):
        return templates.TemplateResponse(template, {
            "request": request, "user": user, **context
        })

    def admin_only(request):
        user = get_current_user(request)
        if not user or user.get("role") != "admin":
            return None
        return user

    @app.get("/admin/clientes", response_class=HTMLResponse)
    def admin_clientes(request: Request, q: str = ""):
        user = admin_only(request)
        if not user:
            return RedirectResponse(url="/login", status_code=303)
        db = get_db()
        term = "%" + q.strip() + "%"
        customers = db.execute("""
            SELECT id, name, email, phone, created_at, active
            FROM users
            WHERE role='customer'
              AND (? = '%%' OR name LIKE ? OR email LIKE ? OR COALESCE(phone, '') LIKE ?)
            ORDER BY name COLLATE NOCASE
            LIMIT 250
        """, (term, term, term, term)).fetchall()
        db.close()
        return render(request, "admin/clientes.html", user, customers=customers, q=q)

    @app.post("/admin/clientes/salvar")
    def admin_cliente_salvar(
        request: Request,
        customer_id: int = Form(...),
        name: str = Form(...),
        email: str = Form(...),
        phone: str = Form("")
    ):
        user = admin_only(request)
        if not user:
            return RedirectResponse(url="/login", status_code=303)
        name, email, phone = name.strip(), email.strip().lower(), phone.strip()
        if not name or not email or "@" not in email:
            return RedirectResponse(url="/admin/clientes?erro=dados", status_code=303)
        db = get_db()
        try:
            db.execute("""
                UPDATE users SET name=?, email=?, phone=?
                WHERE id=? AND role='customer'
            """, (name, email, phone, customer_id))
            db.commit()
        except Exception:
            db.close()
            return RedirectResponse(url="/admin/clientes?erro=email", status_code=303)
        db.close()
        return RedirectResponse(url="/admin/clientes?salvo=1", status_code=303)

    @app.post("/admin/clientes/status")
    def admin_cliente_status(
        request: Request,
        customer_id: int = Form(...),
        active: int = Form(...)
    ):
        user = admin_only(request)
        if not user:
            return RedirectResponse(url="/login", status_code=303)
        db = get_db()
        db.execute("""
            UPDATE users SET active=?, session_version=session_version+1
            WHERE id=? AND role='customer'
        """, (1 if active else 0, customer_id))
        db.commit()
        db.close()
        return RedirectResponse(url="/admin/clientes", status_code=303)

    @app.get("/minha-conta", response_class=HTMLResponse)
    def minha_conta(request: Request):
        user = get_current_user(request)
        if not user:
            return RedirectResponse(url="/login", status_code=303)
        return render(request, "minha_conta.html", user, error=None, success=None)

    @app.post("/minha-conta/senha")
    def alterar_senha(
        request: Request,
        current_password: str = Form(...),
        new_password: str = Form(...),
        confirm_password: str = Form(...)
    ):
        user = get_current_user(request)
        if not user:
            return RedirectResponse(url="/login", status_code=303)
        if len(new_password) < 10:
            return render(request, "minha_conta.html", user,
                          error="A nova senha deve ter pelo menos 10 caracteres.", success=None)
        if new_password != confirm_password:
            return render(request, "minha_conta.html", user,
                          error="A confirmação da nova senha não confere.", success=None)
        db = get_db()
        row = db.execute("SELECT password_hash FROM users WHERE id=? AND active=1",
                         (user["user_id"],)).fetchone()
        if not row or not verify_password(current_password, row["password_hash"]):
            db.close()
            return render(request, "minha_conta.html", user,
                          error="A senha atual está incorreta.", success=None)
        db.execute("""
            UPDATE users SET password_hash=?, session_version=session_version+1
            WHERE id=?
        """, (hash_password(new_password), user["user_id"]))
        db.commit()
        db.close()
        response = RedirectResponse(url="/login?senha_alterada=1", status_code=303)
        response.delete_cookie("barbearia_session")
        return response

    @app.get("/esqueci-senha", response_class=HTMLResponse)
    def esqueci_senha_page(request: Request):
        return render(request, "esqueci_senha.html", None, sent=False, error=None)

    @app.post("/esqueci-senha", response_class=HTMLResponse)
    def solicitar_recuperacao(request: Request, email: str = Form(...)):
        normalized_email = email.strip().lower()
        generic_message = (
            "Se o endereço estiver cadastrado e a recuperação estiver configurada, "
            "você receberá instruções por e-mail."
        )
        # Nunca gerar links usando o cabeçalho Host enviado pelo cliente.
        base_url = os.getenv("APP_BASE_URL", "").strip().rstrip("/")
        smtp_host = os.getenv("SMTP_HOST", "").strip()
        smtp_from = os.getenv("SMTP_FROM", "").strip()
        if not (base_url.startswith("https://") and smtp_host and smtp_from):
            return render(request, "esqueci_senha.html", None, sent=True, error=None)

        db = get_db()
        now = datetime.now(timezone.utc)
        recent = db.execute("""
            SELECT COUNT(*) AS total FROM password_reset_tokens
            WHERE email=? AND created_at >= ?
        """, (normalized_email, (now - timedelta(hours=1)).isoformat())).fetchone()["total"]
        account = db.execute("""
            SELECT id FROM users WHERE email=? AND active=1
        """, (normalized_email,)).fetchone()
        if recent < 3 and account:
            raw_token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
            db.execute("""
                UPDATE password_reset_tokens SET used_at=?
                WHERE user_id=? AND used_at IS NULL
            """, (now.isoformat(), account["id"]))
            db.execute("""
                INSERT INTO password_reset_tokens
                    (user_id, email, token_hash, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (account["id"], normalized_email, token_hash,
                  (now + timedelta(minutes=30)).isoformat(), now.isoformat()))
            db.commit()
            link = base_url + "/redefinir-senha?" + urlencode({"token": raw_token})
            message = EmailMessage()
            message["Subject"] = "Recuperação de senha — BarberFlow"
            message["From"] = smtp_from
            message["To"] = normalized_email
            message.set_content(
                "Foi solicitada a recuperação da senha da sua conta BarberFlow.\n\n"
                "Acesse o link abaixo em até 30 minutos e use-o apenas uma vez:\n"
                + link + "\n\nSe você não solicitou a recuperação, ignore esta mensagem."
            )
            try:
                port = int(os.getenv("SMTP_PORT", "587"))
                with smtplib.SMTP(smtp_host, port, timeout=10) as smtp:
                    smtp.ehlo()
                    if os.getenv("SMTP_STARTTLS", "1").lower() not in ("0", "false", "no"):
                        smtp.starttls()
                        smtp.ehlo()
                    smtp_user = os.getenv("SMTP_USER", "")
                    smtp_password = os.getenv("SMTP_PASSWORD", "")
                    if smtp_user:
                        smtp.login(smtp_user, smtp_password)
                    smtp.send_message(message)
            except Exception:
                # Não expor detalhes do SMTP nem o token ao usuário.
                db.execute("""
                    UPDATE password_reset_tokens SET used_at=?
                    WHERE token_hash=? AND used_at IS NULL
                """, (datetime.now(timezone.utc).isoformat(), token_hash))
                db.commit()
        db.close()
        return render(request, "esqueci_senha.html", None, sent=True, error=None)

    @app.get("/redefinir-senha", response_class=HTMLResponse)
    def redefinir_senha_page(request: Request, token: str = ""):
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest() if token else ""
        db = get_db()
        now = datetime.now(timezone.utc).isoformat()
        row = db.execute("""
            SELECT id FROM password_reset_tokens
            WHERE token_hash=? AND used_at IS NULL AND expires_at > ?
        """, (token_hash, now)).fetchone()
        db.close()
        return render(request, "redefinir_senha.html", None,
                      token=token, valid=bool(row), error=None)

    @app.post("/redefinir-senha", response_class=HTMLResponse)
    def redefinir_senha(
        request: Request,
        token: str = Form(...),
        new_password: str = Form(...),
        confirm_password: str = Form(...)
    ):
        if len(new_password) < 10 or new_password != confirm_password:
            return render(request, "redefinir_senha.html", None, token=token, valid=True,
                          error="Use uma senha com pelo menos 10 caracteres e confirme-a corretamente.")
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        db = get_db()
        now = datetime.now(timezone.utc).isoformat()
        row = db.execute("""
            SELECT id, user_id FROM password_reset_tokens
            WHERE token_hash=? AND used_at IS NULL AND expires_at > ?
        """, (token_hash, now)).fetchone()
        if not row:
            db.close()
            return render(request, "redefinir_senha.html", None, token="", valid=False,
                          error="O link é inválido, expirou ou já foi utilizado.")
        # Consome o token atomicamente antes de alterar a senha, impedindo reutilização.
        consumed = db.execute("""
            UPDATE password_reset_tokens SET used_at=?
            WHERE id=? AND used_at IS NULL AND expires_at > ?
        """, (now, row["id"], now))
        if consumed.rowcount != 1:
            db.close()
            return render(request, "redefinir_senha.html", None, token="", valid=False,
                          error="O link é inválido, expirou ou já foi utilizado.")
        updated = db.execute("""
            UPDATE users SET password_hash=?, session_version=session_version+1
            WHERE id=? AND active=1
        """, (hash_password(new_password), row["user_id"]))
        if updated.rowcount != 1:
            db.commit()
            db.close()
            return render(request, "redefinir_senha.html", None, token="", valid=False,
                          error="Não foi possível redefinir a senha desta conta.")
        db.execute("""
            UPDATE password_reset_tokens SET used_at=?
            WHERE user_id=? AND used_at IS NULL
        """, (now, row["user_id"]))
        db.commit()
        db.close()
        return RedirectResponse(url="/login?senha_redefinida=1", status_code=303)
