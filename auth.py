"""
Utilitários de senha — usa apenas biblioteca padrão (hashlib + pbkdf2).
Formato do hash: pbkdf2$<iterations>$<salt_hex>$<hash_hex>
"""
import hashlib
import secrets

ITERATIONS = 600_000
# Limite superior defensivo: o custo de verificação vem de um valor armazenado
# no banco. Um valor adulterado não deve conseguir travar o processo de login.
MAX_VERIFY_ITERATIONS = 2_000_000
HASH_BYTES = hashlib.sha256().digest_size


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), ITERATIONS
    ).hex()
    return f"pbkdf2${ITERATIONS}${salt}${pw_hash}"


def verify_password(password: str, stored: str) -> bool:
    """Valida hashes PBKDF2 conhecidos sem aceitar algoritmos ou custos arbitrários."""
    try:
        algo, iterations_text, salt, pw_hash = stored.split("$")
        if algo != "pbkdf2":
            return False
        iterations = int(iterations_text)
        if not 1 <= iterations <= MAX_VERIFY_ITERATIONS:
            return False
        if not salt or len(pw_hash) != HASH_BYTES * 2:
            return False
        # O formato persistido usa texto hexadecimal como salt; preserva os hashes
        # legados existentes, inclusive salts hexadecimais armazenados como texto.
        int(salt, 16)
        int(pw_hash, 16)
        calc = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("ascii"), iterations
        ).hex()
        return secrets.compare_digest(calc, pw_hash.lower())
    except (AttributeError, TypeError, ValueError, UnicodeError, OverflowError):
        return False
