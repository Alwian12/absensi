import unittest

from app.authentication.jwt_handler import create_token, hash_password, verify_password, verify_token


class AuthTests(unittest.TestCase):
    def test_password_hash_and_verify(self) -> None:
        password = "secret123"
        hashed = hash_password(password)
        self.assertTrue(verify_password(password, hashed))
        self.assertFalse(verify_password("wrong", hashed))

    def test_create_and_verify_token(self) -> None:
        token = create_token("1", "admin")
        payload = verify_token(token)
        self.assertEqual(payload["sub"], "1")
        self.assertEqual(payload["role"], "admin")


if __name__ == "__main__":
    unittest.main()
