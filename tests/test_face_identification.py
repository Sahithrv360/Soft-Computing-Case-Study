import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.face_verification import OpenCVFaceVerifier


class FaceIdentificationTests(unittest.TestCase):
    def test_identifies_best_enrolled_embedding(self):
        with tempfile.TemporaryDirectory() as directory:
            users = Path(directory) / "users"
            users.mkdir()
            np.save(users / "alice.npy", np.array([1.0, 0.0], dtype=np.float32))
            np.save(users / "bob.npy", np.array([0.0, 1.0], dtype=np.float32))
            verifier = OpenCVFaceVerifier("unused-detector", "unused-recognizer", users, 80)
            with patch.object(verifier, "_capture_embedding", return_value=np.array([0.99, 0.01], dtype=np.float32)):
                user_id, score = verifier.identify()
            self.assertEqual(user_id, "alice")
            self.assertGreaterEqual(score, 80)

    def test_below_threshold_returns_no_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            users = Path(directory) / "users"
            users.mkdir()
            np.save(users / "alice.npy", np.array([1.0, 0.0], dtype=np.float32))
            verifier = OpenCVFaceVerifier("unused-detector", "unused-recognizer", users, 90)
            with patch.object(verifier, "_capture_embedding", return_value=np.array([-1.0, 0.0], dtype=np.float32)):
                user_id, _ = verifier.identify()
            self.assertIsNone(user_id)

    def test_identification_can_be_restricted_to_registered_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            users = Path(directory) / "users"
            users.mkdir()
            np.save(users / "alice.npy", np.array([1.0, 0.0], dtype=np.float32))
            np.save(users / "unregistered.npy", np.array([0.0, 1.0], dtype=np.float32))
            verifier = OpenCVFaceVerifier("unused-detector", "unused-recognizer", users, 80)
            captured = np.array([0.0, 1.0], dtype=np.float32)
            with patch.object(verifier, "_capture_embedding", return_value=captured):
                user_id, _ = verifier.identify(allowed_user_ids={"alice"})
            self.assertIsNone(user_id)


if __name__ == "__main__":
    unittest.main()
