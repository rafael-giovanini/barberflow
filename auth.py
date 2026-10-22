"""
Utilitários de senha — usa apenas biblioteca padrão (hashlib + pbkdf2).
Sem dependências externas que podem quebrar.
Formato do hash: pbkdf2$<iterations>$<salt_hex>$<hash_hex>
"""
import hashlib
import os
import secrets

ITERATIONS = 100_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), ITERATIONS
    ).hex()
    return f"pbkdf2${ITERATIONS}${salt}${pw_hash}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, pw_hash = stored.split("$")
        iterations = int(iterations)
        calc = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), iterations
        ).hex()
        return secrets.compare_digest(calc, pw_hash)
    except Exception:
        return False
