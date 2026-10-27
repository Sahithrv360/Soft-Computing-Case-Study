import unittest
from src.fuzzy_engine import FuzzyEngine, FingerprintEvidence, face_memberships

class FuzzyTests(unittest.TestCase):
    def setUp(self): self.engine = FuzzyEngine(75)
    def test_memberships(self):
        self.assertEqual(face_memberships(0)["low"], 1)
        self.assertEqual(face_memberships(100)["high"], 1)
    def test_high_and_match_accepts(self):
        self.assertEqual(self.engine.evaluate(95, FingerprintEvidence.MATCH).decision, "ACCEPT")
    def test_high_and_no_match_denies(self):
        self.assertEqual(self.engine.evaluate(95, FingerprintEvidence.NO_MATCH).decision, "DENY")
    def test_low_and_match_denies(self):
        self.assertEqual(self.engine.evaluate(10, FingerprintEvidence.MATCH).decision, "DENY")
    def test_low_both_denies(self):
        self.assertEqual(self.engine.evaluate(10, FingerprintEvidence.NO_MATCH).decision, "DENY")
    def test_medium_and_match_denies(self):
        self.assertEqual(self.engine.evaluate(60, FingerprintEvidence.MATCH).decision, "DENY")
    def test_invalid_input(self):
        for val in (-1, 101, float("nan")):
            with self.assertRaises(ValueError): self.engine.evaluate(val, FingerprintEvidence.MATCH)
        with self.assertRaises(ValueError): self.engine.evaluate(80, True)

if __name__ == "__main__": unittest.main()
