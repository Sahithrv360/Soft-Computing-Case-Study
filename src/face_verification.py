"""Webcam verification with OpenCV YuNet detection and SFace embeddings.

Requires the official OpenCV Zoo YuNet and SFace ONNX files in data/models.
Embedding similarity is cosine similarity; the threshold is deliberately
unconfigured until calibrated on representative genuine/impostor comparisons.
"""
from __future__ import annotations
import json
from pathlib import Path
from collections.abc import Iterable
import cv2
import numpy as np


class FaceVerificationError(RuntimeError): pass


class OpenCVFaceVerifier:
    def __init__(self, detector_path: str | Path, recognizer_path: str | Path,
                 users_dir: str | Path, threshold: float | None = None, camera_index: int = 0):
        self.detector_path, self.recognizer_path = Path(detector_path), Path(recognizer_path)
        self.users_dir, self.threshold, self.camera_index = Path(users_dir), threshold, camera_index
    def _models(self):
        if not self.detector_path.is_file() or not self.recognizer_path.is_file():
            raise FaceVerificationError("YuNet/SFace ONNX model files are missing; see README setup steps")
        detector = cv2.FaceDetectorYN.create(str(self.detector_path), "", (320, 320), 0.8, 0.3, 5000)
        recognizer = cv2.FaceRecognizerSF.create(str(self.recognizer_path), "")
        return detector, recognizer
    def _capture_embedding(self, prompt: str) -> np.ndarray:
        detector, recognizer = self._models()
        camera = cv2.VideoCapture(self.camera_index)
        try:
            if not camera.isOpened(): raise FaceVerificationError("Webcam unavailable")
            print(prompt + " (press Space to capture, Esc to cancel)")
            while True:
                ok, frame = camera.read()
                if not ok: raise FaceVerificationError("Could not read webcam frame")
                detector.setInputSize((frame.shape[1], frame.shape[0]))
                _, faces = detector.detect(frame)
                cv2.putText(frame, f"Faces: {0 if faces is None else len(faces)} | Space capture | Esc cancel",
                            (10, 25), cv2.FONT_HERSHEY_SIMPLEX, .55, (0,255,0), 1)
                cv2.imshow("Biometric face capture", frame)
                key = cv2.waitKey(1) & 0xff
                if key == 27: raise FaceVerificationError("Capture cancelled")
                if key == 32:
                    if faces is None or len(faces) == 0: raise FaceVerificationError("No face detected; improve lighting and retry")
                    if len(faces) != 1: raise FaceVerificationError("Multiple faces detected; ensure only one person is visible")
                    aligned = recognizer.alignCrop(frame, faces[0])
                    return recognizer.feature(aligned).reshape(-1).astype(np.float32)
        finally:
            camera.release()
            cv2.destroyAllWindows()

    def _embedding_from_bytes(self, image_bytes: bytes) -> np.ndarray:
        """Decode a browser camera capture and require exactly one face."""
        detector, recognizer = self._models()
        frame = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise FaceVerificationError("Could not decode the captured image")
        detector.setInputSize((frame.shape[1], frame.shape[0]))
        _, faces = detector.detect(frame)
        if faces is None or len(faces) == 0:
            raise FaceVerificationError("No face detected; improve lighting and capture again")
        if len(faces) != 1:
            raise FaceVerificationError("Multiple faces detected; ensure only one person is visible")
        aligned = recognizer.alignCrop(frame, faces[0])
        return recognizer.feature(aligned).reshape(-1).astype(np.float32)

    def enroll(self, user_id: str) -> None:
        embedding = self._capture_embedding("Enrollment")
        self.save_embedding(user_id, embedding)

    def enroll_image(self, user_id: str, image_bytes: bytes) -> None:
        self.save_embedding(user_id, self._embedding_from_bytes(image_bytes))

    def save_embedding(self, user_id: str, embedding: np.ndarray) -> None:
        self.users_dir.mkdir(parents=True, exist_ok=True)
        safe_id = self._safe_id(user_id)
        np.save(self.users_dir / f"{safe_id}.npy", embedding)
    def verify(self, user_id: str) -> float:
        if self.threshold is None: raise FaceVerificationError("Face threshold is uncalibrated; set it after validation")
        return self.score_against(user_id)

    def score_against(self, user_id: str, prompt: str = "Face comparison") -> float:
        """Capture one face and score it against an enrolled ID without thresholding."""
        reference = self.users_dir / f"{self._safe_id(user_id)}.npy"
        if not reference.is_file(): raise FaceVerificationError("No enrollment exists for this user ID")
        enrolled = np.load(reference, allow_pickle=False).astype(np.float32).reshape(-1)
        live = self._capture_embedding(prompt)
        return self._score(enrolled, live)

    def score_against_image(self, user_id: str, image_bytes: bytes) -> float:
        reference = self.users_dir / f"{self._safe_id(user_id)}.npy"
        if not reference.is_file(): raise FaceVerificationError("No enrollment exists for this user ID")
        enrolled = np.load(reference, allow_pickle=False).astype(np.float32).reshape(-1)
        return self._score(enrolled, self._embedding_from_bytes(image_bytes))

    def identify(self, allowed_user_ids: Iterable[str] | None = None) -> tuple[str | None, float]:
        """Find the best enrolled face match; return no identity below threshold."""
        if self.threshold is None:
            raise FaceVerificationError("Face threshold is uncalibrated; set it after validation")
        enrolled_files = sorted(self.users_dir.glob("*.npy"))
        if allowed_user_ids is not None:
            allowed = set(allowed_user_ids)
            enrolled_files = [path for path in enrolled_files if path.stem in allowed]
        if not enrolled_files:
            raise FaceVerificationError("No registered face enrollments found")
        live = self._capture_embedding("Automatic face identification")
        return self._identify_embedding(live, enrolled_files)

    def identify_image(self, image_bytes: bytes,
                       allowed_user_ids: Iterable[str] | None = None) -> tuple[str | None, float]:
        """Identify a captured browser image against local enrolled embeddings."""
        if self.threshold is None:
            raise FaceVerificationError("Face threshold is uncalibrated; set it after validation")
        enrolled_files = sorted(self.users_dir.glob("*.npy"))
        if allowed_user_ids is not None:
            allowed = set(allowed_user_ids)
            enrolled_files = [path for path in enrolled_files if path.stem in allowed]
        if not enrolled_files:
            raise FaceVerificationError("No registered face enrollments found")
        return self._identify_embedding(self._embedding_from_bytes(image_bytes), enrolled_files)

    def _identify_embedding(self, live: np.ndarray, enrolled_files: list[Path]) -> tuple[str | None, float]:
        best_user: str | None = None
        best_score = -1.0
        for path in enrolled_files:
            try:
                enrolled = np.load(path, allow_pickle=False).astype(np.float32).reshape(-1)
            except (OSError, ValueError) as exc:
                raise FaceVerificationError(f"Could not read face enrollment {path.name}") from exc
            score = self._score(enrolled, live)
            if score > best_score:
                best_user, best_score = path.stem, score
        if best_score < self.threshold:
            return None, best_score
        return best_user, best_score

    @staticmethod
    def _score(enrolled: np.ndarray, live: np.ndarray) -> float:
        similarity = float(np.dot(enrolled, live) / (np.linalg.norm(enrolled)*np.linalg.norm(live)))
        if not np.isfinite(similarity): raise FaceVerificationError("Invalid embedding comparison")
        # Map cosine similarity [-1,1] to display score [0,100]; decision threshold
        # is interpreted on this same mapped scale and must be calibrated.
        return (similarity + 1.0) * 50.0
    @staticmethod
    def _safe_id(user_id: str) -> str:
        if not user_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in user_id):
            raise ValueError("User ID may contain only letters, digits, underscore, and hyphen")
        return user_id
