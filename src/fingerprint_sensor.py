"""Fingerprint interfaces and safe, user-selected serial diagnostics."""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Protocol

from src.fuzzy_engine import FingerprintEvidence


class FingerprintSensor(Protocol):
    is_mock: bool
    def connect(self) -> None: ...
    def enroll(self, user_id: str) -> None: ...
    def verify(self, user_id: str) -> FingerprintEvidence: ...
    def identify(self) -> str | None: ...
    def disconnect(self) -> None: ...


class MockFingerprintSensor:
    """Explicit simulation; configured responses are never real sensor data."""
    is_mock = True
    def __init__(self, evidence: FingerprintEvidence = FingerprintEvidence.MATCH,
                 simulated_user_id: str = "simulated-user"):
        self.evidence = evidence
        self.simulated_user_id = simulated_user_id
        self.connected = False
    def connect(self) -> None: self.connected = True
    def enroll(self, user_id: str) -> None:
        if not self.connected: raise ConnectionError("mock sensor is not connected")
    def verify(self, user_id: str) -> FingerprintEvidence:
        if not self.connected: raise ConnectionError("mock sensor is not connected")
        return self.evidence
    def identify(self) -> str | None:
        if not self.connected: raise ConnectionError("mock sensor is not connected")
        return self.simulated_user_id if self.evidence is FingerprintEvidence.MATCH else None
    def disconnect(self) -> None: self.connected = False


class UnconfiguredFingerprintSensor:
    """Real-hardware placeholder. Configure only after identifying exact module."""
    is_mock = False
    def connect(self) -> None: raise NotImplementedError("Fingerprint sensor model/protocol is not configured")
    def enroll(self, user_id: str) -> None: raise NotImplementedError("Fingerprint sensor model/protocol is not configured")
    def verify(self, user_id: str) -> FingerprintEvidence: raise NotImplementedError("Fingerprint sensor model/protocol is not configured")
    def identify(self) -> str | None: raise NotImplementedError("Fingerprint sensor model/protocol is not configured")
    def disconnect(self) -> None: pass


