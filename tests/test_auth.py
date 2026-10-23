import unittest

from auth import hash_password, verify_password


class PasswordHashTests(unittest.TestCase):
    def test_password_hash_is_not_plaintext_and_verifies(self):
        password = "Senha-de-teste-2026!"
        stored = hash_password(password)
        self.assertNotEqual(stored, password)
        self.assertTrue(verify_password(password, stored))
        self.assertFalse(verify_password("senha-errada", stored))

    def test_hash_uses_independent_salts(self):
        password = "Senha-de-teste-2026!"
        self.assertNotEqual(hash_password(password), hash_password(password))

    def test_rejects_unknown_hash_algorithm(self):
        valid = hash_password("Senha-de-teste-2026!")
        self.assertFalse(verify_password("Senha-de-teste-2026!", valid.replace("pbkdf2$", "unknown$", 1)))

    def test_rejects_excessive_iteration_count_without_hashing(self):
        malformed = "pbkdf2$999999999$73616c74$" + ("0" * 64)
        self.assertFalse(verify_password("senha", malformed))

    def test_rejects_malformed_hash_fields(self):
        self.assertFalse(verify_password("senha", "pbkdf2$600000$not-hex$" + ("0" * 64)))
        self.assertFalse(verify_password("senha", "pbkdf2$600000$73616c74$xyz"))
        self.assertFalse(verify_password("senha", "pbkdf2$0$73616c74$" + ("0" * 64)))


if __name__ == "__main__":
    unittest.main()
