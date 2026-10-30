"""Rotas incrementais para clientes e segurança de conta do BarberFlow.

A integração é registrada pelo app principal para reaproveitar o banco,
templates e os helpers de autenticação existentes.
"""
import hashlib
from html import escape
import os
import secrets
import sqlite3
import smtplib
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage

from auth import normalize_cpf, valid_cpf, valid_birth_date
from smtp_settings import get_smtp_config
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

    def staff_only(request):
        """Permite cadastro operacional de clientes a administradores e barbeiros."""
        user = get_current_user(request)
        if not user or user.get("role") not in ("admin", "barber"):
            return None
        return user

    def add_branded_email_html(message, db, recipient_name, intro, button_text, link, footer_note):
        setting = db.execute("SELECT value FROM settings WHERE key='shop_name'").fetchone()
        brand_name = (setting["value"].strip() if setting and setting["value"] else "BarberFlow")
        safe_brand = escape(brand_name)
        safe_name = escape(recipient_name or "")
        safe_intro = escape(intro)
        safe_button = escape(button_text)
        safe_link = escape(link, quote=True)
        safe_footer = escape(footer_note)
        message.add_alternative(f"""<!doctype html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background-color:#f3f4f6;font-family:Arial,Helvetica,sans-serif;color:#242424;">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">Acesse o link seguro enviado pela {safe_brand}.</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color:#f3f4f6;padding:28px 12px;">
    <tr><td align="center">
      <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0" style="width:100%;max-width:600px;background-color:#ffffff;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;">
        <tr><td style="background-color:#151515;padding:22px 30px;border-bottom:4px solid #c9a227;">
          <div style="font-size:22px;font-weight:700;letter-spacing:1px;color:#ffffff;">{safe_brand}</div>
          <div style="font-size:12px;color:#c9a227;margin-top:5px;letter-spacing:1.5px;text-transform:uppercase;">Acesso seguro à sua conta</div>
        </td></tr>
        <tr><td style="padding:32px 30px 24px;">
          <h1 style="font-size:22px;line-height:1.3;margin:0 0 20px;color:#171717;">Olá{f' {safe_name}' if safe_name else ''}!</h1>
          <p style="font-size:15px;line-height:1.65;margin:0 0 18px;color:#444444;">{safe_intro}</p>
          <table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin:26px 0;">
            <tr><td align="center" bgcolor="#c9a227" style="border-radius:6px;">
              <a href="{safe_link}" style="display:inline-block;padding:14px 24px;font-size:15px;font-weight:bold;color:#171717;text-decoration:none;border-radius:6px;">{safe_button}</a>
            </td></tr>
          </table>
          <p style="font-size:13px;line-height:1.6;margin:0 0 12px;color:#555555;">Este link é válido por <strong>30 minutos</strong> e pode ser usado uma única vez.</p>
          <p style="font-size:13px;line-height:1.6;margin:0;color:#555555;">Se o botão não funcionar, copie e cole este endereço no navegador:</p>
          <p style="font-size:12px;line-height:1.6;margin:8px 0 0;word-break:break-all;"><a href="{safe_link}" style="color:#7a5a00;">{escape(link)}</a></p>
        </td></tr>
        <tr><td style="padding:18px 30px;background-color:#f8f8f8;border-top:1px solid #eeeeee;">
          <p style="font-size:12px;line-height:1.6;margin:0;color:#666666;">{safe_footer}</p>
          <p style="font-size:12px;line-height:1.6;margin:8px 0 0;color:#888888;">Se você não solicitou esta alteração, ignore esta mensagem. Sua senha não será modificada.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>""", subtype="html")

    def customer_form_values(name, email, phone, cpf, birth_date, zip_code, address,
                             address_number, address_complement, neighborhood, city, state):
        return {
            "name": name, "email": email, "phone": phone, "cpf": cpf,
            "birth_date": birth_date, "zip_code": zip_code, "address": address,
            "address_number": address_number, "address_complement": address_complement,
            "neighborhood": neighborhood, "city": city, "state": state,
        }

    def send_first_access_email(account, db):
        smtp_config = get_smtp_config(db)
        base_url = smtp_config["app_base_url"].strip().rstrip("/")
        smtp_host = smtp_config["smtp_host"].strip()
        smtp_from = smtp_config["smtp_from"].strip()
        if not (smtp_config["enabled"] and base_url.startswith("https://") and smtp_host and smtp_from):
            return False
        if smtp_config["smtp_user"].strip() and not smtp_config["password"]:
            return False

        now = datetime.now(timezone.utc)
        recent = db.execute("""
            SELECT COUNT(*) AS total FROM password_reset_tokens
            WHERE email=? AND created_at >= ?
        """, (account["email"], (now - timedelta(hours=1)).isoformat())).fetchone()["total"]
        if recent >= 3:
            return False

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
        """, (account["id"], account["email"], token_hash,
              (now + timedelta(minutes=30)).isoformat(), now.isoformat()))
        db.commit()

        link = base_url + "/criar-senha?" + urlencode({"token": raw_token})
        message = EmailMessage()
        message["Subject"] = "Criar ou redefinir senha — BarberFlow"
        message["From"] = smtp_from
        message["To"] = account["email"]
        message.set_content(
            f"Olá, {account['name']}!\n\n"
            "Foi solicitado um link para criar ou redefinir a senha da sua conta.\n\n"
            "Acesse o link abaixo em até 30 minutos e use-o uma única vez:\n" + link +
            "\n\nSe você não solicitou esta alteração, ignore esta mensagem. Sua senha não será modificada."
        )
        add_branded_email_html(
            message, db, account["name"],
            "Recebemos uma solicitação para criar ou redefinir a senha da sua conta. "
            "Use o botão abaixo para continuar com segurança.",
            "Criar ou redefinir minha senha", link,
            "Mensagem automática enviada pelo sistema de atendimento da barbearia."
        )
        try:
            port = int(smtp_config["smtp_port"] or "587")
            smtp_factory = smtplib.SMTP_SSL if smtp_config["smtp_security"] == "ssl" else smtplib.SMTP
            with smtp_factory(smtp_host, port, timeout=10) as smtp:
                if smtp_config["smtp_security"] != "ssl":
                    smtp.ehlo()
                if smtp_config["smtp_security"] == "starttls":
                    smtp.starttls()
                    smtp.ehlo()
                smtp_user = smtp_config["smtp_user"].strip()
                if smtp_user:
                    smtp.login(smtp_user, smtp_config["password"])
                smtp.send_message(message)
            return True
        except Exception:
            db.execute("""
                UPDATE password_reset_tokens SET used_at=?
                WHERE token_hash=? AND used_at IS NULL
            """, (datetime.now(timezone.utc).isoformat(), token_hash))
            db.commit()
            return False

    @app.get("/admin/clientes/novo", response_class=HTMLResponse)
    def novo_cliente_page(request: Request):
        user = staff_only(request)
        if not user:
            return RedirectResponse(url="/login", status_code=303)
        return render(request, "admin/cliente_novo.html", user, error=None, today=date.today().isoformat(),
                      **customer_form_values("", "", "", "", "", "", "", "", "", "", "", ""))

    @app.post("/admin/clientes/novo", response_class=HTMLResponse)
    def novo_cliente_salvar(
        request: Request,
        name: str = Form(...), email: str = Form(...), phone: str = Form(...),
        cpf: str = Form(...), birth_date: str = Form(...), zip_code: str = Form(...),
        address: str = Form(...), address_number: str = Form(...),
        address_complement: str = Form(""), neighborhood: str = Form(...),
        city: str = Form(...), state: str = Form(...)
    ):
        user = staff_only(request)
        if not user:
            return RedirectResponse(url="/login", status_code=303)

        name, email = name.strip(), email.strip().lower()
        phone, cpf = phone.strip(), normalize_cpf(cpf)
        zip_code = "".join(ch for ch in zip_code if ch.isdigit())
        address, address_number = address.strip(), address_number.strip()
        address_complement = address_complement.strip()
        neighborhood, city, state = neighborhood.strip(), city.strip(), state.strip().upper()
        values = customer_form_values(name, email, phone, cpf, birth_date, zip_code, address,
                                      address_number, address_complement, neighborhood, city, state)
        if not name or len(name) > 120 or "@" not in email:
            return render(request, "admin/cliente_novo.html", user, today=date.today().isoformat(),
                          error="Informe nome completo e e-mail válidos.", **values)
        if not valid_cpf(cpf):
            return render(request, "admin/cliente_novo.html", user, today=date.today().isoformat(),
                          error="Informe um CPF válido.", **values)
        if len(phone) < 10 or len(zip_code) != 8 or not address or not address_number or not neighborhood or not city or len(state) != 2:
            return render(request, "admin/cliente_novo.html", user, today=date.today().isoformat(),
                          error="Preencha telefone e endereço completos.", **values)
        if not valid_birth_date(birth_date):
            return render(request, "admin/cliente_novo.html", user, today=date.today().isoformat(),
                          error="Informe uma data de nascimento válida, que não esteja no futuro.", **values)

        db = get_db()
        try:
            db.execute("""
                INSERT INTO users
                    (name, email, phone, cpf, birth_date, zip_code, address, address_number,
                     address_complement, neighborhood, city, state, password_hash,
                     first_access_required, role)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'customer')
            """, (name, email, phone, cpf, birth_date, zip_code, address, address_number,
                  address_complement, neighborhood, city, state,
                  hash_password(secrets.token_urlsafe(32))))
            account = db.execute("SELECT id, name, email FROM users WHERE cpf=?", (cpf,)).fetchone()
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            return render(request, "admin/cliente_novo.html", user, today=date.today().isoformat(),
                          error="Já existe uma conta com este CPF ou e-mail.", **values)
        finally:
            db.close()

        # Envia um link de ativação ao e-mail previamente informado. O cadastro não
        # fica acessível até o cliente definir uma senha a partir desse link.
        db = get_db()
        email_sent = send_first_access_email(account, db)
        db.close()
        return RedirectResponse(
            url="/admin/clientes/novo?salvo=1" + ("&email=1" if email_sent else "&email=0"),
            status_code=303
        )

    @app.get("/primeiro-acesso", response_class=HTMLResponse)
    def primeiro_acesso_page(request: Request):
        return render(request, "primeiro_acesso.html", None, error=None, sent=False,
                      not_found=False, cpf="")

    @app.post("/primeiro-acesso", response_class=HTMLResponse)
    def primeiro_acesso_cpf(request: Request, cpf: str = Form(...)):
        normalized_cpf = normalize_cpf(cpf)
        if not valid_cpf(normalized_cpf):
            return render(request, "primeiro_acesso.html", None,
                          error="Informe um CPF válido.", sent=False, not_found=False, cpf=cpf)
        db = get_db()
        account = db.execute("""
            SELECT id, name, email, active FROM users
            WHERE REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(cpf, ''), '.', ''), '-', ''), ' ', ''), '/', '')=?
              AND role='customer'
            LIMIT 1
        """, (normalized_cpf,)).fetchone()
        if not account:
            db.close()
            return RedirectResponse(url="/cadastro?cpf_nao_encontrado=1", status_code=303)
        if not account["active"]:
            db.close()
            return render(request, "primeiro_acesso.html", None,
                          error="Este cadastro está inativo. Peça à barbearia para reativá-lo.",
                          sent=False, not_found=False, cpf=cpf)
        email_sent = send_first_access_email(account, db)
        db.close()
        if not email_sent:
            return render(request, "primeiro_acesso.html", None,
                          error="Não foi possível enviar o link. Peça à barbearia para verificar a configuração de e-mail.",
                          sent=False, not_found=False, cpf="")
        return render(request, "primeiro_acesso.html", None, error=None, sent=True,
                      not_found=False, cpf="")

    @app.get("/criar-senha", response_class=HTMLResponse)
    def criar_senha_page(request: Request, token: str = ""):
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest() if token else ""
        db = get_db()
        now = datetime.now(timezone.utc).isoformat()
        row = db.execute("""
            SELECT t.id FROM password_reset_tokens t
            JOIN users u ON u.id=t.user_id
            WHERE t.token_hash=? AND t.used_at IS NULL AND t.expires_at>?
              AND u.active=1 AND u.role='customer'
        """, (token_hash, now)).fetchone()
        db.close()
        return render(request, "criar_senha.html", None, token=token, valid=bool(row), error=None)

    @app.post("/criar-senha", response_class=HTMLResponse)
    def criar_senha(request: Request, token: str = Form(...),
                    new_password: str = Form(...), confirm_password: str = Form(...)):
        if len(new_password) < 10 or new_password != confirm_password:
            return render(request, "criar_senha.html", None, token=token, valid=True,
                          error="Use uma senha com pelo menos 10 caracteres e confirme-a corretamente.")
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        db = get_db()
        now = datetime.now(timezone.utc).isoformat()
        row = db.execute("""
            SELECT t.id, t.user_id FROM password_reset_tokens t
            JOIN users u ON u.id=t.user_id
            WHERE t.token_hash=? AND t.used_at IS NULL AND t.expires_at>?
              AND u.active=1 AND u.role='customer'
        """, (token_hash, now)).fetchone()
        if not row:
            db.close()
            return render(request, "criar_senha.html", None, token="", valid=False,
                          error="O link é inválido, expirou ou já foi utilizado.")
        consumed = db.execute("""
            UPDATE password_reset_tokens SET used_at=?
            WHERE id=? AND used_at IS NULL AND expires_at>?
        """, (now, row["id"], now))
        if consumed.rowcount != 1:
            db.rollback()
            db.close()
            return render(request, "criar_senha.html", None, token="", valid=False,
                          error="O link é inválido, expirou ou já foi utilizado.")
        updated = db.execute("""
            UPDATE users SET password_hash=?, first_access_required=0,
                session_version=session_version+1
            WHERE id=? AND role='customer' AND active=1
        """, (hash_password(new_password), row["user_id"]))
        if updated.rowcount != 1:
            db.rollback()
            db.close()
            return render(request, "criar_senha.html", None, token="", valid=False,
                          error="Não foi possível ativar esta conta.")
        db.execute("""
            UPDATE password_reset_tokens SET used_at=?
            WHERE user_id=? AND used_at IS NULL
        """, (now, row["user_id"]))
        db.commit()
        db.close()
        return RedirectResponse(url="/login?senha_criada=1", status_code=303)

    @app.get("/admin/clientes", response_class=HTMLResponse)
    def admin_clientes(request: Request, q: str = ""):
        user = admin_only(request)
        if not user:
            return RedirectResponse(url="/login", status_code=303)
        db = get_db()
        term = "%" + q.strip() + "%"
        customers = db.execute("""
            SELECT id, name, email, phone, cpf, birth_date, zip_code, address, address_number,
                   address_complement, neighborhood, city, state, created_at, active,
                   first_access_required
            FROM users
            WHERE role='customer'
              AND (? = '%%' OR name LIKE ? OR email LIKE ? OR COALESCE(phone, '') LIKE ? OR COALESCE(cpf, '') LIKE ?)
            ORDER BY name COLLATE NOCASE
            LIMIT 250
        """, (term, term, term, term, term)).fetchall()
        db.close()
        return render(request, "admin/clientes.html", user, customers=customers, q=q)

    @app.post("/admin/clientes/salvar")
    def admin_cliente_salvar(
        request: Request, customer_id: int = Form(...), name: str = Form(...),
        email: str = Form(...), phone: str = Form(""), cpf: str = Form(""),
        birth_date: str = Form(""), zip_code: str = Form(""), address: str = Form(""),
        address_number: str = Form(""), address_complement: str = Form(""),
        neighborhood: str = Form(""), city: str = Form(""), state: str = Form("")
    ):
        user = admin_only(request)
        if not user:
            return RedirectResponse(url="/login", status_code=303)
        name, email = name.strip(), email.strip().lower()
        phone, cpf = phone.strip(), normalize_cpf(cpf)
        zip_code = "".join(ch for ch in zip_code if ch.isdigit())
        address, address_number = address.strip(), address_number.strip()
        address_complement = address_complement.strip()
        neighborhood, city, state = neighborhood.strip(), city.strip(), state.strip().upper()
        has_profile_data = any((cpf, birth_date, zip_code, address, address_number, neighborhood, city, state))
        if not name or "@" not in email:
            return RedirectResponse(url="/admin/clientes?erro=dados", status_code=303)
        if has_profile_data and (not valid_cpf(cpf) or len(phone) < 10 or len(zip_code) != 8
                or not address or not address_number or not neighborhood or not city
                or len(state) != 2 or not valid_birth_date(birth_date)):
            return RedirectResponse(url="/admin/clientes?erro=dados", status_code=303)
        db = get_db()
        try:
            updated = db.execute("""
                UPDATE users SET name=?, email=?, phone=?,
                    cpf=CASE WHEN ?='' THEN cpf ELSE ? END,
                    birth_date=CASE WHEN ?='' THEN birth_date ELSE ? END,
                    zip_code=CASE WHEN ?='' THEN zip_code ELSE ? END,
                    address=CASE WHEN ?='' THEN address ELSE ? END,
                    address_number=CASE WHEN ?='' THEN address_number ELSE ? END,
                    address_complement=CASE WHEN ?='' THEN address_complement ELSE ? END,
                    neighborhood=CASE WHEN ?='' THEN neighborhood ELSE ? END,
                    city=CASE WHEN ?='' THEN city ELSE ? END,
                    state=CASE WHEN ?='' THEN state ELSE ? END
                WHERE id=? AND role='customer'
            """, (name, email, phone, cpf, cpf, birth_date, birth_date, zip_code, zip_code,
                  address, address, address_number, address_number, address_complement,
                  address_complement, neighborhood, neighborhood, city, city, state, state, customer_id))
            if updated.rowcount != 1:
                db.rollback()
                return RedirectResponse(url="/admin/clientes?erro=nao_encontrado", status_code=303)
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            return RedirectResponse(url="/admin/clientes?erro=email", status_code=303)
        finally:
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
        updated = db.execute("""
            UPDATE users SET active=?, session_version=session_version+1
            WHERE id=? AND role='customer'
        """, (1 if active else 0, customer_id))
        if updated.rowcount != 1:
            db.rollback()
            db.close()
            return RedirectResponse(
                url="/admin/clientes?erro=nao_encontrado", status_code=303
            )
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
        db = get_db()
        smtp_config = get_smtp_config(db)
        base_url = smtp_config["app_base_url"].strip().rstrip("/")
        smtp_host = smtp_config["smtp_host"].strip()
        smtp_from = smtp_config["smtp_from"].strip()
        if not (smtp_config["enabled"] and base_url.startswith("https://") and smtp_host and smtp_from):
            db.close()
            return render(request, "esqueci_senha.html", None, sent=True, error=None)
        if smtp_config["smtp_user"].strip() and not smtp_config["password"]:
            db.close()
            return render(request, "esqueci_senha.html", None, sent=True, error=None)

        now = datetime.now(timezone.utc)
        recent = db.execute("""
            SELECT COUNT(*) AS total FROM password_reset_tokens
            WHERE email=? AND created_at >= ?
        """, (normalized_email, (now - timedelta(hours=1)).isoformat())).fetchone()["total"]
        account = db.execute("""
            SELECT id, name FROM users WHERE email=? AND active=1 AND first_access_required=0
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
                f"Olá, {account['name']}!\n\n"
                "Foi solicitada a recuperação da senha da sua conta.\n\n"
                "Acesse o link abaixo em até 30 minutos e use-o uma única vez:\n"
                + link + "\n\nSe você não solicitou esta alteração, ignore esta mensagem. Sua senha não será modificada."
            )
            add_branded_email_html(
                message, db, account["name"],
                "Recebemos uma solicitação para redefinir a senha da sua conta. "
                "Use o botão abaixo para escolher uma nova senha.",
                "Redefinir minha senha", link,
                "Mensagem automática de recuperação de acesso do BarberFlow."
            )
            try:
                port = int(smtp_config["smtp_port"] or "587")
                smtp_factory = smtplib.SMTP_SSL if smtp_config["smtp_security"] == "ssl" else smtplib.SMTP
                with smtp_factory(smtp_host, port, timeout=10) as smtp:
                    if smtp_config["smtp_security"] != "ssl":
                        smtp.ehlo()
                    if smtp_config["smtp_security"] == "starttls":
                        smtp.starttls()
                        smtp.ehlo()
                    smtp_user = smtp_config["smtp_user"].strip()
                    if smtp_user:
                        smtp.login(smtp_user, smtp_config["password"])
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
            SELECT t.id FROM password_reset_tokens t
            JOIN users u ON u.id=t.user_id
            WHERE t.token_hash=? AND t.used_at IS NULL AND t.expires_at > ?
              AND u.first_access_required=0 AND u.active=1
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
            SELECT t.id, t.user_id FROM password_reset_tokens t
            JOIN users u ON u.id=t.user_id
            WHERE t.token_hash=? AND t.used_at IS NULL AND t.expires_at > ?
              AND u.first_access_required=0 AND u.active=1
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
