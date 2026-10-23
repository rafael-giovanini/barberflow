"""
Sistema de Barbearia - Aplicação Principal
FastAPI + SQLite + Templates Jinja2
"""
import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Request, Form, HTTPException, Depends, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer

from database import init_db, get_db, get_settings
from auth import hash_password, verify_password

# Inicializa banco
init_db()

app = FastAPI(title="Sistema de Barbearia")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
import json as _json
templates.env.filters["from_json"] = lambda s: _json.loads(s) if s else []


@app.middleware("http")
async def inject_settings(request: Request, call_next):
    """Injeta configurações e aplica validações defensivas globais."""
    request.state.settings = get_settings()

    # Rejeita POSTs com Origin explicitamente externo; complementa SameSite=Lax.
    # Requisições sem Origin (ex.: clientes de teste/integrações) seguem o fluxo normal.
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin:
            from urllib.parse import urlsplit
            origin_parts = urlsplit(origin)
            request_host = request.headers.get("host", "").lower()
            origin_host = (origin_parts.netloc or "").lower()
            if not origin_parts.scheme or not origin_host or origin_host != request_host:
                response = JSONResponse({"detail": "Origem da requisição não permitida."}, status_code=403)
                response.headers["X-Content-Type-Options"] = "nosniff"
                response.headers["X-Frame-Options"] = "DENY"
                response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                response.headers["Cache-Control"] = "no-store"
                if IS_PRODUCTION:
                    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
                return response

    response = await call_next(request)
    # Cabeçalhos defensivos aplicados também a respostas de erro e redirecionamentos.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cache-Control", "no-store")
    if IS_PRODUCTION:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response

# Em desenvolvimento, a chave aleatória evita um segredo fixo no código.
# Em produção, defina SECRET_KEY com um valor aleatório persistente no ambiente.
IS_PRODUCTION = os.getenv("ENVIRONMENT", "development").strip().lower() == "production"
_configured_secret = os.getenv("SECRET_KEY", "").strip()
if IS_PRODUCTION and len(_configured_secret) < 32:
    raise RuntimeError("Em produção, configure SECRET_KEY com pelo menos 32 caracteres aleatórios.")
SECRET_KEY = _configured_secret or secrets.token_urlsafe(48)
serializer = URLSafeTimedSerializer(SECRET_KEY)

COOKIE_NAME = "barbearia_session"
CART_COOKIE = "barbearia_cart"


# ---------- Helpers de autenticação ----------
def set_session(response, user_id: int, role: str, name: str):
    db = get_db()
    row = db.execute(
        "SELECT session_version, active FROM users WHERE id=?", (user_id,)
    ).fetchone()
    db.close()
    if not row or not row["active"]:
        return
    token = serializer.dumps({
        "user_id": user_id, "role": role, "name": name,
        "session_version": row["session_version"],
    })
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, max_age=86400 * 30,
        secure=IS_PRODUCTION or os.getenv("COOKIE_SECURE", "0").lower() in ("1", "true", "yes"),
        samesite="lax",
    )


