import unittest
from src.fuzzy_engine import (FuzzyEngine, FaceSets, FingerprintEvidence as F, RULES,
                              face_memberships, fingerprint_memberships)


class FuzzyTraceTests(unittest.TestCase):
    def setUp(self):
        self.engine = FuzzyEngine(75)

    def test_trace_exposes_every_stage(self):
        result = self.engine.evaluate(90, F.MATCH)
        t = result.trace
        self.assertEqual(t.face_score, 90)
        self.assertEqual(t.fingerprint, "MATCH")
        self.assertAlmostEqual(t.face_memberships["high"], 25 / 35)
        self.assertEqual(t.fingerprint_memberships, {"no_match": 0.0, "match": 1.0})
        self.assertEqual(len(t.rules), len(RULES))
        self.assertEqual(len(t.aggregated), 101)
        self.assertAlmostEqual(t.centroid, result.score)
        self.assertEqual(t.decision, result.decision)
        self.assertEqual(t.threshold, 75)

    def test_rule_activation_values(self):
        t = self.engine.evaluate(90, F.MATCH).trace
        strengths = {r.rule_id: r.strength for r in t.rules}
        self.assertEqual(strengths["R1"], 0.0)            # fingerprint no-match rule not active
        self.assertEqual(strengths["R2"], 0.0)            # face is not Low at 90
        self.assertAlmostEqual(strengths["R4"], 25 / 35)  # min(match=1, high=.714)
        self.assertEqual(strengths["R4"], strengths["R5"])
        t = self.engine.evaluate(90, F.NO_MATCH).trace
        strengths = {r.rule_id: r.strength for r in t.rules}
        self.assertEqual(strengths["R1"], 1.0)
        self.assertEqual(strengths["R4"], 0.0)

    def test_no_match_never_activates_accepting_rules(self):
        for score in range(0, 101, 5):
            t = self.engine.evaluate(score, F.NO_MATCH).trace
            self.assertTrue(all(r.strength == 0 for r in t.rules if r.output_set in ("high", "very_high")))
            self.assertEqual(t.decision, "DENY")

    def test_pinned_reference_values(self):
        # Pinned from the engine before the trace refactor (regression guard).
        self.assertAlmostEqual(self.engine.evaluate(95, F.MATCH).score, 83.117, places=2)
        self.assertAlmostEqual(self.engine.evaluate(100, F.MATCH).score, 83.224, places=2)
        self.assertAlmostEqual(self.engine.evaluate(95, F.NO_MATCH).score, 13.0, places=2)

    def test_monotone_decision_with_match(self):
        decisions = [self.engine.evaluate(s, F.MATCH).decision for s in range(0, 101)]
        first = decisions.index("ACCEPT")
        self.assertTrue(all(d == "ACCEPT" for d in decisions[first:]))
        self.assertTrue(all(d == "DENY" for d in decisions[:first]))

    def test_accept_boundary_matches_scan(self):
        boundary = self.engine.accept_boundary()
        self.assertEqual(boundary, 83.5)
        self.assertEqual(self.engine.evaluate(boundary, F.MATCH).decision, "ACCEPT")
        self.assertEqual(self.engine.evaluate(boundary - 0.5, F.MATCH).decision, "DENY")

    def test_threshold_above_reachable_score_has_no_boundary(self):
        self.assertIsNone(FuzzyEngine(99).accept_boundary())

    def test_invalid_inputs_raise(self):
        for bad in (-0.1, 100.1, float("nan"), float("inf"), True, None, "90"):
            with self.assertRaises(ValueError):
                self.engine.evaluate(bad, F.MATCH)
        with self.assertRaises(ValueError):
            fingerprint_memberships("MATCH")
        for bad in (-1, 101, float("nan"), True):
            with self.assertRaises(ValueError):
                FuzzyEngine(bad)

    def test_anchored_sets_keep_low_scores_out_of_high(self):
        sets = FaceSets.anchored(68.0, ramp=10)
        self.assertEqual(face_memberships(68.0, sets)["high"], 0.0)
        self.assertEqual(face_memberships(60.0, sets)["high"], 0.0)
        self.assertEqual(face_memberships(78.0, sets)["high"], 1.0)
        engine = FuzzyEngine(75, sets)
        self.assertEqual(engine.evaluate(67, F.MATCH).decision, "DENY")
        self.assertEqual(engine.evaluate(90, F.MATCH).decision, "ACCEPT")
        boundary = engine.accept_boundary()
        self.assertGreater(boundary, 68.0)
        self.assertLess(boundary, 83.5)   # anchoring lowers the boundary vs the fixed sets here

    def test_anchored_requires_valid_threshold(self):
        for bad in (0, 100, -5, float("nan")):
            with self.assertRaises(ValueError):
                FaceSets.anchored(bad)

    def test_for_settings_defaults_to_fixed_sets(self):
        fixed = FuzzyEngine.for_settings(75, 68.0, anchor_face_sets=False)
        self.assertEqual(fixed.face_sets, FaceSets())
        self.assertNotEqual(FuzzyEngine.for_settings(75, 68.0, True).face_sets, FaceSets())
        self.assertEqual(FuzzyEngine.for_settings(75, None, True).face_sets, FaceSets())


if __name__ == "__main__":
    unittest.main()
