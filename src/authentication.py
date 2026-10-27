"""Fail-closed orchestration for face, fingerprint, fuzzy decision and audit."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Protocol
from src.audit_logger import AuditLogger
from src.fingerprint_sensor import FingerprintSensor
from src.fuzzy_engine import FuzzyEngine, FingerprintEvidence, FuzzyTrace


class FaceVerifier(Protocol):
    def verify(self, user_id: str) -> float: ...
    def identify(self) -> tuple[str | None, float]: ...


@dataclass(frozen=True)
class AuthenticationResult:
    status: str
    face_score: float | None
    fingerprint_result: FingerprintEvidence | None
    fuzzy_score: float | None
    mock_hardware: bool
    error_category: str | None = None
    identified_user_id: str | None = None
    error_message: str | None = None
    reason: str | None = None            # machine-readable outcome reason (see REASONS)
    trace: FuzzyTrace | None = None      # fuzzy inference trace, when inference ran
    face_user_id: str | None = None
    fingerprint_user_id: str | None = None


REASONS = ("ACCEPTED", "FACE_NOT_IDENTIFIED", "FINGERPRINT_NOT_IDENTIFIED", "IDENTITY_MISMATCH",
           "USER_NOT_ACTIVE", "FACE_BELOW_CALIBRATED_THRESHOLD", "FUZZY_BELOW_THRESHOLD",
           "SENSOR_UNAVAILABLE", "SYSTEM_ERROR", "AUDIT_FAILURE")


class AuthenticationService:
    def __init__(self, face: FaceVerifier, fingerprint: FingerprintSensor,
                 fuzzy: FuzzyEngine, audit: AuditLogger,
                 is_active: Callable[[str], bool] | None = None):
        """``is_active`` (e.g. ``UserRegistry.is_active``) makes acceptance require an
        active registered account; unknown or deactivated IDs are denied. If omitted,
        no registry check is performed (unit-test use only)."""
        self.face, self.fingerprint, self.fuzzy, self.audit = face, fingerprint, fuzzy, audit
        self.is_active = is_active
    def authenticate(self, user_id: str) -> AuthenticationResult:
        face_score = None
        fingerprint = None
        fuzzy_score = None
        error = None
        error_message = None
        try:
            face_score = self.face.verify(user_id)
            if not 0 <= face_score <= 100: raise ValueError("face score outside 0..100")
            self.fingerprint.connect()
            fingerprint = self.fingerprint.verify(user_id)
            if not isinstance(fingerprint, FingerprintEvidence): raise ValueError("invalid fingerprint evidence")
            result = self.fuzzy.evaluate(face_score, fingerprint)
            fuzzy_score, status = result.score, result.decision
            # The calibrated face verifier is an independent gate: fuzzy
            # aggregation must not turn a below-threshold identity comparison
            # into acceptance. Preserve the fuzzy score for audit/analysis.
            face_threshold = getattr(self.face, "threshold", None)
            if status == "ACCEPT" and face_threshold is not None and face_score < face_threshold:
                status = "DENY"
        except Exception as exc:
            status = "INCOMPLETE" if isinstance(exc, (NotImplementedError, ConnectionError)) else "ERROR"
            error = type(exc).__name__
            error_message = str(exc)
        finally:
            try: self.fingerprint.disconnect()
            except Exception: pass
        try:
            face_threshold = getattr(self.face, "threshold", None)
            face_outcome = (None if face_score is None else
                            ("MATCH" if face_threshold is not None and face_score >= face_threshold
                             else "NO_MATCH" if face_threshold is not None else "SCORED"))
            self.audit.log_attempt(user_id=user_id, face_outcome=face_outcome,
                fingerprint_outcome=(fingerprint.name if fingerprint else None), fuzzy_score=fuzzy_score,
                decision=status, error_category=error, mock_hardware=self.fingerprint.is_mock)
        except Exception:
            # An audit failure cannot upgrade an outcome; return explicit error.
            return AuthenticationResult("ERROR", face_score, fingerprint, fuzzy_score,
                                        self.fingerprint.is_mock, "AuditError")
        return AuthenticationResult(status, face_score, fingerprint, fuzzy_score,
                                    self.fingerprint.is_mock, error, error_message=error_message)

    def authenticate_any(self) -> AuthenticationResult:
        """Identify without a typed user ID; accept only when both IDs agree, the
        account is active, and the fuzzy decision (and calibrated face gate) pass."""
        face_user_id = None
        fingerprint_user_id = None
        face_score = None
        fuzzy_score = None
        fingerprint_evidence = None
        trace = None
        error = None
        error_message = None
        status = "ERROR"
        reason = "SYSTEM_ERROR"
        try:
            face_user_id, face_score = self.face.identify()
            if (face_score is None or isinstance(face_score, bool)
                    or not isinstance(face_score, (int, float)) or not 0 <= face_score <= 100):
                raise ValueError("face identification score outside 0..100")
            self.fingerprint.connect()
            fingerprint_user_id = self.fingerprint.identify()
            same_identity = (face_user_id is not None and fingerprint_user_id is not None
                             and face_user_id == fingerprint_user_id)
            fingerprint_evidence = (FingerprintEvidence.MATCH if same_identity
                                    else FingerprintEvidence.NO_MATCH)
            fuzzy = self.fuzzy.evaluate(face_score, fingerprint_evidence)
            fuzzy_score, trace = fuzzy.score, fuzzy.trace
            threshold = getattr(self.face, "threshold", None)
            # Gates are evaluated in a fixed order; the first failing gate names the reason.
            if face_user_id is None:
                status, reason = "DENY", "FACE_NOT_IDENTIFIED"
            elif fingerprint_user_id is None:
                status, reason = "DENY", "FINGERPRINT_NOT_IDENTIFIED"
            elif not same_identity:
                status, reason = "DENY", "IDENTITY_MISMATCH"
            elif self.is_active is not None and not self.is_active(face_user_id):
                status, reason = "DENY", "USER_NOT_ACTIVE"
            elif threshold is None or face_score < threshold:
                status, reason = "DENY", "FACE_BELOW_CALIBRATED_THRESHOLD"
            elif fuzzy.decision != "ACCEPT":
                status, reason = "DENY", "FUZZY_BELOW_THRESHOLD"
            else:
                status, reason = "ACCEPT", "ACCEPTED"
        except Exception as exc:
            if isinstance(exc, (NotImplementedError, ConnectionError)):
                status, reason = "INCOMPLETE", "SENSOR_UNAVAILABLE"
            else:
                status, reason = "ERROR", "SYSTEM_ERROR"
            error = type(exc).__name__
            error_message = str(exc)
        finally:
            try: self.fingerprint.disconnect()
            except Exception: pass

        matched_id = face_user_id if (face_user_id is not None and face_user_id == fingerprint_user_id) else None
        log_user_id = face_user_id or fingerprint_user_id or "unidentified"
        try:
            self.audit.log_attempt(
                user_id=log_user_id,
                face_outcome=(f"MATCH:{face_user_id}" if face_user_id else "NO_MATCH"),
                fingerprint_outcome=(f"MATCH:{fingerprint_user_id}" if fingerprint_user_id else "NO_MATCH"),
                fuzzy_score=fuzzy_score, decision=status, error_category=error,
                mock_hardware=self.fingerprint.is_mock, reason=reason)
        except Exception:
            # An audit failure cannot upgrade an outcome; if access cannot be recorded it is not granted.
            return AuthenticationResult("ERROR", face_score, fingerprint_evidence, fuzzy_score,
                                        self.fingerprint.is_mock, "AuditError", None,
                                        "Audit record could not be written; access not granted",
                                        "AUDIT_FAILURE", trace, face_user_id, fingerprint_user_id)
        return AuthenticationResult(status, face_score, fingerprint_evidence, fuzzy_score,
                                    self.fingerprint.is_mock, error,
                                    matched_id if status == "ACCEPT" else None, error_message,
                                    reason, trace, face_user_id, fingerprint_user_id)