def get_current_user(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        data = serializer.loads(token, max_age=86400 * 30)
        # Sessões antigas ou revogadas deixam de ser aceitas após troca de senha
        # ou desativação da conta.
        db = get_db()
        row = db.execute(
            "SELECT role, name, active, session_version FROM users WHERE id=?",
            (data.get("user_id"),),
        ).fetchone()
        db.close()
        if (not row or not row["active"]
                or data.get("session_version") != row["session_version"]):
            return None
        data["role"] = row["role"]
        data["name"] = row["name"]
        return data
    except Exception:
        return None


def require_login(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def require_admin(request: Request):
    user = get_current_user(request)
    if not user or user.get("role") not in ("admin", "barber"):
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def get_cart(request: Request):
    """Lê e normaliza o carrinho não confiável armazenado no cookie do navegador."""
    raw = request.cookies.get(CART_COOKIE)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            return []
        normalized = {}
        for item in parsed[:50]:
            if not isinstance(item, dict):
                continue
            try:
                product_id = int(item.get("product_id"))
                qty = int(item.get("qty"))
            except (TypeError, ValueError):
                continue
            if product_id > 0 and 1 <= qty <= 20:
                normalized[product_id] = min(20, normalized.get(product_id, 0) + qty)
        return [{"product_id": pid, "qty": qty} for pid, qty in normalized.items()]
    except (ValueError, TypeError):
        return []


def cart_total(cart, db):
    total = 0
    for item in cart:
        row = db.execute("SELECT price FROM products WHERE id=?", (item["product_id"],)).fetchone()
        if row:
            total += row["price"] * item["qty"]
    return total


# ---------- Páginas públicas ----------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    db = get_db()
    services = db.execute("SELECT * FROM services WHERE active=1 ORDER BY category, price").fetchall()
    portfolio = db.execute("SELECT * FROM portfolio ORDER BY id DESC LIMIT 6").fetchall()
    products = db.execute("SELECT * FROM products WHERE active=1 AND stock>0 ORDER BY id DESC LIMIT 4").fetchall()
    user = get_current_user(request)
    db.close()
    return templates.TemplateResponse("index.html", {
        "request": request, "user": user,
        "services": services, "portfolio": portfolio, "products": products,
    })


@app.get("/servicos", response_class=HTMLResponse)
def servicos(request: Request):
    db = get_db()
    services = db.execute("SELECT * FROM services WHERE active=1 ORDER BY category, price").fetchall()
    user = get_current_user(request)
    db.close()
    return templates.TemplateResponse("servicos.html", {"request": request, "user": user, "services": services})


@app.get("/portfolio", response_class=HTMLResponse)
def portfolio_page(request: Request):
    db = get_db()
    items = db.execute("SELECT * FROM portfolio ORDER BY category, id").fetchall()
    categories = db.execute("SELECT DISTINCT category FROM portfolio").fetchall()
    user = get_current_user(request)
    db.close()
    return templates.TemplateResponse("portfolio.html", {
        "request": request, "user": user, "items": items,
        "categories": [c["category"] for c in categories],
    })


@app.get("/agendar", response_class=HTMLResponse)
def agendar_page(request: Request):
    db = get_db()
    services = db.execute("SELECT * FROM services WHERE active=1 ORDER BY price").fetchall()
    barbers = db.execute("SELECT * FROM barbers WHERE active=1").fetchall()
    user = get_current_user(request)
    db.close()
    return templates.TemplateResponse("agendar.html", {
        "request": request, "user": user, "services": services, "barbers": barbers,
    })


@app.get("/loja", response_class=HTMLResponse)
def loja(request: Request):
    db = get_db()
    products = db.execute("SELECT * FROM products WHERE active=1 ORDER BY category, name").fetchall()
    categories = db.execute("SELECT DISTINCT category FROM products WHERE active=1").fetchall()
    user = get_current_user(request)
    cart = get_cart(request)
    cart_count = sum(i["qty"] for i in cart)
    db.close()
    return templates.TemplateResponse("loja.html", {
        "request": request, "user": user, "products": products,
        "categories": [c["category"] for c in categories], "cart_count": cart_count,
    })


@app.get("/carrinho", response_class=HTMLResponse)
def carrinho(request: Request):
    db = get_db()
    cart = get_cart(request)
    items = []
    total = 0
    for ci in cart:
        p = db.execute("SELECT * FROM products WHERE id=?", (ci["product_id"],)).fetchone()
        if p:
            subtotal = p["price"] * ci["qty"]
            total += subtotal
            items.append({"product": dict(p), "qty": ci["qty"], "subtotal": subtotal})
    user = get_current_user(request)
    db.close()
    return templates.TemplateResponse("carrinho.html", {
        "request": request, "user": user, "items": items, "total": total,
    })


# ---------- Auth ----------
@app.get("/cadastro", response_class=HTMLResponse)
def cadastro_page(request: Request):
    return templates.TemplateResponse("cadastro.html", {"request": request, "user": None, "error": None})


@app.post("/cadastro")
def cadastro(request: Request, name: str = Form(...), email: str = Form(...),
             phone: str = Form(""), password: str = Form(...)):
    name = name.strip()
    email = email.strip().lower()
    phone = phone.strip()
    if not name or "@" not in email or len(password) < 8:
        return templates.TemplateResponse("cadastro.html", {
            "request": request, "user": None,
            "error": "Informe nome e e-mail válidos e uma senha com pelo menos 8 caracteres."
        })
    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    if existing:
        db.close()
        return templates.TemplateResponse("cadastro.html", {
            "request": request, "user": None, "error": "Este e-mail já está cadastrado."
        })
    pw_hash = hash_password(password)
    try:
        cur = db.execute("INSERT INTO users (name, email, phone, password_hash, role) VALUES (?,?,?,?,?)",
                         (name, email, phone, pw_hash, "customer"))
        db.commit()
        user_id = cur.lastrowid
    except sqlite3.IntegrityError:
        db.rollback()
        db.close()
        return templates.TemplateResponse("cadastro.html", {
            "request": request, "user": None,
            "error": "Este e-mail já está cadastrado."
        }, status_code=409)
    finally:
        db.close()
    resp = RedirectResponse(url="/area-cliente", status_code=303)
    set_session(resp, user_id, "customer", name)
    return resp


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "user": None, "error": None})


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    normalized_email = email.strip().lower()
    client_ip = request.client.host if request.client else "unknown"
    now = datetime.utcnow()
    window_start = (now - timedelta(minutes=15)).isoformat()

    db = get_db()
    # Limite persistente no SQLite: continua funcionando entre reinicializações.
    attempts = db.execute("""
        SELECT COUNT(*) AS total FROM auth_login_attempts
        WHERE email=? AND client_ip=? AND attempted_at >= ? AND succeeded=0
    """, (normalized_email, client_ip, window_start)).fetchone()["total"]
    if attempts >= 10:
        db.close()
        return templates.TemplateResponse("login.html", {
            "request": request, "user": None,
            "error": "Muitas tentativas de acesso. Aguarde 15 minutos e tente novamente."
        }, status_code=429)

    user = db.execute("SELECT * FROM users WHERE email=?", (normalized_email,)).fetchone()
    valid = bool(user and user["active"] and verify_password(password, user["password_hash"]))
    if valid:
        # Atualiza hashes legados no próximo login válido, sem exigir redefinição
        # de senha nem invalidar a sessão recém-criada.
        try:
            stored_iterations = int(user["password_hash"].split("$", 3)[1])
        except (IndexError, TypeError, ValueError):
            stored_iterations = 0
        if stored_iterations < 600_000:
            upgraded_hash = hash_password(password)
            db.execute("UPDATE users SET password_hash=? WHERE id=?",
                       (upgraded_hash, user["id"]))
    db.execute(
        "INSERT INTO auth_login_attempts (email, client_ip, attempted_at, succeeded) VALUES (?, ?, ?, ?)",
        (normalized_email, client_ip, now.isoformat(), 1 if valid else 0),
    )
    if valid:
        # Um login válido remove falhas anteriores para não manter o usuário bloqueado.
        db.execute("DELETE FROM auth_login_attempts WHERE email=? AND client_ip=? AND succeeded=0",
                   (normalized_email, client_ip))
    # Limpeza limitada para impedir crescimento indefinido da tabela de tentativas.
    db.execute("DELETE FROM auth_login_attempts WHERE attempted_at < ?",
               ((now - timedelta(days=7)).isoformat(),))
    db.commit()
    db.close()

    if not valid:
        return templates.TemplateResponse("login.html", {
            "request": request, "user": None, "error": "E-mail ou senha inválidos."
        })
    resp = RedirectResponse(url="/admin" if user["role"] in ("admin", "barber") else "/area-cliente", status_code=303)
    set_session(resp, user["id"], user["role"], user["name"])
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse(url="/", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ---------- Área do cliente ----------
@app.get("/area-cliente", response_class=HTMLResponse)
def area_cliente(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    db = get_db()
    appointments = db.execute("""
        SELECT a.*, s.name as service_name, s.price as service_price, b.name as barber_name
        FROM appointments a
        JOIN services s ON a.service_id = s.id
        JOIN barbers b ON a.barber_id = b.id
        WHERE a.user_id=? ORDER BY a.appointment_date DESC, a.start_time DESC
    """, (user["user_id"],)).fetchall()
    orders = db.execute("SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC", (user["user_id"],)).fetchall()
    db.close()
    return templates.TemplateResponse("area_cliente.html", {
        "request": request, "user": user, "appointments": appointments, "orders": orders,
    })


# ---------- API: horários disponíveis ----------
@app.get("/api/slots")
def api_slots(barber_id: int, date: str, service_id: int):
    """Retorna horários disponíveis para um barbeiro em uma data."""
    db = get_db()
    barber = db.execute("SELECT * FROM barbers WHERE id=?", (barber_id,)).fetchone()
    service = db.execute("SELECT duration_min FROM services WHERE id=?", (service_id,)).fetchone()
    if not barber or not service:
        db.close()
        return JSONResponse({"slots": [], "error": "Dados inválidos"})

    duration = service["duration_min"]
    work_start = datetime.strptime(barber["work_start"], "%H:%M")
    work_end = datetime.strptime(barber["work_end"], "%H:%M")
    lunch_start = datetime.strptime(barber["lunch_start"], "%H:%M")
    lunch_end = datetime.strptime(barber["lunch_end"], "%H:%M")

    # Verifica se a data é um dia de trabalho
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        db.close()
        return JSONResponse({"slots": [], "error": "Data inválida"})
    work_days = json.loads(barber["work_days"])  # 1=Seg ... 7=Dom
    if dt.isoweekday() not in work_days:
        db.close()
        return JSONResponse({"slots": [], "error": "Fechado neste dia"})

    # Agendamentos existentes
    booked = db.execute("""
        SELECT start_time, end_time FROM appointments
        WHERE barber_id=? AND appointment_date=? AND status='scheduled'
    """, (barber_id, date)).fetchall()
    db.close()

    booked_ranges = []
    for b in booked:
        s = datetime.strptime(b["start_time"], "%H:%M")
        e = datetime.strptime(b["end_time"], "%H:%M")
        booked_ranges.append((s, e))

    slots = []
    current = work_start
    while current + timedelta(minutes=duration) <= work_end:
        slot_end = current + timedelta(minutes=duration)
        # Pula horário de almoço
        if current < lunch_end and slot_end > lunch_start:
            current = lunch_end
            continue
        # Verifica conflito
        conflict = any(not (slot_end <= bs or current >= be) for bs, be in booked_ranges)
        # Não permite agendar no passado (se for hoje)
        now = datetime.now()
        is_past = (dt.date() == now.date()) and (current <= now)
        if not conflict and not is_past:
            slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=30)

    return JSONResponse({"slots": slots})


@app.post("/api/agendar")
async def api_agendar(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"ok": False, "error": "Faça login para agendar"}, status_code=401)
    try:
        data = await request.json()
        barber_id = int(data["barber_id"])
        service_id = int(data["service_id"])
        appointment_date = datetime.strptime(str(data["date"]), "%Y-%m-%d").date()
        start = datetime.strptime(str(data["start_time"]), "%H:%M")
        notes = str(data.get("notes", "")).strip()[:500]
    except (ValueError, TypeError, KeyError):
        return JSONResponse({"ok": False, "error": "Dados de agendamento inválidos."}, status_code=400)
    if appointment_date < datetime.now().date():
        return JSONResponse({"ok": False, "error": "Não é possível agendar no passado."}, status_code=400)
    db = get_db()
    try:
        barber = db.execute("SELECT * FROM barbers WHERE id=? AND active=1", (barber_id,)).fetchone()
        service = db.execute("SELECT duration_min FROM services WHERE id=? AND active=1", (service_id,)).fetchone()
        if not barber or not service:
            return JSONResponse({"ok": False, "error": "Barbeiro ou serviço indisponível."}, status_code=400)
        end = start + timedelta(minutes=service["duration_min"])
        work_days = json.loads(barber["work_days"] or "[]")
        if appointment_date.isoweekday() not in work_days:
            return JSONResponse({"ok": False, "error": "O barbeiro não atende nesta data."}, status_code=400)
        work_start = datetime.strptime(barber["work_start"], "%H:%M")
        work_end = datetime.strptime(barber["work_end"], "%H:%M")
        lunch_start = datetime.strptime(barber["lunch_start"], "%H:%M")
        lunch_end = datetime.strptime(barber["lunch_end"], "%H:%M")
        if (start < work_start or end > work_end or
                (start < lunch_end and end > lunch_start) or start.minute not in (0, 30)):
            return JSONResponse({"ok": False, "error": "Horário fora da agenda de atendimento."}, status_code=400)
        if appointment_date == datetime.now().date() and start.time() <= datetime.now().time():
            return JSONResponse({"ok": False, "error": "Não é possível agendar um horário passado."}, status_code=400)
        db.execute("BEGIN IMMEDIATE")
        conflict = db.execute("""
            SELECT id FROM appointments WHERE barber_id=? AND appointment_date=? AND status='scheduled'
            AND NOT (end_time <= ? OR start_time >= ?)
        """, (barber_id, appointment_date.isoformat(), start.strftime("%H:%M"), end.strftime("%H:%M"))).fetchone()
        if conflict:
            db.rollback()
            return JSONResponse({"ok": False, "error": "Horário já reservado, escolha outro."}, status_code=409)
        db.execute("""
            INSERT INTO appointments (user_id, barber_id, service_id, appointment_date, start_time, end_time, notes)
            VALUES (?,?,?,?,?,?,?)
        """, (user["user_id"], barber_id, service_id, appointment_date.isoformat(),
              start.strftime("%H:%M"), end.strftime("%H:%M"), notes))
        db.commit()
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        db.rollback()
        return JSONResponse({"ok": False, "error": "Configuração de agenda inválida."}, status_code=400)
    finally:
        db.close()
    try:
        msg = (f"🔔 NOVO AGENDAMENTO!\nCliente: {user['name']}\n"
               f"Data: {appointment_date.strftime('%d/%m/%Y')} às {start.strftime('%H:%M')}\n"
               f"Serviço: {service_id}\nObs: {notes or '-'}")
        send_whatsapp_notify(msg)
    except Exception:
        pass
    return JSONResponse({"ok": True, "message": "Agendamento confirmado!"})


