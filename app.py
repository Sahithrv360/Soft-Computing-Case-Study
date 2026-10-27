"""Local Streamlit interface for face and R307 multimodal authentication."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path

import streamlit as st

import config
from src.audit_logger import AuditLogger
from src.authentication import AuthenticationService
from src.face_verification import OpenCVFaceVerifier
from src.fingerprint_sensor import ArduinoR307Sensor, list_serial_ports
from src.enrollment_state import enrollment_status
from src.evaluation import equal_error_rate, sample_warnings, threshold_sweep
from src.fuzzy_engine import FuzzyEngine, FingerprintEvidence, FuzzyTrace
from src.user_registry import UserRegistry
from calibrate_face_threshold import load_scores, suggest_threshold


config.DATA_DIR.mkdir(parents=True, exist_ok=True)
logger = AuditLogger(config.DATABASE_PATH)
registry = UserRegistry(config.DATABASE_PATH)

st.set_page_config(page_title="Biometric Access System", page_icon="🔐", layout="wide")
st.markdown("""
<style>
.block-container {max-width: 1120px; padding-top: 2rem;}
.hero {padding: 1.25rem 1.5rem; border-radius: 14px; background: linear-gradient(120deg,#102a43,#176b87); color:white;}
.hero h1 {color:white; margin:0;} .hero p {color:#d9edf5; margin:.35rem 0 0;}
</style>
<div class="hero"><h1>Biometric Access System</h1>
<p>Local face identification + R307 fingerprint search + Mamdani fuzzy decision</p></div>
""", unsafe_allow_html=True)


def make_face(threshold: float | None = None) -> OpenCVFaceVerifier:
    return OpenCVFaceVerifier(config.FACE_DETECTOR_MODEL, config.FACE_EMBEDDING_MODEL,
                              config.DATA_DIR / "users",
                              config.get_face_threshold() if threshold is None else threshold)


def get_ports() -> list[str]:
    try:
        return [port.device for port in list_serial_ports()]
    except Exception as exc:
        st.error(f"Could not list serial ports: {exc}")
        return []


def make_engine() -> FuzzyEngine:
    return FuzzyEngine.for_settings(config.AUTHENTICATION_THRESHOLD, config.get_face_threshold(),
                                    config.FUZZY_ANCHOR_FACE_SETS, config.FUZZY_ANCHOR_RAMP)


def render_boundary_note(engine: FuzzyEngine) -> None:
    """Show where the fuzzy rules actually start accepting, relative to the face threshold."""
    boundary = engine.accept_boundary()
    face_threshold = config.get_face_threshold()
    if boundary is None:
        st.error("With the current fuzzy sets no face score reaches the acceptance threshold.")
        return
    st.caption(f"Fuzzy acceptance boundary: with a fingerprint match, a face score of about "
               f"{boundary:.1f} or higher is needed to reach {engine.threshold:.0f} "
               f"(computed from the rules, not a measured accuracy).")
    if face_threshold is not None and boundary > face_threshold + 1e-9:
        st.warning(f"The fuzzy layer ({boundary:.1f}) is stricter than your calibrated face threshold "
                   f"({face_threshold:.1f}), so it, not the calibration, decides the face requirement. "
                   "Review this against labelled genuine scores; `FUZZY_ANCHOR_FACE_SETS` in config.py "
                   "positions the fuzzy sets around the calibrated threshold.")


def render_trace(trace: FuzzyTrace) -> None:
    """Crisp inputs -> memberships -> rule activation -> aggregation -> centroid -> decision."""
    st.markdown("#### Fuzzy inference trace")
    st.markdown("**1. Crisp inputs**")
    st.write({"face score (0–100)": round(trace.face_score, 3), "fingerprint evidence": trace.fingerprint})
    left, right = st.columns(2)
    with left:
        st.markdown("**2. Fuzzification: face memberships**")
        st.dataframe([{"set": k, "membership": round(v, 4)} for k, v in trace.face_memberships.items()],
                     hide_index=True, use_container_width=True)
    with right:
        st.markdown("**2. Fuzzification: fingerprint memberships**")
        st.dataframe([{"set": k, "membership": round(v, 4)} for k, v in trace.fingerprint_memberships.items()],
                     hide_index=True, use_container_width=True)
    st.markdown("**3. Rule activation** (antecedent strength = minimum of its memberships)")
    st.dataframe(trace.rule_rows(), hide_index=True, use_container_width=True)
    st.markdown("**4. Aggregation** (maximum of the clipped output sets, over the 0–100 score axis)")
    st.line_chart({"aggregated membership": list(trace.aggregated)})
    st.markdown(f"**5. Defuzzification:** centroid = **{trace.centroid:.2f}** / 100")
    st.markdown(f"**6. Decision:** {trace.centroid:.2f} {'≥' if trace.centroid >= trace.threshold else '<'} "
                f"threshold {trace.threshold:.2f} → **{trace.decision}** (fuzzy layer only; identity agreement, "
                "active-account and calibrated-face gates are applied separately)")


REASON_TEXT = {
    "ACCEPTED": "Face and fingerprint identified the same active user and every gate passed.",
    "FACE_NOT_IDENTIFIED": "The face did not match any registered, active enrollment.",
    "FINGERPRINT_NOT_IDENTIFIED": "The fingerprint sensor did not identify an enrolled finger (or the sensor timed out).",
    "IDENTITY_MISMATCH": "Face and fingerprint identified different users.",
    "USER_NOT_ACTIVE": "The identified account is not an active registered account.",
    "FACE_BELOW_CALIBRATED_THRESHOLD": "The face score was below the calibrated face threshold (or none is set).",
    "FUZZY_BELOW_THRESHOLD": "The fuzzy authentication score was below its decision threshold.",
    "SENSOR_UNAVAILABLE": "The fingerprint hardware was unavailable or not connected.",
    "SYSTEM_ERROR": "An error occurred; access is denied when evidence is missing or invalid.",
    "AUDIT_FAILURE": "The attempt could not be recorded, so access was not granted.",
}


def choose_port() -> str | None:
    ports = get_ports()
    if not ports:
        st.warning("No serial ports detected. Connect the Uno and refresh the page.")
        return None
    previous = st.session_state.get("arduino_port", os.environ.get("BIOMETRICS_FINGERPRINT_PORT"))
    index = ports.index(previous) if previous in ports else 0
    selected = st.selectbox("Arduino Uno COM port", ports, index=index, key="port_select")
    st.session_state["arduino_port"] = selected
    return selected


def mapping_for_user(user_id: str) -> bool:
    path = config.DATA_DIR / "fingerprint_ids.json"
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
        return user_id in values
    except (OSError, json.JSONDecodeError, TypeError):
        return False


def status_callback(status_box):
    def update(message: str) -> None:
        status_box.write(message)
    return update


def render_register() -> None:
    st.header("Register a user")
    st.caption("A standard local registration record links a unique user ID to basic profile metadata and biometric enrollment. No password is added; the configured factors are face and fingerprint.")
    left, right = st.columns(2)
    with left:
        user_id = st.text_input("User ID *", max_chars=32, key="reg_user_id",
                                help="1–32 letters, digits, underscore, or hyphen. This is the identity key used by both modalities.")
        full_name = st.text_input("Full name *", max_chars=100, key="reg_full_name")
        email = st.text_input("Email (optional)", type="email", max_chars=254, key="reg_email")
        department = st.text_input("Department (optional)", max_chars=100, key="reg_department")
        role = st.selectbox("Registration category", ("student", "faculty", "staff"), key="reg_role")
    with right:
        st.markdown("#### Capture enrollment face")
        face_photo = st.camera_input("Capture one clear face image", key="registration_camera")
        if face_photo:
            st.caption("The image is processed in memory to create an embedding; it is not saved as a photo.")

    clean_user_id = user_id.strip()
    if clean_user_id and UserRegistry.USER_ID_PATTERN.fullmatch(clean_user_id):
        face_exists = (config.DATA_DIR / "users" / f"{clean_user_id}.npy").is_file()
        finger_exists = mapping_for_user(clean_user_id)
        if face_exists and finger_exists:
            st.info("Both modalities are already enrolled for this ID. Registration will link the profile to those enrollments.")
        elif face_exists or finger_exists:
            st.warning("One modality is already enrolled. The missing modality will be enrolled during registration.")
    elif clean_user_id:
        st.warning("User ID may contain only 1–32 letters, digits, underscores, and hyphens.")

    port = choose_port()
    if st.button("Register profile and enroll missing biometrics", type="primary", use_container_width=True):
        try:
            # Validate the whole profile BEFORE touching biometrics so a typo cannot leave an
            # enrolled fingerprint/face behind without a registry record.
            profile = UserRegistry.validate_profile(user_id=user_id, full_name=full_name, email=email,
                                                    department=department, role=role)
            user_id = profile["user_id"]
            if registry.get(user_id):
                raise ValueError(f"User ID {user_id!r} is already registered")
            face_exists = (config.DATA_DIR / "users" / f"{user_id}.npy").is_file()
            finger_exists = mapping_for_user(user_id)
            if not user_id:
                raise ValueError("Enter a user ID")
            if not face_exists and face_photo is None:
                raise ValueError("Capture the enrollment face first")
            if not finger_exists and not port:
                raise ValueError("Select the Uno COM port to enroll the fingerprint")

            new_face_path = config.DATA_DIR / "users" / f"{user_id}.npy"
            with st.status("Registering account and enrolling biometrics…", expanded=True) as progress:
                try:
                    if not face_exists:
                        progress.write("Checking face image and creating local embedding…")
                        make_face().enroll_image(user_id, face_photo.getvalue())
                    if not finger_exists:
                        sensor = ArduinoR307Sensor(port, config.DATA_DIR / "fingerprint_ids.json",
                                                   progress_callback=status_callback(progress))
                        try:
                            sensor.connect()
                            sensor.enroll(user_id)
                        finally:
                            sensor.disconnect()
                    registry.register(user_id=user_id, full_name=full_name, email=email,
                                      department=department, role=role)
                except Exception:
                    if not face_exists:
                        new_face_path.unlink(missing_ok=True)
                    raise
                progress.update(label="Registration complete", state="complete", expanded=False)
            st.success(f"Registered {full_name.strip()} ({user_id}). Face embedding is local; fingerprint template remains on the R307.")
        except Exception as exc:
            st.error(f"Registration failed: {exc}")


def _activation_callback() -> None:
    _activate()
    st.session_state["activation_key"] = ""


def _activate() -> None:
    st.session_state["access_activated"] = True
    st.session_state["activation_number"] = st.session_state.get("activation_number", 0) + 1
    st.session_state.pop("last_result", None)


def render_authenticate() -> None:
    st.header("Automatic verification")
    threshold = config.get_face_threshold()
    engine = make_engine()
    if threshold is None:
        st.warning("Face matching is disabled until a validated threshold is set in Calibration.")
    else:
        st.success(f"Calibrated face threshold loaded: {threshold:.2f}")
    render_boundary_note(engine)
    st.caption("No ID is asked here: the face is matched against registered users and the R307 searches its own "
               "templates. Both must name the same active user. Liveness detection is not implemented, so a photo "
               "or video of an enrolled person is not rejected by this prototype.")

    col_key, col_btn = st.columns([3, 1])
    with col_key:
        st.text_input("Click here, then press any printable key", key="activation_key", max_chars=1,
                      placeholder="Type one character", live="0ms", on_change=_activation_callback,
                      help="Works only while this field has focus; a web page cannot see keys pressed "
                           "elsewhere. If it does not respond, use the button.")
    with col_btn:
        st.write("")
        st.button("Start verification", type="primary", use_container_width=True, on_click=_activate,
                  help="Same effect as the key press.")

    if st.session_state.get("access_activated", False):
        _run_attempt(threshold, engine)
    last = st.session_state.get("last_result")
    if last is not None:
        _show_result(last)
    elif not st.session_state.get("access_activated", False):
        st.info("Waiting for activation (key press in the field above, or the button). Then capture a fresh "
                "face image; the R307 search follows.")


def _run_attempt(threshold, engine: FuzzyEngine) -> None:
    st.success("Activated. Capture one face image for this attempt.")
    port = choose_port()
    attempt = st.session_state.get("activation_number", 1)
    photo = st.camera_input("Capture face for verification", key=f"access_camera_{attempt}")
    if photo is None:
        return
    digest = hashlib.sha256(photo.getvalue()).hexdigest()
    processed_key = f"processed_access_{attempt}"
    if st.session_state.get(processed_key) == digest:
        return
    st.session_state[processed_key] = digest
    st.session_state["access_activated"] = False   # one activation = one attempt
    if threshold is None:
        st.error("No validated face threshold is configured. Complete calibration before authentication.")
        return
    if port is None:
        st.error("No Arduino COM port is selected.")
        return

    class CapturedFaceIdentifier:
        def __init__(self, face_threshold: float, captured: bytes, allowed_ids: list[str]):
            self.threshold = face_threshold
            self.captured = captured
            self.allowed_ids = allowed_ids
        def identify(self):
            return make_face(self.threshold).identify_image(self.captured, self.allowed_ids)

    with st.status("Verifying face and fingerprint…", expanded=True) as progress:
        progress.write("Evaluating the captured face against local enrollments…")
        sensor = ArduinoR307Sensor(port, config.DATA_DIR / "fingerprint_ids.json",
                                   progress_callback=status_callback(progress))
        result = AuthenticationService(CapturedFaceIdentifier(threshold, photo.getvalue(), registry.active_user_ids()),
                                       sensor, engine, logger, is_active=registry.is_active).authenticate_any()
        progress.update(label=f"Authentication {result.status}",
                        state="complete" if result.status == "ACCEPT" else "error", expanded=False)
    st.session_state["last_result"] = result


def _show_result(result) -> None:
    st.subheader(f"Decision: {result.status}")
    if result.status == "ACCEPT" and result.identified_user_id:
        user = registry.get(result.identified_user_id)
        st.success(f"Welcome, {user['full_name'] if user else result.identified_user_id}. "
                   "Both modalities identified the same active registered user.")
    else:
        st.error("Access denied or incomplete.")
    if result.reason:
        st.write(f"**Reason:** `{result.reason}`: {REASON_TEXT.get(result.reason, '')}")
    if result.error_message:
        st.caption(f"Details: {result.error_message}")
    st.write({"face score (crisp)": result.face_score,
              "face identified": result.face_user_id,
              "fingerprint identified": result.fingerprint_user_id,
              "fuzzy score (defuzzified)": result.fuzzy_score,
              "mock hardware": result.mock_hardware})
    if result.trace is not None:
        render_trace(result.trace)


def render_calibration() -> None:
    st.header("Face threshold calibration")
    st.write("Collect labelled face-to-enrollment comparisons under representative lighting and capture conditions. Use genuine samples from the enrolled person and impostor samples from other consenting participants. The app stores only score and label in the CSV.")
    registry_ids = [row["user_id"] for row in registry.list_users()]
    embedded_ids = [p.stem for p in (config.DATA_DIR / "users").glob("*.npy")] if (config.DATA_DIR / "users").exists() else []
    ids = sorted(set(registry_ids + embedded_ids))
    if not ids:
        st.info("Enroll a face first.")
        return
    reference_id = st.selectbox("Reference enrollment ID", ids)
    label = st.selectbox("Label the person in this capture", ("genuine", "impostor"))
    photo = st.camera_input("Capture one face comparison", key="calibration_camera")
    if st.button("Record labelled comparison", disabled=photo is None):
        try:
            score = make_face(threshold=0.0).score_against_image(reference_id, photo.getvalue())
            path = config.DATA_DIR / "face_validation_scores.csv"
            first = not path.exists()
            with path.open("a", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                if first:
                    writer.writerow(("score", "genuine"))
                writer.writerow((f"{score:.6f}", label))
            st.success(f"Recorded {label} score {score:.2f}. No face image was saved.")
        except Exception as exc:
            st.error(f"Could not record comparison: {exc}")

    score_path = config.DATA_DIR / "face_validation_scores.csv"
    if score_path.exists():
        with score_path.open(encoding="utf-8") as stream:
            record_count = max(0, sum(1 for _ in stream) - 1)
        st.caption(f"Calibration data: {score_path} ({record_count} labelled records)")
        try:
            scored = load_scores(score_path)
            genuine_n = sum(g for _, g in scored)
            impostor_n = len(scored) - genuine_n
            for note in sample_warnings(genuine_n, impostor_n):
                st.warning(note)
            if genuine_n and impostor_n:
                sweep = threshold_sweep(scored)
                eer = equal_error_rate(scored)
                st.markdown(f"**FAR/FRR trade-off** (raising the threshold lowers FAR and raises FRR). "
                            f"Approximate EER on this data: {eer['EER']:.1%} near threshold {eer['threshold']:.1f}.")
                st.line_chart({"FAR": [r["FAR"] for r in sweep], "FRR": [r["FRR"] for r in sweep]},
                              x_label="threshold index (low → high)", y_label="rate")
        except (ValueError, OSError) as exc:
            st.error(f"Calibration CSV problem: {exc}")
        target_far = st.number_input("Maximum target FAR for threshold suggestion", min_value=0.0,
                                     max_value=1.0, value=0.01, step=0.005, format="%.3f")
        if st.button("Suggest threshold"):
            try:
                st.session_state["face_threshold_suggestion"] = suggest_threshold(score_path, target_far)
            except Exception as exc:
                st.error(f"Cannot suggest a threshold: {exc}")
        suggestion = st.session_state.get("face_threshold_suggestion")
        if suggestion:
            st.json(suggestion)
            st.warning("This is a dataset-specific suggestion, not a security guarantee. Review sample size and representativeness before applying.")
            if st.button("Apply reviewed threshold locally"):
                threshold_path = config.DATA_DIR / "face_threshold.json"
                temp = threshold_path.with_suffix(".json.tmp")
                temp.write_text(json.dumps({"threshold": suggestion["threshold"]}, indent=2) + "\n", encoding="utf-8")
                temp.replace(threshold_path)
                st.success(f"Saved threshold {suggestion['threshold']} locally.")


def render_fuzzy_demo() -> None:
    st.header("Fuzzy inference engine")
    st.caption("Crisp face score and binary fingerprint evidence are fuzzified, evaluated by conservative Mamdani "
               "rules, aggregated, then centroid-defuzzified to a 0–100 score. This page is a what-if tool: it uses "
               "typed-in values, not a real capture.")
    engine = make_engine()
    render_boundary_note(engine)
    face_score = st.slider("Crisp face score", min_value=0.0, max_value=100.0, value=90.0, step=0.5)
    fingerprint = st.selectbox("Crisp fingerprint result", ("MATCH", "NO_MATCH"))
    evidence = FingerprintEvidence.MATCH if fingerprint == "MATCH" else FingerprintEvidence.NO_MATCH
    result = engine.evaluate(face_score, evidence)
    left, right = st.columns(2)
    left.metric("Defuzzified authentication score", f"{result.score:.2f}/100")
    right.metric("Fuzzy-layer decision", result.decision)
    render_trace(result.trace)
    st.caption("Rule list and set shapes are defined in `src/fuzzy_engine.py`. Thresholds are provisional until "
               "validated on labelled data.")


def render_audit() -> None:
    st.header("Registration and audit records")
    users = registry.list_users()
    st.subheader("Enrollment status")
    st.caption("Shows which modalities exist locally per ID (no biometric content is read or shown). "
               "Check this before re-enrolling anyone: Register reuses an existing face embedding or fingerprint "
               "mapping for the same ID.")
    st.dataframe(enrollment_status(config.DATA_DIR, users), hide_index=True, use_container_width=True)
    st.subheader("Registered accounts")
    st.dataframe(users, hide_index=True, use_container_width=True)
    if users:
        with st.expander("Deactivate or reactivate an account"):
            target = st.selectbox("Account", [row["user_id"] for row in users], key="active_target")
            current = next(row for row in users if row["user_id"] == target)
            makes_active = not bool(current["active"])
            label = "Reactivate" if makes_active else "Deactivate"
            if st.button(f"{label} {target}"):
                registry.set_active(target, makes_active)
                st.success(f"{target} is now {'active' if makes_active else 'inactive'}. "
                           "Inactive accounts are denied even if both biometrics match.")
                st.rerun()
    st.subheader("Recent authentication attempts")
    st.dataframe(logger.get_attempts(100), hide_index=True, use_container_width=True)


def render_hardware() -> None:
    st.header("Arduino Uno / R307 hardware")
    st.caption("Run locally on the laptop attached to the Uno. A remote Streamlit server cannot access the laptop's COM port.")
    port = choose_port()
    if st.button("Check R307", type="primary", disabled=port is None):
        with st.status("Checking Arduino/R307…", expanded=True) as status:
            sensor = ArduinoR307Sensor(port, config.DATA_DIR / "fingerprint_ids.json",
                                       progress_callback=status_callback(status))
            try:
                sensor.connect()
                status.update(label="R307 ready", state="complete", expanded=False)
            except Exception as exc:
                status.update(label="R307 check failed", state="error", expanded=True)
                st.error(str(exc))
            finally:
                sensor.disconnect()


def main() -> None:
    with st.sidebar:
        st.markdown("### Navigation")
        page = st.radio("", ("Authenticate", "Register", "Calibration", "Fuzzy engine", "Audit", "Hardware"),
                        label_visibility="collapsed")
        st.caption("Local educational prototype · fuzzy threshold is provisional")
    if page == "Authenticate":
        render_authenticate()
    elif page == "Register":
        render_register()
    elif page == "Calibration":
        render_calibration()
    elif page == "Fuzzy engine":
        render_fuzzy_demo()
    elif page == "Audit":
        render_audit()
    else:
        render_hardware()


if __name__ == "__main__":
    main()
