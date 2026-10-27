import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from src.enrollment_state import enrollment_status


class EnrollmentStateTests(unittest.TestCase):
    def test_reports_modalities_and_orphans_without_reading_templates(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d); (data / "users").mkdir()
            np.save(data / "users" / "ready.npy", np.zeros(3, dtype=np.float32))
            np.save(data / "users" / "faceonly.npy", np.zeros(3, dtype=np.float32))
            np.save(data / "users" / "orphan.npy", np.zeros(3, dtype=np.float32))
            (data / "fingerprint_ids.json").write_text(json.dumps({"ready": 1, "fingeronly": 2}), encoding="utf-8")
            registered = [{"user_id": "ready", "active": 1}, {"user_id": "faceonly", "active": 1},
                          {"user_id": "fingeronly", "active": 1}, {"user_id": "off", "active": 0}]
            rows = {r["user_id"]: r for r in enrollment_status(data, registered)}
            self.assertEqual(rows["ready"]["status"], "ready")
            self.assertEqual(rows["faceonly"]["status"], "missing fingerprint")
            self.assertEqual(rows["fingeronly"]["status"], "missing face")
            self.assertIn("not registered", rows["orphan"]["status"])
            self.assertFalse(rows["off"]["active"])
            for row in rows.values():
                self.assertFalse({"embedding", "template"} & set(row))

    def test_empty_or_missing_state_does_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(enrollment_status(Path(d), []), [])
            (Path(d) / "fingerprint_ids.json").write_text("not json", encoding="utf-8")
            self.assertEqual(enrollment_status(Path(d), []), [])


if __name__ == "__main__":
    unittest.main()