# ---------- API: carrinho ----------
@app.post("/api/carrinho/add")
async def api_cart_add(request: Request):
    try:
        data = await request.json()
        pid, qty = int(data["product_id"]), int(data.get("qty", 1))
    except (ValueError, TypeError, KeyError):
        return JSONResponse({"ok": False, "error": "Produto ou quantidade inválidos."}, status_code=400)
    if pid <= 0 or qty <= 0 or qty > 20:
        return JSONResponse({"ok": False, "error": "A quantidade deve estar entre 1 e 20."}, status_code=400)
    db = get_db()
    product = db.execute("SELECT stock FROM products WHERE id=? AND active=1", (pid,)).fetchone()
    db.close()
    if not product or product["stock"] <= 0:
        return JSONResponse({"ok": False, "error": "Produto indisponível."}, status_code=404)
    cart = get_cart(request)
    cart = [{"product_id": int(i["product_id"]), "qty": int(i["qty"])}
            for i in cart if isinstance(i, dict) and str(i.get("product_id", "")).isdigit()
            and str(i.get("qty", "")).isdigit() and int(i["qty"]) > 0][:50]
    found = False
    for item in cart:
        if item["product_id"] == pid:
            item["qty"] = min(item["qty"] + qty, min(20, product["stock"]))
            found = True
            break
    if not found:
        cart.append({"product_id": pid, "qty": min(qty, product["stock"])})
    resp = JSONResponse({"ok": True, "cart_count": sum(i["qty"] for i in cart)})
    resp.set_cookie(CART_COOKIE, json.dumps(cart), max_age=86400 * 7, httponly=True,
                    secure=IS_PRODUCTION, samesite="lax")
    return resp


