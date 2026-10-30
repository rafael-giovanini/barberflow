"""Leitura e armazenamento protegido das configurações de envio SMTP."""
import base64
import hashlib
import os
import ipaddress
from email.utils import parseaddr
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken


SMTP_TEXT_FIELDS = {
    "smtp_host": "SMTP_HOST",
    "smtp_port": "SMTP_PORT",
    "smtp_user": "SMTP_USER",
    "smtp_from": "SMTP_FROM",
    "smtp_security": "SMTP_SECURITY",
    "app_base_url": "APP_BASE_URL",
}


def _cipher():
    secret = os.getenv("SECRET_KEY", "").strip()
    if len(secret) < 32 or secret == "troque-esta-chave-por-uma-secreta-sua-2024":
        raise RuntimeError("Configure uma SECRET_KEY persistente com pelo menos 32 caracteres.")
    material = hashlib.sha256(b"barberflow:smtp-password:v1:" + secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def get_smtp_config(db):
    """Retorna a configuração ativa, usando banco quando o painel já foi salvo."""
    rows = {row["key"]: row["value"] for row in db.execute(
        "SELECT key, value FROM settings WHERE key LIKE 'smtp_%' OR key='app_base_url'"
    ).fetchall()}
    config = {}
    for setting, env_name in SMTP_TEXT_FIELDS.items():
        config[setting] = rows[setting] if setting in rows else os.getenv(env_name, "")
    if config["smtp_security"].lower() not in {"starttls", "ssl", "none"}:
        starttls = os.getenv("SMTP_STARTTLS", "1").lower() not in ("0", "false", "no")
        config["smtp_security"] = "starttls" if starttls else "none"
    encrypted = rows.get("smtp_password_encrypted", "")
    config["password_encrypted"] = encrypted
    if "smtp_password_encrypted" in rows and not encrypted:
        # Valor vazio no banco funciona como substituição explícita para não
        # reativar silenciosamente uma senha antiga do ambiente.
        config["password"] = ""
        config["password_unavailable"] = False
    elif encrypted:
        try:
            config["password"] = _cipher().decrypt(encrypted.encode("ascii")).decode("utf-8")
        except (InvalidToken, RuntimeError, ValueError, UnicodeError):
            config["password"] = ""
            config["password_unavailable"] = True
    else:
        config["password"] = os.getenv("SMTP_PASSWORD", "")
        config["password_unavailable"] = False
    configured_by_panel = "smtp_enabled" in rows
    config["enabled"] = (
        rows.get("smtp_enabled") == "1" if configured_by_panel else
        bool(config["smtp_host"].strip() and config["smtp_from"].strip())
    )
    config["password_is_configured"] = bool(config["password"])
    return config


def public_smtp_settings(config):
    """Campos permitidos na interface; a senha em texto nunca é devolvida."""
    return {
        "enabled": config["enabled"],
        "host": config["smtp_host"],
        "port": config["smtp_port"],
        "user": config["smtp_user"],
        "from": config["smtp_from"],
        "security": config["smtp_security"],
        "base_url": config["app_base_url"],
        "password_is_configured": config["password_is_configured"],
        "password_unavailable": config.get("password_unavailable", False),
    }


def validate_smtp_form(form, password_is_configured=False):
    enabled = bool(form.get("smtp_enabled"))
    host = str(form.get("smtp_host", "")).strip()[:255]
    sender = str(form.get("smtp_from", "")).strip()[:320]
    username = str(form.get("smtp_user", "")).strip()[:320]
    base_url = str(form.get("app_base_url", "")).strip().rstrip("/")[:500]
    password = str(form.get("smtp_password", ""))
    security = str(form.get("smtp_security", "starttls")).strip().lower()
    if security not in {"starttls", "ssl", "none"}:
        return None, "seguranca"
    try:
        port = int(str(form.get("smtp_port", "587")).strip())
    except (TypeError, ValueError):
        return None, "porta"
    if not 1 <= port <= 65535:
        return None, "porta"
    if len(password) > 512:
        return None, "senha"
    if enabled:
        sender_address = parseaddr(sender)[1]
        if (not host or not sender_address or sender_address.count("@") != 1
                or any(char in sender for char in "\r\n")):
            return None, "campos"
        parsed = urlsplit(base_url)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        try:
            is_loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            is_loopback = hostname == "localhost" or hostname.endswith(".localhost")
        if parsed.scheme != "https" or not hostname or is_loopback:
            return None, "url"
        if username and not (password or password_is_configured):
            return None, "senha"
    return {
        "enabled": enabled,
        "host": host,
        "port": str(port),
        "user": username,
        "from": sender,
        "security": security,
        "base_url": base_url,
        "password": password,
        "clear_password": bool(form.get("smtp_clear_password")),
    }, None


def save_smtp_settings(db, values):
    if values["password"]:
        encrypted = _cipher().encrypt(values["password"].encode("utf-8")).decode("ascii")
        db.execute("INSERT INTO settings (key,value) VALUES ('smtp_password_encrypted',?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (encrypted,))
    elif values["clear_password"]:
        db.execute("INSERT INTO settings (key,value) VALUES ('smtp_password_encrypted','') "
                   "ON CONFLICT(key) DO UPDATE SET value=''")
    fields = {
        "smtp_enabled": "1" if values["enabled"] else "0",
        "smtp_host": values["host"],
        "smtp_port": values["port"],
        "smtp_user": values["user"],
        "smtp_from": values["from"],
        "smtp_security": values["security"],
        "app_base_url": values["base_url"],
    }
    for key, value in fields.items():
        db.execute("INSERT INTO settings (key,value) VALUES (?,?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
