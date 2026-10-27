import unittest
from src.evaluation import (rates_at_threshold, threshold_sweep, equal_error_rate,
                            rule_of_three_upper_bound, sample_warnings, confusion_metrics)

ROWS = [(92, True), (88, True), (75, True), (30, False), (70, False), (80, False)]


class EvaluationTests(unittest.TestCase):
    def test_far_frr_gar_definitions(self):
        r = rates_at_threshold(ROWS, 80)
        self.assertAlmostEqual(r["FAR"], 1 / 3)      # the 80 impostor is accepted
        self.assertAlmostEqual(r["FRR"], 1 / 3)      # the 75 genuine is rejected
        self.assertAlmostEqual(r["GAR"], 2 / 3)

    def test_tradeoff_is_monotone(self):
        sweep = threshold_sweep(ROWS)
        fars = [r["FAR"] for r in sweep]; frrs = [r["FRR"] for r in sweep]
        self.assertEqual(fars, sorted(fars, reverse=True))
        self.assertEqual(frrs, sorted(frrs))

    def test_eer(self):
        eer = equal_error_rate(ROWS)
        self.assertAlmostEqual(eer["EER"], 1 / 3)

    def test_requires_both_classes(self):
        with self.assertRaises(ValueError): rates_at_threshold([(90, True)], 50)

    def test_small_samples_flagged_and_zero_errors_bounded(self):
        self.assertTrue(sample_warnings(10, 10))
        self.assertAlmostEqual(rule_of_three_upper_bound(30), 0.1)
        self.assertEqual(sample_warnings(500, 500), [])

    def test_confusion_metrics(self):
        m = confusion_metrics(tp=8, fp=1, tn=9, fn=2)
        self.assertAlmostEqual(m["precision"], 8 / 9); self.assertAlmostEqual(m["recall"], 0.8)
        self.assertAlmostEqual(m["FAR"], 0.1); self.assertAlmostEqual(m["FRR"], 0.2); self.assertAlmostEqual(m["GAR"], 0.8)
        self.assertTrue(m["warnings"])


if __name__ == "__main__":
    unittest.main()