@app.post("/api/carrinho/update")
async def api_cart_update(request: Request):
    try:
        data = await request.json()
        pid, qty = int(data["product_id"]), int(data.get("qty", 0))
    except (ValueError, TypeError, KeyError):
        return JSONResponse({"ok": False, "error": "Produto ou quantidade inválidos."}, status_code=400)
    if pid <= 0 or qty < 0 or qty > 20:
        return JSONResponse({"ok": False, "error": "Quantidade inválida."}, status_code=400)
    cart = [i for i in get_cart(request) if isinstance(i, dict) and i.get("product_id") != pid]
    if qty > 0:
        db = get_db()
        product = db.execute("SELECT stock FROM products WHERE id=? AND active=1", (pid,)).fetchone()
        db.close()
        if not product:
            return JSONResponse({"ok": False, "error": "Produto indisponível."}, status_code=404)
        if product["stock"] < 1:
            return JSONResponse(
                {"ok": False, "error": "Produto sem estoque disponível."},
                status_code=409,
            )
        cart.append({"product_id": pid, "qty": min(qty, product["stock"], 20)})
    resp = JSONResponse({"ok": True})
    resp.set_cookie(CART_COOKIE, json.dumps(cart), max_age=86400 * 7, httponly=True,
                    secure=IS_PRODUCTION, samesite="lax")
    return resp


@app.post("/api/carrinho/remove")
async def api_cart_remove(request: Request):
    try:
        data = await request.json()
        pid = int(data["product_id"])
    except (ValueError, TypeError, KeyError):
        return JSONResponse({"ok": False, "error": "Produto inválido."}, status_code=400)
    cart = [i for i in get_cart(request) if isinstance(i, dict) and i.get("product_id") != pid]
    resp = JSONResponse({"ok": True})
    resp.set_cookie(CART_COOKIE, json.dumps(cart), max_age=86400 * 7, httponly=True,
                    secure=IS_PRODUCTION, samesite="lax")
    return resp


@app.post("/finalizar-pedido")
async def finalizar_pedido(request: Request, customer_name: str = Form(...),
                           customer_phone: str = Form(...), address: str = Form(...),
                           payment_method: str = Form("pix")):
    user = get_current_user(request)
    customer_name, customer_phone, address = customer_name.strip(), customer_phone.strip(), address.strip()
    if not customer_name or not customer_phone or not address or len(customer_name) > 120 or len(customer_phone) > 40 or len(address) > 500:
        return JSONResponse({"ok": False, "error": "Preencha os dados de entrega corretamente."}, status_code=400)
    if payment_method not in {"pix", "dinheiro", "cartao"}:
        return JSONResponse({"ok": False, "error": "Forma de pagamento inválida."}, status_code=400)
    raw_cart = get_cart(request)
    try:
        cart_map = {}
        for item in raw_cart:
            if not isinstance(item, dict):
                raise ValueError()
            pid, qty = int(item["product_id"]), int(item["qty"])
            if pid <= 0 or qty <= 0 or qty > 20:
                raise ValueError()
            cart_map[pid] = cart_map.get(pid, 0) + qty
        if not cart_map or len(cart_map) > 50 or any(qty > 20 for qty in cart_map.values()):
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        return JSONResponse({"ok": False, "error": "Carrinho inválido. Revise os produtos e quantidades."}, status_code=400)
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        verified_items = []
        total = 0.0
        for pid, qty in cart_map.items():
            product = db.execute("SELECT id, name, price, stock FROM products WHERE id=? AND active=1", (pid,)).fetchone()
            if not product or product["stock"] < qty:
                db.rollback()
                return JSONResponse({"ok": False, "error": "Um produto está indisponível ou sem estoque suficiente."}, status_code=409)
            verified_items.append((product, qty))
            total += product["price"] * qty
        cur = db.execute("""
            INSERT INTO orders (user_id, customer_name, customer_phone, address, total, payment_method, status)
            VALUES (?,?,?,?,?,?, 'pending')
        """, (user["user_id"] if user else None, customer_name, customer_phone, address, total, payment_method))
        order_id = cur.lastrowid
        for product, qty in verified_items:
            changed = db.execute("UPDATE products SET stock=stock-? WHERE id=? AND stock>=? AND active=1",
                                 (qty, product["id"], qty))
            if changed.rowcount != 1:
                db.rollback()
                return JSONResponse({"ok": False, "error": "Estoque alterado durante a compra. Tente novamente."}, status_code=409)
            db.execute("INSERT INTO order_items (order_id, product_id, product_name, quantity, price) VALUES (?,?,?,?,?)",
                       (order_id, product["id"], product["name"], qty, product["price"]))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    try:
        send_whatsapp_notify(f"🛍️ NOVO PEDIDO NA LOJA!\nPedido #{order_id}\nCliente: {customer_name}\nTotal: R$ {total:.2f}\nPagamento: {payment_method}")
    except Exception:
        pass
    resp = RedirectResponse(url=f"/pedido-confirmado/{order_id}", status_code=303)
    resp.delete_cookie(CART_COOKIE)
    if not user:
        receipt = serializer.dumps({"order_id": order_id, "purpose": "guest-order-receipt"})
        resp.set_cookie("barbearia_order_receipt", receipt, max_age=1800, httponly=True,
                        secure=IS_PRODUCTION, samesite="lax")
    return resp


@app.get("/pedido-confirmado/{order_id}", response_class=HTMLResponse)
def pedido_confirmado(request: Request, order_id: int):
    user = get_current_user(request)
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        db.close()
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    owns_order = bool(user and user.get("user_id") == order["user_id"])
    is_admin = bool(user and user.get("role") == "admin")
    guest_receipt_valid = False
    if order["user_id"] is None:
        receipt = request.cookies.get("barbearia_order_receipt", "")
        try:
            receipt_data = serializer.loads(receipt, max_age=1800)
            guest_receipt_valid = (receipt_data.get("purpose") == "guest-order-receipt"
                                   and receipt_data.get("order_id") == order_id)
        except Exception:
            guest_receipt_valid = False
    if not (owns_order or is_admin or guest_receipt_valid):
        db.close()
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    items = db.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,)).fetchall()
    db.close()
    return templates.TemplateResponse("pedido_confirmado.html", {
        "request": request, "user": user, "order": order, "items": items,
    })


