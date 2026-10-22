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


if __name__ == "__main__":
    unittest.main()
