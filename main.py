"""Command-line entry point for enrollment, demo authentication and diagnostics."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import config
from src.audit_logger import AuditLogger
from src.authentication import AuthenticationService
from src.fingerprint_sensor import (ArduinoR307Sensor, MockFingerprintSensor, UnconfiguredFingerprintSensor,
                                    SerialPortInfo, list_serial_ports,
                                    diagnose_selected_port)
from src.evaluation import confusion_metrics
from src.fuzzy_engine import FuzzyEngine, FingerprintEvidence
from src.user_registry import UserRegistry


def resolve_selected_port(selection: str, ports: list[SerialPortInfo]) -> str | None:
    """Resolve COM9 or its numeric shorthand 9 against detected ports only."""
    value = selection.strip()
    if not value:
        return None
    if value.isdecimal():
        value = f"COM{value}"
    detected = {port.device.upper(): port.device for port in ports}
    if value.upper() not in detected:
        raise ValueError("That port was not in the detected list.")
    return detected[value.upper()]


def make_fuzzy_engine() -> FuzzyEngine:
    return FuzzyEngine.for_settings(config.AUTHENTICATION_THRESHOLD, config.get_face_threshold(),
                                    config.FUZZY_ANCHOR_FACE_SETS, config.FUZZY_ANCHOR_RAMP)


def face_verifier():
    try:
        from src.face_verification import OpenCVFaceVerifier
    except ImportError as exc:
        raise RuntimeError("OpenCV is required for webcam features. Install requirements.txt") from exc
    return OpenCVFaceVerifier(config.FACE_DETECTOR_MODEL, config.FACE_EMBEDDING_MODEL,
                              config.DATA_DIR / "users", config.get_face_threshold())


def evaluate(path: Path) -> dict:
    """Evaluate labelled records; each row has face_score, fingerprint_match, genuine."""
    records = json.loads(path.read_text(encoding="utf-8"))
    engine = make_fuzzy_engine()
    tp = fp = tn = fn = 0
    for row in records:
        predicted = engine.evaluate(float(row["face_score"]), FingerprintEvidence.MATCH if row["fingerprint_match"] else FingerprintEvidence.NO_MATCH).decision == "ACCEPT"
        actual = bool(row["genuine"])
        if predicted and actual: tp += 1
        elif predicted: fp += 1
        elif actual: fn += 1
        else: tn += 1
    return {"source_file": str(path), "records": len(records),
            "data_type": "user-labelled; not assumed real", **confusion_metrics(tp, fp, tn, fn)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fuzzy multimodal biometric educational prototype")
    hardware = parser.add_mutually_exclusive_group()
    hardware.add_argument("--mock", action="store_true", help="Use explicitly simulated fingerprint evidence")
    hardware.add_argument("--fingerprint-port", help="Explicit Arduino Uno USB COM port running the Arduino R307 bridge sketch")
    parser.add_argument("--cli", action="store_true", help="Use the text menu instead of the desktop interface")
    args = parser.parse_args()
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not args.cli and not args.mock:
        app_path = Path(__file__).resolve().with_name("app.py")
        streamlit_env = os.environ.copy()
        if args.fingerprint_port:
            streamlit_env["BIOMETRICS_FINGERPRINT_PORT"] = args.fingerprint_port
        # Bind to loopback only: the page can start the webcam/COM port and shows audit data.
        return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app_path),
                                "--server.address", "127.0.0.1"], env=streamlit_env)
    logger = AuditLogger(config.DATABASE_PATH)
    while True:
        print("\n1 Enroll face  2 Authenticate  3 Serial diagnostics  4 Evaluate labelled JSON")
        print("5 Enroll R307 fingerprint  6 Check Arduino Uno/R307  0 Exit")
        choice = input("Choice: ").strip()
        try:
            if choice == "0": return 0
            if choice == "1":
                uid = input("Pseudonymous user ID: ").strip()
                face_verifier().enroll(uid)
                print("Face embedding enrolled locally. Enrollment alone does not verify identity.")
            elif choice == "2":
                if args.mock:
                    sensor = MockFingerprintSensor(FingerprintEvidence.MATCH)
                elif args.fingerprint_port:
                    sensor = ArduinoR307Sensor(args.fingerprint_port, config.DATA_DIR / "fingerprint_ids.json")
                else:
                    sensor = UnconfiguredFingerprintSensor()
                registry = UserRegistry(config.DATABASE_PATH)
                registered_ids = registry.active_user_ids()
                face = face_verifier()
                class RegisteredFaceIdentifier:
                    def __init__(self, verifier, allowed_ids):
                        self.verifier = verifier
                        self.allowed_ids = allowed_ids
                        self.threshold = verifier.threshold
                    def identify(self):
                        return self.verifier.identify(self.allowed_ids)
                service = AuthenticationService(RegisteredFaceIdentifier(face, registered_ids),
                                                sensor, make_fuzzy_engine(), logger,
                                                is_active=registry.is_active)
                result = service.authenticate_any()
                print(f"{result.status} | user={result.identified_user_id} | face={result.face_score} | fingerprint={result.fingerprint_result} | fuzzy={result.fuzzy_score} | mock={result.mock_hardware} | reason={result.reason} | error={result.error_category}")
            elif choice == "3":
                ports = list_serial_ports()
                if not ports: print("No serial ports detected."); continue
                for p in ports: print(f"{p.device}: {p.description} [{p.hardware_id}]")
                selected = input("Enter a listed port (COM9 or 9; blank cancels): ").strip()
                try:
                    selected_port = resolve_selected_port(selected, ports)
                except ValueError as exc:
                    print(exc)
                else:
                    if selected_port:
                        print(diagnose_selected_port(selected_port))
            elif choice == "4":
                path = Path(input("Path to labelled JSON records: ").strip())
                print(json.dumps(evaluate(path), indent=2))
            elif choice in {"5", "6"}:
                if not args.fingerprint_port:
                    print("Start with --fingerprint-port COMx after uploading arduino/arduino_uno_r307/arduino_uno_r307.ino to the Uno.")
                    continue
                sensor = ArduinoR307Sensor(args.fingerprint_port, config.DATA_DIR / "fingerprint_ids.json")
                try:
                    sensor.connect()
                    if choice == "5":
                        uid = input("Pseudonymous user ID: ").strip()
                        sensor.enroll(uid)
                    else:
                        print("Arduino Uno firmware and R307 sensor responded to PING.")
                finally:
                    sensor.disconnect()
            else: print("Choose one of the listed options.")
        except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            print(f"Operation failed: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