# ---------- Integrações: Google/Apple Calendar (feed ICS) + WhatsApp ----------
def send_whatsapp_notify(message: str):
    """Envia notificação via webhook (Evolution API etc.) se configurado."""
    settings = get_settings()
    url = settings.get("whatsapp_api_url", "").strip()
    if not url:
        return
    try:
        import urllib.request
        number = settings.get("whatsapp_notify", "").strip()
        if not number:
            return
        data = json.dumps({"number": number, "text": message}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass  # falha silenciosa — não quebra o agendamento


@app.get("/feed/agenda.ics")
def agenda_ics(token: str):
    """Feed de calendário assinável no Google Calendar e Apple Calendar."""
    settings = get_settings()
    if token != settings.get("calendar_token"):
        raise HTTPException(status_code=403, detail="Token inválido")
    db = get_db()
    appts = db.execute("""
        SELECT a.*, s.name as service_name, s.price as service_price,
               u.name as customer_name, u.phone as customer_phone, b.name as barber_name
        FROM appointments a
        JOIN services s ON a.service_id = s.id
        JOIN users u ON a.user_id = u.id
        JOIN barbers b ON a.barber_id = b.id
        WHERE a.status = 'scheduled'
        ORDER BY a.appointment_date, a.start_time
    """).fetchall()
    db.close()

    def ics_dt(date_str, time_str):
        return date_str.replace("-", "") + "T" + time_str.replace(":", "") + "00"

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Barbearia//Agenda//PT",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{settings['shop_name']} - Agenda",
        "X-WR-TIMEZONE:America/Sao_Paulo",
    ]
    for a in appts:
        uid = f"apt{a['id']}@{settings['shop_name'].lower().replace(' ','')}"
        dtstart = ics_dt(a["appointment_date"], a["start_time"])
        dtend = ics_dt(a["appointment_date"], a["end_time"])
        desc = f"{a['service_name']} - R$ {a['service_price']:.2f}\\nCliente: {a['customer_name']}\\nTel: {a['customer_phone'] or '-'}\\nBarbeiro: {a['barber_name']}"
        if a["notes"]:
            desc += f"\\nObs: {a['notes']}"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{dtstart}",
            f"DTSTART:{dtstart}",
            f"DTEND:{dtend}",
            f"SUMMARY:{a['customer_name']} - {a['service_name']}",
            f"DESCRIPTION:{desc}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    content = "\r\n".join(lines)
    return Response(content=content, media_type="text/calendar",
                    headers={"Content-Disposition": "inline; filename=agenda.ics",
                             "Cache-Control": "no-cache"})


# ---------- Área Administrativa (Barbeiro) ----------
@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    user = get_current_user(request)
    if not user or user.get("role") not in ("admin", "barber"):
        return RedirectResponse(url="/login", status_code=303)
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    today_appts = db.execute("""
        SELECT a.*, s.name as service_name, u.name as customer_name, u.phone as customer_phone
        FROM appointments a
        JOIN services s ON a.service_id = s.id
        JOIN users u ON a.user_id = u.id
        WHERE a.appointment_date=? AND a.status='scheduled'
        ORDER BY a.start_time
    """, (today,)).fetchall()
    total_today = sum(a["service_price"] if "service_price" in a.keys() else 0 for a in today_appts)
    # Recalcular total do dia
    total_valor = 0
    for a in today_appts:
        s = db.execute("SELECT price FROM services WHERE id=?", (a["service_id"],)).fetchone()
        total_valor += s["price"] if s else 0
    pending_orders = db.execute("SELECT COUNT(*) as c FROM orders WHERE status='paid'").fetchone()["c"]
    total_services = db.execute("SELECT COUNT(*) as c FROM services WHERE active=1").fetchone()["c"]
    total_products = db.execute("SELECT COUNT(*) as c FROM products WHERE active=1").fetchone()["c"]
    db.close()
    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request, "user": user, "today_appts": today_appts,
        "total_valor": total_valor, "pending_orders": pending_orders,
        "total_services": total_services, "total_products": total_products, "today": today,
    })



@app.get("/admin/financeiro", response_class=HTMLResponse)
def admin_financeiro(request: Request, inicio: Optional[str] = None, fim: Optional[str] = None):
    """Relatório financeiro com acesso restrito ao administrador."""
    user = get_current_user(request)
    if not user or user.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=303)

    today = datetime.now().strftime("%Y-%m-%d")
    inicio = inicio or today[:8] + "01"
    fim = fim or today
    try:
        inicio_date = datetime.strptime(inicio, "%Y-%m-%d").date()
        fim_date = datetime.strptime(fim, "%Y-%m-%d").date()
        if inicio_date > fim_date or (fim_date - inicio_date).days > 366:
            raise ValueError
    except (TypeError, ValueError):
        return RedirectResponse(url="/admin/financeiro?erro=periodo", status_code=303)

    db = get_db()
    try:
        totals = db.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN transaction_type='income' AND status='paid'
                    THEN amount_cents ELSE 0 END), 0) AS income_cents,
                COALESCE(SUM(CASE WHEN transaction_type='expense' AND status='paid'
                    THEN amount_cents ELSE 0 END), 0) AS expense_cents,
                COALESCE(SUM(CASE WHEN status='pending'
                    THEN amount_cents ELSE 0 END), 0) AS pending_cents
            FROM financial_transactions
            WHERE occurred_on BETWEEN ? AND ?
        """, (inicio, fim)).fetchone()
        transactions = db.execute("""
            SELECT t.*, b.name AS barber_name, u.name AS creator_name
            FROM financial_transactions t
            LEFT JOIN barbers b ON b.id=t.barber_id
            LEFT JOIN users u ON u.id=t.created_by
            WHERE t.occurred_on BETWEEN ? AND ?
            ORDER BY t.occurred_on DESC, t.id DESC
            LIMIT 250
        """, (inicio, fim)).fetchall()
        production = db.execute("""
            SELECT b.id AS barber_id, b.name AS barber_name,
                   COUNT(a.id) AS completed_services,
                   COALESCE(SUM(COALESCE(a.service_price_cents, CAST(ROUND(s.price * 100) AS INTEGER))), 0) AS production_cents,
                   COALESCE(cs.commission_percent, 0) AS commission_percent
            FROM barbers b
            LEFT JOIN appointments a
              ON a.barber_id=b.id AND a.status='completed'
             AND a.appointment_date BETWEEN ? AND ?
            LEFT JOIN services s ON s.id=a.service_id
            LEFT JOIN barber_commission_settings cs ON cs.barber_id=b.id
            WHERE b.active=1
            GROUP BY b.id, b.name, cs.commission_percent
            ORDER BY production_cents DESC, b.name
        """, (inicio, fim)).fetchall()
    finally:
        db.close()

    return templates.TemplateResponse("admin/financeiro.html", {
        "request": request, "user": user, "inicio": inicio, "fim": fim,
        "totals": totals, "transactions": transactions, "production": production,
        "net_cents": totals["income_cents"] - totals["expense_cents"],
    })



@app.post("/admin/financeiro/comissao")
def admin_financeiro_comissao(
    request: Request,
    barber_id: int = Form(...),
    commission_percent: str = Form(...),
):
    """Define a taxa de comissão por barbeiro; somente administrador pode alterar."""
    user = get_current_user(request)
    if not user or user.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=303)
    import math
    try:
        rate = float(commission_percent.strip().replace(",", "."))
    except (TypeError, ValueError, AttributeError):
        return RedirectResponse(url="/admin/financeiro?erro=comissao", status_code=303)
    if not math.isfinite(rate) or rate < 0 or rate > 100:
        return RedirectResponse(url="/admin/financeiro?erro=comissao", status_code=303)

    db = get_db()
    try:
        exists = db.execute("SELECT id FROM barbers WHERE id=? AND active=1", (barber_id,)).fetchone()
        if not exists:
            return RedirectResponse(url="/admin/financeiro?erro=barbeiro", status_code=303)
        db.execute("""
            INSERT INTO barber_commission_settings (barber_id, commission_percent)
            VALUES (?, ?)
            ON CONFLICT(barber_id) DO UPDATE SET
                commission_percent=excluded.commission_percent,
                updated_at=CURRENT_TIMESTAMP
        """, (barber_id, rate))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/admin/financeiro?salvo=comissao", status_code=303)


@app.post("/admin/financeiro/lancamento")
def admin_financeiro_lancamento(
    request: Request,
    transaction_type: str = Form(...),
    category: str = Form(...),
    description: str = Form(...),
    amount: str = Form(...),
    occurred_on: str = Form(...),
    payment_method: str = Form(""),
    status: str = Form("paid"),
):
    """Registra uma entrada ou despesa manual sem expor o financeiro aos barbeiros."""
    user = get_current_user(request)
    if not user or user.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=303)

    import math
    category, description = category.strip(), description.strip()
    payment_method = payment_method.strip()
    try:
        normalized_amount = amount.strip().replace(",", ".")
        amount_value = float(normalized_amount)
        occurred = datetime.strptime(occurred_on, "%Y-%m-%d").date()
    except (TypeError, ValueError, OverflowError):
        return RedirectResponse(url="/admin/financeiro?erro=dados", status_code=303)

    if (transaction_type not in {"income", "expense"}
            or status not in {"pending", "paid", "cancelled"}
            or not category or len(category) > 80
            or not description or len(description) > 240
            or len(payment_method) > 40
            or not math.isfinite(amount_value)
            or amount_value <= 0 or amount_value > 100_000_000):
        return RedirectResponse(url="/admin/financeiro?erro=dados", status_code=303)

    amount_cents = int(round(amount_value * 100))
    if amount_cents <= 0:
        return RedirectResponse(url="/admin/financeiro?erro=dados", status_code=303)

    db = get_db()
    try:
        db.execute("""
            INSERT INTO financial_transactions
                (transaction_type, category, description, amount_cents,
                 occurred_on, payment_method, status, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (transaction_type, category, description, amount_cents,
              occurred.isoformat(), payment_method or None, status, user["user_id"]))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/admin/financeiro?salvo=1", status_code=303)


