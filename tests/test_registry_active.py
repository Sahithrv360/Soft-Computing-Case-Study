import tempfile
import unittest
from pathlib import Path
from src.user_registry import UserRegistry


class RegistryActiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.registry = UserRegistry(Path(self.tmp.name) / "r.sqlite3")

    def test_validate_profile_normalises_and_does_not_write(self):
        profile = UserRegistry.validate_profile(user_id=" a1 ", full_name=" Ada Lovelace ", email=" ADA@Example.org ")
        self.assertEqual((profile["user_id"], profile["full_name"], profile["email"]), ("a1", "Ada Lovelace", "ada@example.org"))
        self.assertEqual(self.registry.list_users(), [])

    def test_validate_profile_rejects_bad_fields(self):
        bad = [dict(user_id="", full_name="Ada Lovelace"), dict(user_id="a b", full_name="Ada Lovelace"),
               dict(user_id="x" * 33, full_name="Ada Lovelace"), dict(user_id="a1", full_name="A"),
               dict(user_id="a1", full_name="Ada Lovelace", email="nope"),
               dict(user_id="a1", full_name="Ada Lovelace", role="admin"),
               dict(user_id="a1", full_name="Ada Lovelace", department="d" * 101)]
        for kwargs in bad:
            with self.assertRaises(ValueError, msg=str(kwargs)):
                UserRegistry.validate_profile(**kwargs)

    def test_activation_controls_acceptance_eligibility(self):
        self.registry.register(user_id="a1", full_name="Ada Lovelace")
        self.registry.register(user_id="b2", full_name="Bob Babbage")
        self.assertTrue(self.registry.is_active("a1"))
        self.assertFalse(self.registry.is_active("unknown"))
        self.registry.set_active("a1", False)
        self.assertFalse(self.registry.is_active("a1"))
        self.assertEqual(self.registry.active_user_ids(), ["b2"])
        self.assertEqual(len(self.registry.list_users()), 2)   # still listed, but inactive
        self.registry.set_active("a1", True)
        self.assertEqual(self.registry.active_user_ids(), ["a1", "b2"])

    def test_set_active_unknown_user_raises(self):
        with self.assertRaises(ValueError):
            self.registry.set_active("ghost", False)


if __name__ == "__main__":
    unittest.main()
