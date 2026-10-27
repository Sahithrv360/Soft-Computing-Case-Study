import tempfile
import unittest
from pathlib import Path
from src.audit_logger import AuditLogger
from src.authentication import AuthenticationService
from src.fingerprint_sensor import MockFingerprintSensor
from src.fuzzy_engine import FuzzyEngine, FingerprintEvidence


class FaceStub:
    def __init__(self, user="u1", score=95.0, threshold=80.0, error=None):
        self.user, self.score, self.threshold, self.error = user, score, threshold, error
    def identify(self):
        if self.error: raise self.error
        return self.user, self.score


class ScriptedSensor:
    """Fingerprint stub whose connect/identify can be made to fail."""
    is_mock = False
    def __init__(self, identified="u1", connect_error=None, identify_error=None):
        self.identified, self.connect_error, self.identify_error = identified, connect_error, identify_error
        self.disconnected = False
    def connect(self):
        if self.connect_error: raise self.connect_error
    def identify(self):
        if self.identify_error: raise self.identify_error
        return self.identified
    def enroll(self, user_id): pass
    def verify(self, user_id): return FingerprintEvidence.MATCH
    def disconnect(self): self.disconnected = True


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.logger = AuditLogger(Path(self.tmp.name) / "a.sqlite3")

    def run_any(self, face, sensor, active=None, engine=None):
        service = AuthenticationService(face, sensor, engine or FuzzyEngine(), self.logger, is_active=active)
        return service.authenticate_any()

    def last_row(self):
        return self.logger.get_attempts(1)[0]

    # --- acceptance requires every gate ---
    def test_accepts_when_every_gate_passes(self):
        r = self.run_any(FaceStub(), ScriptedSensor("u1"), active=lambda u: True)
        self.assertEqual((r.status, r.reason, r.identified_user_id), ("ACCEPT", "ACCEPTED", "u1"))
        self.assertIsNotNone(r.trace)
        self.assertEqual(self.last_row()["reason"], "ACCEPTED")

    def test_inactive_or_unregistered_user_is_denied_even_if_both_match(self):
        r = self.run_any(FaceStub(), ScriptedSensor("u1"), active=lambda u: False)
        self.assertEqual((r.status, r.reason, r.identified_user_id), ("DENY", "USER_NOT_ACTIVE", None))

    def test_identity_mismatch(self):
        r = self.run_any(FaceStub("u1"), ScriptedSensor("u2"), active=lambda u: True)
        self.assertEqual((r.status, r.reason, r.identified_user_id), ("DENY", "IDENTITY_MISMATCH", None))
        self.assertEqual((r.face_user_id, r.fingerprint_user_id), ("u1", "u2"))

    def test_missing_fingerprint_identity(self):
        r = self.run_any(FaceStub(), ScriptedSensor(None), active=lambda u: True)
        self.assertEqual((r.status, r.reason), ("DENY", "FINGERPRINT_NOT_IDENTIFIED"))

    def test_missing_face_identity(self):
        r = self.run_any(FaceStub(user=None, score=40.0), ScriptedSensor("u1"), active=lambda u: True)
        self.assertEqual((r.status, r.reason), ("DENY", "FACE_NOT_IDENTIFIED"))

    def test_both_unidentified(self):
        r = self.run_any(FaceStub(user=None, score=30.0), ScriptedSensor(None))
        self.assertEqual(r.status, "DENY")
        self.assertEqual(self.last_row()["user_id"], "unidentified")

    def test_face_below_calibrated_threshold_denied(self):
        r = self.run_any(FaceStub(score=90.0, threshold=95.0), ScriptedSensor("u1"))
        self.assertEqual((r.status, r.reason), ("DENY", "FACE_BELOW_CALIBRATED_THRESHOLD"))

    def test_unset_face_threshold_never_accepts(self):
        r = self.run_any(FaceStub(threshold=None), ScriptedSensor("u1"))
        self.assertEqual(r.status, "DENY")

    def test_fuzzy_threshold_is_enforced(self):
        # Face passes its own gate (>=60) but the fuzzy layer needs ~83.5 with fixed sets.
        r = self.run_any(FaceStub(score=75.0, threshold=60.0), ScriptedSensor("u1"))
        self.assertEqual((r.status, r.reason), ("DENY", "FUZZY_BELOW_THRESHOLD"))

    def test_anchored_engine_accepts_what_fixed_engine_denied(self):
        anchored = FuzzyEngine.for_settings(75, 60.0, anchor_face_sets=True)
        r = self.run_any(FaceStub(score=75.0, threshold=60.0), ScriptedSensor("u1"), engine=anchored)
        self.assertEqual(r.status, "ACCEPT")

    # --- failures are fail-closed and still audited ---
    def test_sensor_not_connected_is_incomplete(self):
        s = ScriptedSensor(connect_error=ConnectionError("no port"))
        r = self.run_any(FaceStub(), s)
        self.assertEqual((r.status, r.reason), ("INCOMPLETE", "SENSOR_UNAVAILABLE"))
        self.assertTrue(s.disconnected)
        self.assertEqual(self.last_row()["decision"], "INCOMPLETE")

    def test_sensor_timeout_and_firmware_error_are_errors(self):
        for exc in (TimeoutError("timed out"), RuntimeError("R307 firmware error finger_capture_failed")):
            r = self.run_any(FaceStub(), ScriptedSensor(identify_error=exc))
            self.assertEqual((r.status, r.reason), ("ERROR", "SYSTEM_ERROR"))
            self.assertIsNone(r.identified_user_id)

    def test_face_failure_is_error(self):
        r = self.run_any(FaceStub(error=RuntimeError("Webcam unavailable")), ScriptedSensor("u1"))
        self.assertEqual(r.status, "ERROR")

    def test_invalid_face_scores_never_accept(self):
        for bad in (101.0, -1.0, float("nan"), None, True):
            r = self.run_any(FaceStub(score=bad), ScriptedSensor("u1"))
            self.assertNotEqual(r.status, "ACCEPT", bad)

    def test_registry_check_failure_never_accepts(self):
        def boom(user): raise RuntimeError("db locked")
        r = self.run_any(FaceStub(), ScriptedSensor("u1"), active=boom)
        self.assertEqual(r.status, "ERROR")

    def test_audit_failure_withholds_access(self):
        class BrokenAudit:
            def log_attempt(self, **kw): raise OSError("disk full")
        service = AuthenticationService(FaceStub(), ScriptedSensor("u1"), FuzzyEngine(), BrokenAudit(),
                                        is_active=lambda u: True)
        r = service.authenticate_any()
        self.assertEqual((r.status, r.reason, r.identified_user_id), ("ERROR", "AUDIT_FAILURE", None))

    def test_mock_hardware_is_flagged_in_audit(self):
        self.run_any(FaceStub(), MockFingerprintSensor(simulated_user_id="u1"))
        self.assertEqual(self.last_row()["mock_hardware"], 1)

    def test_audit_row_contains_no_biometric_fields(self):
        self.run_any(FaceStub(), ScriptedSensor("u1"))
        keys = set(self.last_row())
        self.assertFalse({"embedding", "template", "image", "face_score"} & keys)


if __name__ == "__main__":
    unittest.main()