@app.get("/admin/agenda", response_class=HTMLResponse)
def admin_agenda(request: Request, date: Optional[str] = None):
    user = get_current_user(request)
    if not user or user.get("role") not in ("admin", "barber"):
        return RedirectResponse(url="/login", status_code=303)
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    db = get_db()
    appts = db.execute("""
        SELECT a.*, s.name as service_name, s.price as service_price, u.name as customer_name, u.phone as customer_phone
        FROM appointments a
        JOIN services s ON a.service_id = s.id
        JOIN users u ON a.user_id = u.id
        WHERE a.appointment_date=? ORDER BY a.start_time
    """, (date,)).fetchall()
    db.close()
    return templates.TemplateResponse("admin/agenda.html", {
        "request": request, "user": user, "appts": appts, "date": date,
    })


@app.post("/admin/agenda/status")
async def admin_agenda_status(request: Request):
    user = get_current_user(request)
    if not user or user.get("role") not in ("admin", "barber"):
        return JSONResponse({"ok": False, "error": "Acesso não autorizado."}, status_code=403)
    try:
        data = await request.json()
        appointment_id = int(data["appointment_id"])
        status = str(data["status"]).strip().lower()
    except (ValueError, TypeError, KeyError):
        return JSONResponse({"ok": False, "error": "Dados inválidos."}, status_code=400)
    if status not in {"scheduled", "completed", "cancelled"}:
        return JSONResponse({"ok": False, "error": "Status inválido."}, status_code=400)
    db = get_db()
    try:
        # Barbeiros só podem alterar agendamentos vinculados à própria agenda.
        if user.get("role") == "barber":
            updated = db.execute("""
                UPDATE appointments SET status=?
                WHERE id=? AND barber_id IN (
                    SELECT id FROM barbers WHERE user_id=?
                )
            """, (status, appointment_id, user["user_id"]))
        else:
            updated = db.execute(
                "UPDATE appointments SET status=? WHERE id=?",
                (status, appointment_id),
            )
        if updated.rowcount != 1:
            db.rollback()
            return JSONResponse(
                {"ok": False, "error": "Agendamento não encontrado ou sem permissão."},
                status_code=404,
            )

        # Gera/atualiza o lançamento vinculado ao atendimento de forma idempotente.
        # A unicidade de appointment_id impede duplicar a receita ao clicar duas vezes.
        appointment = db.execute("""
            SELECT a.id, a.barber_id, a.service_price_cents, s.price
            FROM appointments a
            JOIN services s ON s.id = a.service_id
            WHERE a.id = ?
        """, (appointment_id,)).fetchone()
        if status == "completed" and appointment:
            price_cents = appointment["service_price_cents"]
            if price_cents is None:
                price_cents = int(round(float(appointment["price"]) * 100))
                db.execute(
                    "UPDATE appointments SET service_price_cents=? WHERE id=?",
                    (price_cents, appointment_id),
                )
            if price_cents > 0:
                db.execute("""
                    INSERT INTO financial_transactions
                        (transaction_type, category, description, amount_cents,
                         occurred_on, status, barber_id, appointment_id, created_by)
                    VALUES ('income', 'Serviços', ?, ?, date('now', 'localtime'),
                            'paid', ?, ?, ?)
                    ON CONFLICT(appointment_id) WHERE appointment_id IS NOT NULL
                    DO UPDATE SET status='paid', amount_cents=excluded.amount_cents,
                                  barber_id=excluded.barber_id
                """, (
                    f"Atendimento concluído #{appointment_id}", price_cents,
                    appointment["barber_id"], appointment_id, user["user_id"],
                ))
        else:
            # Se o atendimento for reaberto ou cancelado, não o mantém como receita paga.
            db.execute("""
                UPDATE financial_transactions SET status='cancelled'
                WHERE appointment_id=? AND transaction_type='income'
            """, (appointment_id,))
        db.commit()
    finally:
        db.close()
    return JSONResponse({"ok": True})


@app.get("/admin/servicos", response_class=HTMLResponse)
def admin_servicos(request: Request):
    user = get_current_user(request)
    if not user or user.get("role") not in ("admin", "barber"):
        return RedirectResponse(url="/login", status_code=303)
    db = get_db()
    services = [dict(r) for r in db.execute("SELECT * FROM services ORDER BY category, price").fetchall()]
    db.close()
    return templates.TemplateResponse("admin/servicos.html", {"request": request, "user": user, "services": services})