class ArduinoR307Sensor:
    """R307 adapter over an Arduino USB serial firmware bridge.

    The microcontroller owns sensor communication; this host class exchanges
    newline-delimited JSON commands with the project firmware. The COM port
    must be selected explicitly and cannot be shared with Arduino Serial Monitor.
    """
    is_mock = False

    def __init__(self, port: str, mapping_path: str | Path,
                 usb_baudrate: int = 115200, response_timeout: float = 30.0,
                 progress_callback=None):
        self.port = port
        self.mapping_path = Path(mapping_path)
        self.usb_baudrate = usb_baudrate
        self.response_timeout = response_timeout
        self.progress_callback = progress_callback
        self._serial = None
        self._user_ids = self._load_mapping()

    def _load_mapping(self) -> dict[str, int]:
        if not self.mapping_path.exists():
            return {}
        try:
            raw = json.loads(self.mapping_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict): raise ValueError("fingerprint ID mapping must be a JSON object")
            mapping = {str(k): int(v) for k, v in raw.items()}
            if any(not 1 <= value <= 999 for value in mapping.values()):
                raise ValueError("fingerprint template IDs must be from 1 through 999")
            if len(set(mapping.values())) != len(mapping):
                raise ValueError("fingerprint template ID mapping contains duplicates")
            return mapping
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"Invalid fingerprint ID mapping at {self.mapping_path}") from exc

    def _save_mapping(self) -> None:
        self.mapping_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.mapping_path.with_suffix(self.mapping_path.suffix + ".tmp")
        temp.write_text(json.dumps(self._user_ids, indent=2) + "\n", encoding="utf-8")
        temp.replace(self.mapping_path)

    def _template_id(self, user_id: str, create: bool = False) -> int:
        if user_id in self._user_ids: return self._user_ids[user_id]
        if not create: raise ValueError(f"No R307 fingerprint enrollment found for user ID {user_id!r}")
        used = set(self._user_ids.values())
        for candidate in range(1, 1000):
            if candidate not in used: return candidate
        raise ValueError("No free R307 template IDs remain (maximum supported here: 999)")

    def connect(self) -> None:
        if self._serial is not None and self._serial.is_open: return
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("pyserial is required; install requirements.txt") from exc
        try:
            self._serial = serial.Serial(self.port, self.usb_baudrate, timeout=0.5, write_timeout=2)
        except (serial.SerialException, OSError, ValueError) as exc:
            self._serial = None
            raise ConnectionError(f"Could not open Arduino port {self.port}: {exc}") from exc
        # Opening an Arduino USB serial connection commonly resets its firmware.
        time.sleep(2.5)
        self._serial.reset_input_buffer()
        try:
            # The Uno firmware may probe all documented R307 UART baud rates.
            reply = self._command("PING", expected="ping", timeout=25)
            if not reply.get("ok"):
                raise ConnectionError("Arduino replied, but the R307 did not pass its sensor check")
        except Exception:
            self.disconnect()
            raise
        message = f"R307 ready via Arduino ({reply.get('capacity', 'unknown')} template slots)."
        if self.progress_callback: self.progress_callback(message)
        else: print(message)

    def _command(self, command: str, expected: str, timeout: float | None = None) -> dict:
        if self._serial is None or not self._serial.is_open:
            raise ConnectionError("Arduino serial connection is not open")
        self._serial.write((command + "\n").encode("ascii"))
        self._serial.flush()
        deadline = time.monotonic() + (timeout or self.response_timeout)
        while time.monotonic() < deadline:
            raw = self._serial.readline()
            if not raw: continue
            try: message = json.loads(raw.decode("utf-8").strip())
            except (UnicodeDecodeError, json.JSONDecodeError): continue  # ignore ESP boot text
            event = message.get("event")
            if event == "progress":
                prompts = {"checking_sensor_baud": "Checking the R307 at its documented UART baud rates...",
                           "place_first": "Place your finger on the R307.",
                           "remove_finger": "Lift your finger from the R307.",
                           "place_second": "Place the same finger again.",
                           "place_finger": "Place the enrolled finger on the R307."}
                prompt = prompts.get(message.get("step"))
                if prompt:
                    if self.progress_callback: self.progress_callback(prompt)
                    else: print(prompt)
                continue
            if event == "error":
                raise RuntimeError(f"R307 firmware error {message.get('code', 'unknown')}")
            if event == expected: return message
        raise TimeoutError(f"Timed out waiting for R307 firmware response to {command}")

    def enroll(self, user_id: str) -> None:
        template_id = self._template_id(user_id, create=True)
        self._command(f"ENROLL {template_id}", expected="enrolled", timeout=90)
        self._user_ids[user_id] = template_id
        self._save_mapping()
        message = f"R307 fingerprint template enrolled for pseudonymous user {user_id!r}."
        if self.progress_callback: self.progress_callback(message)
        else: print(message)

    def verify(self, user_id: str) -> FingerprintEvidence:
        template_id = self._template_id(user_id)
        reply = self._command(f"VERIFY {template_id}", expected="verify", timeout=self.response_timeout)
        if reply.get("result") == "match": return FingerprintEvidence.MATCH
        if reply.get("result") == "no_match": return FingerprintEvidence.NO_MATCH
        raise RuntimeError("R307 firmware returned an invalid verification result")

    def identify(self) -> str | None:
        """Return the pseudonymous user mapped to the R307's 1:N search result."""
        reply = self._command("IDENTIFY", expected="identify", timeout=self.response_timeout)
        if reply.get("result") == "no_match":
            return None
        if reply.get("result") != "match":
            raise RuntimeError("R307 firmware returned an invalid identification result")
        try:
            template_id = int(reply["template_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("R307 firmware omitted a valid template ID") from exc
        for user_id, stored_id in self._user_ids.items():
            if stored_id == template_id:
                return user_id
        # A sensor template not enrolled through this app has no trusted identity mapping.
        return None

    def disconnect(self) -> None:
        if self._serial is not None:
            try: self._serial.close()
            finally: self._serial = None


# Backward-compatible name for earlier project code/tests.
WemosR307Sensor = ArduinoR307Sensor


@dataclass(frozen=True)
class SerialPortInfo:
    device: str
    description: str
    hardware_id: str


def list_serial_ports() -> list[SerialPortInfo]:
    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise RuntimeError("pyserial is required; install requirements.txt") from exc
    return [SerialPortInfo(p.device, p.description, p.hwid) for p in list_ports.comports()]


def diagnose_selected_port(port: str, baudrate: int = 57600) -> str:
    """Open only the explicitly selected port; send no commands or bytes."""
    try:
        import serial
    except ImportError as exc:
        raise RuntimeError("pyserial is required; install requirements.txt") from exc
    try:
        with serial.Serial(port=port, baudrate=baudrate, timeout=1):
            return f"Opened {port} at {baudrate} baud. No bytes were sent."
    except (serial.SerialException, OSError, ValueError) as exc:
        return (f"Could not open {port}: {exc}. Confirm the selected device in Device Manager, "
                "close other programs using it, check the adapter/driver/cable, and verify its COM number.")
