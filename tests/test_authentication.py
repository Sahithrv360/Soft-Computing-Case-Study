import tempfile
import unittest
from pathlib import Path
from src.audit_logger import AuditLogger
from src.authentication import AuthenticationService
from src.fingerprint_sensor import MockFingerprintSensor, UnconfiguredFingerprintSensor
from src.fuzzy_engine import FuzzyEngine, FingerprintEvidence

class FaceStub:
    def __init__(self, score, threshold=None, user_id="u1"):
        self.score=score; self.threshold=threshold; self.user_id=user_id
    def verify(self, user_id): return self.score
    def identify(self): return self.user_id, self.score

class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.logger=AuditLogger(Path(self.temp.name)/"audit.sqlite3")
    def service(self, face, sensor): return AuthenticationService(face,sensor,FuzzyEngine(),self.logger)
    def test_mock_is_marked_and_acceptance_logged(self):
        sensor=MockFingerprintSensor()
        result=self.service(FaceStub(95),sensor).authenticate("u1")
        self.assertEqual(result.status,"ACCEPT"); self.assertTrue(result.mock_hardware)
        self.assertEqual(self.logger.get_attempts()[0]["mock_hardware"],1)
    def test_nonmatch_denies(self):
        result=self.service(FaceStub(95),MockFingerprintSensor(FingerprintEvidence.NO_MATCH)).authenticate("u1")
        self.assertEqual(result.status,"DENY")
    def test_sensor_unconfigured_incomplete(self):
        result=self.service(FaceStub(95),UnconfiguredFingerprintSensor()).authenticate("u1")
        self.assertEqual(result.status,"INCOMPLETE")
        self.assertNotEqual(result.status,"ACCEPT")
    def test_bad_face_score_never_accepts(self):
        self.assertEqual(self.service(FaceStub(101),MockFingerprintSensor()).authenticate("u1").status,"ERROR")
    def test_face_calibration_gate_blocks_fuzzy_accept(self):
        result=self.service(FaceStub(99,100),MockFingerprintSensor()).authenticate("u1")
        self.assertEqual(result.status,"DENY")
    def test_automatic_identification_accepts_only_same_identity(self):
        service=self.service(FaceStub(95,80,"u1"),MockFingerprintSensor(simulated_user_id="u1"))
        result=service.authenticate_any()
        self.assertEqual(result.status,"ACCEPT")
        self.assertEqual(result.identified_user_id,"u1")
    def test_automatic_identification_denies_identity_mismatch(self):
        service=self.service(FaceStub(95,80,"u1"),MockFingerprintSensor(simulated_user_id="u2"))
        result=service.authenticate_any()
        self.assertEqual(result.status,"DENY")
        self.assertIsNone(result.identified_user_id)

if __name__ == "__main__": unittest.main()