@app.post("/admin/servicos/salvar")
def admin_servico_salvar(request: Request, name: str = Form(...), description: str = Form(""),
                         price: float = Form(...), duration_min: int = Form(30),
                         category: str = Form("Cabelo"), service_id: Optional[int] = Form(None)):
    user = get_current_user(request)
    if not user or user.get("role") not in ("admin", "barber"):
        return RedirectResponse(url="/login", status_code=303)
    name, description, category = name.strip(), description.strip(), category.strip()
    # Nunca confiar nos valores numéricos enviados pelo formulário.
    import math
    if (not name or len(name) > 120 or len(description) > 2000 or
            not category or len(category) > 80 or
            not math.isfinite(price) or price < 0 or price > 1_000_000 or
            duration_min < 5 or duration_min > 480):
        return RedirectResponse(url="/admin/servicos?erro=dados", status_code=303)
    db = get_db()
    try:
        if service_id:
            changed = db.execute(
                "UPDATE services SET name=?, description=?, price=?, duration_min=?, category=? WHERE id=?",
                (name, description, price, duration_min, category, service_id),
            )
            if changed.rowcount != 1:
                db.rollback()
                return RedirectResponse(url="/admin/servicos?erro=nao_encontrado", status_code=303)
        else:
            db.execute(
                "INSERT INTO services (name, description, price, duration_min, category) VALUES (?,?,?,?,?)",
                (name, description, price, duration_min, category),
            )
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/admin/servicos?salvo=1", status_code=303)


@app.post("/admin/servicos/excluir")
def admin_servico_excluir(request: Request, service_id: int = Form(...)):
    user = get_current_user(request)
    if not user or user.get("role") not in ("admin", "barber"):
        return RedirectResponse(url="/login", status_code=303)
    db = get_db()
    db.execute("UPDATE services SET active=0 WHERE id=?", (service_id,))
    db.commit()
    db.close()
    return RedirectResponse(url="/admin/servicos", status_code=303)


@app.get("/admin/produtos", response_class=HTMLResponse)
def admin_produtos(request: Request):
    user = get_current_user(request)
    if not user or user.get("role") not in ("admin", "barber"):
        return RedirectResponse(url="/login", status_code=303)
    db = get_db()
    products = [dict(r) for r in db.execute("SELECT * FROM products ORDER BY category, name").fetchall()]
    db.close()
    return templates.TemplateResponse("admin/produtos.html", {"request": request, "user": user, "products": products})


@app.post("/admin/produtos/salvar")
def admin_produto_salvar(request: Request, name: str = Form(...), description: str = Form(""),
                         price: float = Form(...), stock: int = Form(0),
                         category: str = Form("Geral"), image_url: str = Form(""),
                         product_id: Optional[int] = Form(None)):
    user = get_current_user(request)
    if not user or user.get("role") not in ("admin", "barber"):
        return RedirectResponse(url="/login", status_code=303)
    import math
    name, description, category, image_url = (
        name.strip(), description.strip(), category.strip(), image_url.strip()
    )
    if (not name or len(name) > 120 or len(description) > 2000 or
            not category or len(category) > 80 or len(image_url) > 1000 or
            not math.isfinite(price) or price < 0 or price > 1_000_000 or
            stock < 0 or stock > 1_000_000):
        return RedirectResponse(url="/admin/produtos?erro=dados", status_code=303)
    if image_url:
        from urllib.parse import urlsplit
        parsed_image = urlsplit(image_url)
        if parsed_image.scheme not in {"https", "http"} or not parsed_image.hostname:
            return RedirectResponse(url="/admin/produtos?erro=imagem", status_code=303)
    db = get_db()
    try:
        if product_id:
            changed = db.execute(
                "UPDATE products SET name=?, description=?, price=?, stock=?, category=?, image_url=? WHERE id=?",
                (name, description, price, stock, category, image_url, product_id),
            )
            if changed.rowcount != 1:
                db.rollback()
                return RedirectResponse(url="/admin/produtos?erro=nao_encontrado", status_code=303)
        else:
            db.execute(
                "INSERT INTO products (name, description, price, stock, category, image_url) VALUES (?,?,?,?,?,?)",
                (name, description, price, stock, category, image_url),
            )
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/admin/produtos?salvo=1", status_code=303)


@app.post("/admin/produtos/excluir")
def admin_produto_excluir(request: Request, product_id: int = Form(...)):
    user = get_current_user(request)
    if not user or user.get("role") not in ("admin", "barber"):
        return RedirectResponse(url="/login", status_code=303)
    db = get_db()
    db.execute("UPDATE products SET active=0 WHERE id=?", (product_id,))
    db.commit()
    db.close()
    return RedirectResponse(url="/admin/produtos", status_code=303)


@app.get("/admin/portfolio", response_class=HTMLResponse)
def admin_portfolio(request: Request):
    user = get_current_user(request)
    if not user or user.get("role") not in ("admin", "barber"):
        return RedirectResponse(url="/login", status_code=303)
    db = get_db()
    items = db.execute("SELECT * FROM portfolio ORDER BY id DESC").fetchall()
    services = db.execute("SELECT * FROM services WHERE active=1").fetchall()
    db.close()
    return templates.TemplateResponse("admin/portfolio.html", {
        "request": request, "user": user, "items": items, "services": services,
    })


@app.post("/admin/portfolio/salvar")
def admin_portfolio_salvar(request: Request, name: str = Form(...), description: str = Form(""),
                           image_url: str = Form(...), category: str = Form("Corte"),
                           service_id: Optional[int] = Form(None)):
    user = get_current_user(request)
    if not user or user.get("role") not in ("admin", "barber"):
        return RedirectResponse(url="/login", status_code=303)
    db = get_db()
    db.execute("INSERT INTO portfolio (name, description, image_url, category, service_id) VALUES (?,?,?,?,?)",
               (name, description, image_url, category, service_id))
    db.commit()
    db.close()
    return RedirectResponse(url="/admin/portfolio", status_code=303)


@app.post("/admin/portfolio/excluir")
def admin_portfolio_excluir(request: Request, item_id: int = Form(...)):
    user = get_current_user(request)
    if not user or user.get("role") not in ("admin", "barber"):
        return RedirectResponse(url="/login", status_code=303)
    db = get_db()
    db.execute("DELETE FROM portfolio WHERE id=?", (item_id,))
    db.commit()
    db.close()
    return RedirectResponse(url="/admin/portfolio", status_code=303)


@app.get("/admin/pedidos", response_class=HTMLResponse)
def admin_pedidos(request: Request):
    user = get_current_user(request)
    if not user or user.get("role") not in ("admin", "barber"):
        return RedirectResponse(url="/login", status_code=303)
    db = get_db()
    orders = db.execute("""
        SELECT o.*, 
               (SELECT GROUP_CONCAT(product_name || ' x' || quantity, ', ') 
                FROM order_items WHERE order_id=o.id) as items_summary
        FROM orders o ORDER BY o.created_at DESC
    """).fetchall()
    db.close()
    return templates.TemplateResponse("admin/pedidos.html", {"request": request, "user": user, "orders": orders})


@app.get("/admin/configuracoes", response_class=HTMLResponse)
def admin_configuracoes(request: Request):
    user = get_current_user(request)
    if not user or user.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=303)
    settings = get_settings()
    return templates.TemplateResponse("admin/configuracoes.html", {
        "request": request, "user": user, "settings": settings,
    })


