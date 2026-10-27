import tempfile
import unittest
from pathlib import Path
from calibrate_face_threshold import suggest_threshold

class FaceCalibrationTests(unittest.TestCase):
    def test_threshold_respects_requested_far(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"scores.csv"
            path.write_text("score,genuine\n92,true\n88,true\n30,false\n70,false\n", encoding="utf-8")
            result=suggest_threshold(path, 0.0)
            self.assertEqual(result["threshold"],88.0)
            self.assertEqual(result["observed_far"],0.0)

if __name__ == "__main__": unittest.main()
