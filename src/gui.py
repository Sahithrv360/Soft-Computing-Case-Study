"""Small Tkinter desktop interface for the educational biometric prototype."""
from __future__ import annotations

import queue
import csv
import json
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import config
from src.audit_logger import AuditLogger
from src.authentication import AuthenticationService
from src.face_verification import OpenCVFaceVerifier
from src.fingerprint_sensor import ArduinoR307Sensor, list_serial_ports
from src.fuzzy_engine import FuzzyEngine
from calibrate_face_threshold import suggest_threshold


class BiometricApp:
    def __init__(self, root: tk.Tk, initial_port: str | None = None):
        self.root = root
        self.root.title("Multimodal Biometric Authentication")
        self.root.geometry("760x700")
        self.root.minsize(680, 620)
        self.logger = AuditLogger(config.DATABASE_PATH)
        self.events: queue.Queue[tuple[str, str]] = queue.Queue()
        self.busy = False
        self.threshold: float | None = self._load_threshold()
        self._build(initial_port)
        self.root.after(100, self._drain_events)

    def _build(self, initial_port: str | None) -> None:
        outer = ttk.Frame(self.root, padding=22)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Multimodal Biometric Authentication",
                  font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(outer, text="Face + R307 fingerprint identification",
                  font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 16))

        ports_frame = ttk.LabelFrame(outer, text="Arduino Uno serial port", padding=10)
        ports_frame.pack(fill="x")
        self.port_var = tk.StringVar(value=initial_port or "")
        self.port_box = ttk.Combobox(ports_frame, textvariable=self.port_var, width=22)
        self.port_box.pack(side="left", padx=(0, 8))
        ttk.Button(ports_frame, text="Refresh ports", command=self._refresh_ports).pack(side="left")
        self._refresh_ports(initial_port)

        enroll_frame = ttk.LabelFrame(outer, text="Enroll a user (one time)", padding=10)
        enroll_frame.pack(fill="x", pady=(12, 0))
        ttk.Label(enroll_frame, text="Pseudonymous ID:").pack(side="left")
        self.user_var = tk.StringVar()
        ttk.Entry(enroll_frame, textvariable=self.user_var, width=24).pack(side="left", padx=8)
        self.enroll_button = ttk.Button(enroll_frame, text="Enroll face + fingerprint",
                                        command=self._enroll)
        self.enroll_button.pack(side="left", padx=(4, 0))

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=16)
        self.auth_button = ttk.Button(actions, text="Identify & authenticate",
                                      command=self._authenticate)
        self.auth_button.pack(side="left")
        self.check_button = ttk.Button(actions, text="Check R307", command=self._check_sensor)
        self.check_button.pack(side="left", padx=8)
        ttk.Button(actions, text="Recent attempts", command=self._show_attempts).pack(side="left")

        threshold_frame = ttk.LabelFrame(outer, text="Face threshold", padding=10)
        threshold_frame.pack(fill="x")
        self.threshold_var = tk.StringVar(value="" if self.threshold is None else str(self.threshold))
        ttk.Label(threshold_frame, text="Validated value (0–100):").pack(side="left")
        ttk.Entry(threshold_frame, textvariable=self.threshold_var, width=10).pack(side="left", padx=8)
        self.threshold_button = ttk.Button(threshold_frame, text="Use for this session",
                                           command=self._set_threshold)
        self.threshold_button.pack(side="left")
        ttk.Label(threshold_frame,
                  text="Authentication stays disabled until a validated threshold is set.",
                  wraplength=660).pack(anchor="w", pady=(8, 0))

        calibration = ttk.LabelFrame(outer, text="Collect face calibration comparisons", padding=10)
        calibration.pack(fill="x", pady=(10, 0))
        ttk.Label(calibration, text="For the ID above, compare this person against its enrollment:").pack(anchor="w")
        self.label_var = tk.StringVar(value="genuine")
        ttk.Combobox(calibration, textvariable=self.label_var, values=("genuine", "impostor"),
                     state="readonly", width=12).pack(side="left", pady=(6, 0))
        self.record_score_button = ttk.Button(calibration, text="Capture and record score",
                                              command=self._record_face_score)
        self.record_score_button.pack(side="left", padx=8, pady=(6, 0))
        ttk.Button(calibration, text="Suggest threshold from CSV",
                   command=self._suggest_threshold).pack(side="left", pady=(6, 0))

        status_frame = ttk.LabelFrame(outer, text="Status", padding=10)
        status_frame.pack(fill="both", expand=True, pady=(14, 0))
        self.status = tk.StringVar(value="Ready. Enroll the same pseudonymous user on both modalities.")
        ttk.Label(status_frame, textvariable=self.status, wraplength=650,
                  justify="left").pack(anchor="nw", fill="both", expand=True)
        ttk.Label(outer, text="Educational prototype. Webcam liveness detection is not implemented.",
                  foreground="#8a4b08").pack(anchor="w", pady=(10, 0))

    def _load_threshold(self) -> float | None:
        return config.get_face_threshold()

    def _refresh_ports(self, preferred: str | None = None) -> None:
        try:
            ports = list_serial_ports()
            devices = [p.device for p in ports]
            self.port_box["values"] = devices
            if preferred and preferred in devices:
                self.port_var.set(preferred)
            elif self.port_var.get() not in devices and devices:
                self.port_var.set(devices[0])
            elif not devices:
                self.port_var.set("")
        except Exception as exc:
            self.status.set(f"Could not list serial ports: {exc}")

    def _face(self) -> OpenCVFaceVerifier:
        return OpenCVFaceVerifier(config.FACE_DETECTOR_MODEL, config.FACE_EMBEDDING_MODEL,
                                  config.DATA_DIR / "users", self.threshold)

    def _sensor(self, port: str, progress=None) -> ArduinoR307Sensor:
        port = port.strip()
        if not port:
            raise ValueError("Select the Arduino Uno COM port first.")
        return ArduinoR307Sensor(port, config.DATA_DIR / "fingerprint_ids.json",
                                 progress_callback=progress)

    def _start_job(self, label: str, work) -> None:
        if self.busy:
            return
        self.busy = True
        self._set_controls(False)
        self.status.set(label)

        def run():
            try:
                message = work()
                self.events.put(("done", str(message)))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        threading.Thread(target=run, daemon=True).start()

    def _set_controls(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in (self.enroll_button, self.auth_button, self.check_button,
                       self.threshold_button, self.record_score_button):
            widget.configure(state=state)

    def _enroll(self) -> None:
        user_id = self.user_var.get().strip()
        port = self.port_var.get().strip()
        if not user_id:
            messagebox.showerror("User ID required", "Enter a pseudonymous ID for enrollment.")
            return
        if not port:
            messagebox.showerror("Arduino port required", "Select the Uno COM port first.")
            return

        def work():
            self.events.put(("progress", "Enrolling face. Use the webcam window and press Space."))
            self._face().enroll(user_id)
            sensor = self._sensor(port, self._progress)
            try:
                sensor.connect()
                sensor.enroll(user_id)
            finally:
                sensor.disconnect()
            return f"Enrollment complete for {user_id!r}. Face embedding is local; fingerprint template stays on R307."

        self._start_job("Starting enrollment…", work)

    def _authenticate(self) -> None:
        if self.threshold is None:
            messagebox.showwarning("Face threshold required",
                                   "Set a threshold chosen from labelled genuine/impostor validation data first.")
            return
        port = self.port_var.get().strip()
        if not port:
            messagebox.showerror("Arduino port required", "Select the Uno COM port first.")
            return

        def work():
            self.events.put(("progress", "Capturing face for automatic identification…"))
            sensor = self._sensor(port, self._progress)
            service = AuthenticationService(self._face(), sensor, FuzzyEngine(), self.logger)
            result = service.authenticate_any()
            if result.status == "ACCEPT":
                return (f"ACCEPT — identified {result.identified_user_id!r}\n"
                        f"Face score: {result.face_score:.2f} | fuzzy score: {result.fuzzy_score:.2f}")
            return (f"{result.status} — no two-modality identity match\n"
                    f"Face score: {result.face_score} | fingerprint: {result.fingerprint_result} | "
                    f"fuzzy score: {result.fuzzy_score} | error: {result.error_category}")

        self._start_job("Starting automatic face and fingerprint identification…", work)

    def _check_sensor(self) -> None:
        port = self.port_var.get().strip()
        if not port:
            messagebox.showerror("Arduino port required", "Select the Uno COM port first.")
            return
        def work():
            sensor = self._sensor(port, self._progress)
            try:
                sensor.connect()
                return "Arduino Uno and R307 responded to PING."
            finally:
                sensor.disconnect()
        self._start_job("Checking Arduino/R307…", work)

    def _set_threshold(self) -> None:
        try:
            value = float(self.threshold_var.get())
            if not 0 <= value <= 100:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid threshold", "Enter a number from 0 through 100.")
            return
        self.threshold = value
        path = config.DATA_DIR / "face_threshold.json"
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps({"threshold": value}, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)
        self.status.set(f"Threshold {value:g} saved locally. Confirm it was selected from validation data.")

    def _record_face_score(self) -> None:
        user_id = self.user_var.get().strip()
        label = self.label_var.get()
        if not user_id:
            messagebox.showerror("Enrollment ID required", "Enter an enrolled reference ID above.")
            return

        def work():
            score = self._face().score_against(user_id, f"{label.title()} face comparison")
            path = config.DATA_DIR / "face_validation_scores.csv"
            new_file = not path.exists()
            with path.open("a", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                if new_file:
                    writer.writerow(("score", "genuine"))
                writer.writerow((f"{score:.6f}", label))
            return f"Recorded {label} face comparison score {score:.2f} in {path}. No image was saved."

        self._start_job(f"Capturing {label} comparison…", work)

    def _suggest_threshold(self) -> None:
        path = config.DATA_DIR / "face_validation_scores.csv"
        try:
            result = suggest_threshold(path, target_far=0.01)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Cannot suggest threshold", str(exc))
            return
        self.threshold_var.set(str(result["threshold"]))
        self.status.set(f"Suggested threshold {result['threshold']} | observed FAR {result['observed_far']:.3f} "
                         f"| observed FRR {result['observed_frr']:.3f} | {result['comparisons']} labelled comparisons. "
                         "Review the dataset before applying it.")

    def _progress(self, message: str) -> None:
        self.events.put(("progress", message))

    def _show_attempts(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Recent authentication attempts")
        window.geometry("800x330")
        columns = ("timestamp", "user_id", "face", "fingerprint", "fuzzy", "decision", "mock")
        tree = ttk.Treeview(window, columns=columns, show="headings")
        for column, title, width in zip(columns,
                                       ("Timestamp UTC", "Pseudonymous ID", "Face", "Fingerprint", "Fuzzy", "Decision", "Mock"),
                                       (190, 120, 90, 110, 70, 90, 50)):
            tree.heading(column, text=title)
            tree.column(column, width=width, anchor="w")
        tree.pack(fill="both", expand=True, padx=8, pady=8)
        try:
            for row in self.logger.get_attempts(100):
                tree.insert("", "end", values=(row["timestamp"], row["user_id"], row["face_outcome"],
                                                row["fingerprint_outcome"], row["fuzzy_score"],
                                                row["decision"], bool(row["mock_hardware"])))
        except Exception as exc:
            messagebox.showerror("Audit log error", str(exc), parent=window)

    def _drain_events(self) -> None:
        try:
            while True:
                kind, message = self.events.get_nowait()
                self.status.set(message)
                if kind in {"done", "error"}:
                    self.busy = False
                    self._set_controls(True)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)


def launch_gui(initial_port: str | None = None) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    BiometricApp(root, initial_port)
    root.mainloop()
