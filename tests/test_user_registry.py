import tempfile
import unittest
from pathlib import Path

from src.user_registry import UserRegistry


class UserRegistryTests(unittest.TestCase):
    def test_register_and_retrieve_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = UserRegistry(Path(folder) / "users.sqlite3")
            registry.register(user_id="student_1", full_name="Sample Student",
                              email="student@example.edu", department="Computing", role="student")
            user = registry.get("student_1")
            self.assertEqual(user["full_name"], "Sample Student")
            self.assertEqual(user["role"], "student")

    def test_rejects_duplicate_and_invalid_email(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = UserRegistry(Path(folder) / "users.sqlite3")
            registry.register(user_id="u1", full_name="Sample User")
            with self.assertRaises(ValueError):
                registry.register(user_id="u1", full_name="Second User")
            with self.assertRaises(ValueError):
                registry.register(user_id="u2", full_name="Sample User", email="not-email")


if __name__ == "__main__":
    unittest.main()