@app.post("/admin/configuracoes/salvar")
async def admin_configuracoes_salvar(request: Request):
    user = get_current_user(request)
    if not user or user.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=303)
    form = await request.form()
    allowed_keys = {"shop_name", "shop_slogan", "logo_url", "color_primary",
                    "color_primary_light", "color_bg", "color_card", "color_text",
                    "whatsapp", "instagram", "address", "whatsapp_notify",
                    "whatsapp_api_url"}
    db = get_db()
    try:
        for key in allowed_keys.intersection(form.keys()):
            value = str(form[key]).strip()[:2000]
            if key in {"whatsapp_api_url"} and value:
                from urllib.parse import urlsplit
                parsed = urlsplit(value)
                if parsed.scheme != "https" or not parsed.hostname:
                    db.close()
                    return RedirectResponse(url="/admin/configuracoes?erro=url", status_code=303)
            db.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, value))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url="/admin/configuracoes?salvo=1", status_code=303)


# ---------- Gerenciamento de Barbeiros ----------
@app.get("/admin/barbeiros", response_class=HTMLResponse)
def admin_barbeiros(request: Request):
    user = get_current_user(request)
    if not user or user.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=303)
    db = get_db()
    barbers = [dict(r) for r in db.execute("""
        SELECT b.*, u.email as login_email
        FROM barbers b LEFT JOIN users u ON b.user_id = u.id
        ORDER BY b.active DESC, b.name
    """).fetchall()]
    db.close()
    return templates.TemplateResponse("admin/barbeiros.html", {
        "request": request, "user": user, "barbers": barbers,
    })


@app.post("/admin/barbeiros/salvar")
async def admin_barbeiro_salvar(request: Request):
    user = get_current_user(request)
    if not user or user.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=303)
    form = await request.form()
    name = form.get("name", "").strip()
    if not name:
        return RedirectResponse(url="/admin/barbeiros?erro=1", status_code=303)
    db = get_db()
    barber_id = form.get("barber_id")
    work_days = json.dumps([int(d) for d in form.getlist("work_days")] or [1,2,3,4,5,6])
    email = form.get("email", "").strip().lower()
    password = form.get("password", "")
    if email and ("@" not in email or len(email) > 254):
        db.close()
        return RedirectResponse(url="/admin/barbeiros?erro=email", status_code=303)
    if password and len(password) < 8:
        db.close()
        return RedirectResponse(url="/admin/barbeiros?erro=senha", status_code=303)

    if barber_id:
        db.execute("""UPDATE barbers SET name=?, bio=?, photo_url=?, work_start=?, work_end=?,
                      lunch_start=?, lunch_end=?, work_days=?, active=? WHERE id=?""",
                   (name, form.get("bio",""), form.get("photo_url",""),
                    form.get("work_start","09:00"), form.get("work_end","18:00"),
                    form.get("lunch_start","12:00"), form.get("lunch_end","13:00"),
                    work_days, 1 if form.get("active") else 0, barber_id))
        if email and password:
            existing = db.execute("SELECT user_id FROM barbers WHERE id=?", (barber_id,)).fetchone()
            if existing and existing["user_id"]:
                db.execute("UPDATE users SET email=?, password_hash=?, name=?, session_version=session_version+1 WHERE id=?",
                           (email, hash_password(password), name, existing["user_id"]))
            else:
                cur = db.execute("INSERT INTO users (name, email, password_hash, role) VALUES (?,?,?,?)",
                                 (name, email, hash_password(password), "barber"))
                db.execute("UPDATE barbers SET user_id=? WHERE id=?", (cur.lastrowid, barber_id))
    else:
        cur = db.execute("""INSERT INTO barbers (name, bio, photo_url, work_start, work_end,
                          lunch_start, lunch_end, work_days, active) VALUES (?,?,?,?,?,?,?,?,1)""",
                        (name, form.get("bio",""), form.get("photo_url",""),
                         form.get("work_start","09:00"), form.get("work_end","18:00"),
                         form.get("lunch_start","12:00"), form.get("lunch_end","13:00"), work_days))
        bid = cur.lastrowid
        if email and password:
            uc = db.execute("INSERT INTO users (name, email, password_hash, role) VALUES (?,?,?,?)",
                            (name, email, hash_password(password), "barber"))
            db.execute("UPDATE barbers SET user_id=? WHERE id=?", (uc.lastrowid, bid))
    db.commit()
    db.close()
    return RedirectResponse(url="/admin/barbeiros?salvo=1", status_code=303)


@app.post("/admin/barbeiros/excluir")
async def admin_barbeiro_excluir(request: Request):
    user = get_current_user(request)
    if not user or user.get("role") != "admin":
        return RedirectResponse(url="/login", status_code=303)
    form = await request.form()
    db = get_db()
    db.execute("UPDATE barbers SET active=0 WHERE id=?", (form.get("barber_id"),))
    db.commit()
    db.close()
    return RedirectResponse(url="/admin/barbeiros", status_code=303)


# ---------- Versão App Mobile (PWA) ----------
@app.get("/app", response_class=HTMLResponse)
def mobile_app(request: Request):
    """Painel simplificado otimizado para celular do barbeiro."""
    user = get_current_user(request)
    if not user or user.get("role") not in ("admin", "barber"):
        return RedirectResponse(url="/login?next=/app", status_code=303)
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    today_appts = db.execute("""
        SELECT a.*, s.name as service_name, s.price as service_price,
               u.name as customer_name, u.phone as customer_phone
        FROM appointments a
        JOIN services s ON a.service_id = s.id
        JOIN users u ON a.user_id = u.id
        WHERE a.appointment_date=? ORDER BY a.start_time
    """, (today,)).fetchall()
    services = db.execute("SELECT * FROM services WHERE active=1 ORDER BY price").fetchall()
    products = db.execute("SELECT * FROM products WHERE active=1 ORDER BY name").fetchall()
    settings = get_settings(db)
    db.close()
    return templates.TemplateResponse("mobile.html", {
        "request": request, "user": user, "today_appts": today_appts,
        "services": services, "products": products, "settings": settings, "today": today,
    })


@app.get("/manifest.json")
def manifest():
    settings = get_settings()
    return {
        "name": settings["shop_name"] + " - Barbeiro",
        "short_name": settings["shop_name"][:12],
        "start_url": "/app",
        "display": "standalone",
        "background_color": settings["color_bg"],
        "theme_color": settings["color_primary"],
        "icons": [{"src": "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect width='100' height='100' rx='20' fill='%230f0f0f'/><text x='50' y='65' font-size='50' text-anchor='middle' fill='%23c9a227' font-weight='bold'>✂</text></svg>", "sizes": "192x192", "type": "image/svg+xml"}],
    }


# Rotas incrementais de clientes, alteração e recuperação de senha.
from security_routes import register_security_routes

register_security_routes(
    app, templates, get_db, get_current_user, hash_password, verify_password
)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
