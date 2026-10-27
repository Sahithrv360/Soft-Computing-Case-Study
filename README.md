# Fuzzy Logic Based Multimodal Biometric Authentication

Educational prototype: laptop webcam face identification + R307 fingerprint search (Arduino Uno) fused by a
Mamdani fuzzy decision. **Not production security software.** It has not been validated on labelled data, has no
liveness detection, and no accuracy claim is made for it.

## Setup and launch (Windows PowerShell, Python 3.12)

Check that an existing `.venv` still points at a real interpreter before reusing it:

```powershell
if (Test-Path .\.venv\Scripts\python.exe) { .\.venv\Scripts\python.exe --version } else { "no .venv yet" }
```

If that prints an error or a version other than 3.12.x, recreate it:

```powershell
Remove-Item -Recurse -Force .venv -ErrorAction SilentlyContinue
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v      # hardware-independent tests
python main.py --fingerprint-port COM11      # replace COM11 with the Uno's port; opens the app at http://127.0.0.1:8501
```

`python main.py` starts Streamlit bound to **127.0.0.1 only** (also set in `.streamlit/config.toml`), because the page
drives this laptop's webcam and Uno COM port and shows audit data. A remote or LAN-reachable Streamlit server cannot
reach the local hardware and should not be exposed. `streamlit run app.py` works too. `python main.py --cli` gives a text
menu; `python main.py --mock` runs the CLI with clearly marked *simulated* fingerprint evidence (not a scan).

Model files (not in version control): put `face_detection_yunet_2023mar.onnx` and `face_recognition_sface_2021dec.onnx`
from the OpenCV Zoo into `data/models/` (use each file page's "Download raw file").

## How authentication works

1. **Activate.** On the Authenticate page click **Start verification**, or click the text field and press any printable
   key. The key field only works while it has focus; a browser page cannot see keys pressed elsewhere, so the button is
   the dependable path.
2. **Capture + identify.** One face image is captured in the browser, processed in memory, and matched 1:N against
   *active registered* users' local embeddings. The R307 then does its own 1:N search and the app maps its template ID
   back to a user. No ID is typed at verification; an ID is requested only during registration.
3. **Fuse.** Face score (0-100) and binary fingerprint evidence go through the fuzzy engine. Evidence is `MATCH` only when
   both modalities named the same user.
4. **Gates (first failing gate gives the reason code).** face identified -> fingerprint identified -> same user ->
   account active -> face score >= calibrated face threshold -> fuzzy score >= decision threshold. Any missing
   evidence, sensor failure, timeout, invalid score, registry error or audit-write failure ends in `DENY`,
   `INCOMPLETE` or `ERROR`, never `ACCEPT`.

### Fuzzy engine (`src/fuzzy_engine.py`)

Inputs: face score and binary fingerprint evidence (the R307 firmware reports only match/no-match, so no fingerprint
confidence is invented). Rules (min for AND, clip, max aggregation, centroid over 0..100):

| Rule | IF | THEN |
|---|---|---|
| R1 | fingerprint No Match | Low |
| R2 | fingerprint Match AND face Low | Low |
| R3 | fingerprint Match AND face Medium | Low |
| R4, R5 | fingerprint Match AND face High | High, Very High |

The Authenticate and Fuzzy pages show every stage: crisp inputs, memberships, per-rule activation, the aggregated
output curve, the centroid, and the threshold comparison. Default face sets: Low (0,0,55), Medium (35,60,85), High
(65,100,100); decision threshold `AUTHENTICATION_THRESHOLD = 75` (provisional).

**Important calibration interaction.** With these fixed sets and a fingerprint match, the fuzzy layer only reaches 75 at
a face score of about **83.5** (cosine similarity about 0.67). A calibrated face threshold below that is therefore not
the binding face requirement, and the app says so. Setting `FUZZY_ANCHOR_FACE_SETS = True` in `config.py` positions the
face sets around the calibrated threshold instead (High starts at the threshold and is full `FUZZY_ANCHOR_RAMP`
points above it). It is off by default because it loosens the face requirement; turn it on only with real labelled data.

### Face scores and calibration

Score = (cosine similarity + 1) x 50, an arbitrary display scale, not a probability. There is deliberately no default
face threshold: identification fails closed until one is set in **Calibration** (record labelled genuine/impostor
comparisons, review, apply) or `config.FACE_THRESHOLD`. The Calibration page also plots the FAR/FRR trade-off and an
approximate EER from your CSV and warns when the sample is small. `python calibrate_face_threshold.py scores.csv
--target-far 0.01` does the threshold suggestion offline. A threshold from a small classroom set is not a security
guarantee.

## Privacy

- Local only: face embeddings in `data/users/*.npy`, fingerprint templates stay inside the R307 (the PC keeps only a
  user-to-template-ID map, `data/fingerprint_ids.json`), profiles and audit rows in `data/authentication.sqlite3`.
- Audit rows hold outcome, reason code, fuzzy score and pseudonymous IDs only: no images, embeddings or templates.
  Existing audit databases are upgraded in place (a `reason` column is added; old rows are kept).
- Raw face images are not saved. `.gitignore` excludes the database, embeddings, models, mappings and calibration data;
  do not zip or share `data/`.
- **Before re-enrolling anyone**, open **Audit -> Enrollment status**: it lists, per ID, whether the profile is
  registered/active and whether a face embedding and fingerprint mapping exist (without reading their contents).
  Register reuses an existing face embedding or fingerprint mapping for the same ID.
- Registration validates the whole profile *before* touching biometrics, so a typo cannot leave a stray enrollment.
- Accounts can be deactivated on the Audit page; inactive accounts are denied even if both biometrics match.

## Arduino Uno + R307 (supported hardware path)

Upload `arduino/arduino_uno_r307/arduino_uno_r307.ino` (Adafruit Fingerprint Sensor Library). R307 TXD -> Uno D2, Uno D3
-> R307 RXD, common ground; power the R307 within its own specification (commonly 4.2-6.0 V). Protocol over USB serial at
115200 baud, newline-delimited: `PING`, `ENROLL <id>`, `VERIFY <id>`, `IDENTIFY` (unchanged in this revision, so no
re-upload is needed for these changes). Close Arduino Serial Monitor before the app opens the port. The sensor-side
confidence value is not used. `arduino/wemos_d1_r1_r307/` is a legacy sketch without `IDENTIFY`; it is not the active path.
`src/gui.py` is an older Tkinter front end that `main.py` no longer launches; it does not apply the active-account check.

## Evaluation: what data would make FAR/FRR/F1 meaningful

No performance results are included, and none may be inferred from the demo, mock sensor or unit tests. Definitions
follow the reference paper (Table 4, p. 18): FAR = false accepts / impostor trials, FRR = false rejects / genuine
trials, GAR = 1 - FRR, EER where FAR = FRR (`src/evaluation.py`). To measure them you need:

- **Face:** many genuine comparisons per enrolled person across sessions (lighting, pose, days apart) and impostor
  comparisons between *different* consenting people. Hundreds of trials per class is a sensible floor for FAR near
  1%; observing zero false accepts in N impostor trials only bounds FAR near 3/N.
- **Fingerprint:** genuine and impostor attempts on this R307 (the datasheet's FAR/FRR are vendor claims, not
  results from this project).
- **End to end:** labelled attempts of the whole system (genuine users, impostors presenting their own face and finger,
  and mixed cases such as one person's face with another's finger) to compute FAR, FRR, precision, recall and F1 of the
  *fused decision*. `python main.py --cli` -> option 4 accepts a JSON array of `{face_score, fingerprint_match, genuine}`;
  results are only as real as those labels.
- Hold out data not used to pick the thresholds, and report the sample sizes with every rate.

## Mapping to the reference paper (Houssein et al., Arch. Comput. Methods Eng., DOI 10.1007/s11831-026-10731-3)

The paper is a *review*; it reports other studies' results under heterogeneous protocols (p. 21) and none of its figures
describe this project.

| Paper point | Page | In this project |
|---|---|---|
| Fusion levels (sensor, feature, score, rank, decision); score-level fusion generally recommended | 4 | Face and fingerprint are fused at score/decision level: face cosine score + the R307's binary result |
| Fuzzy logic handles ambiguous, imprecise biometric data; membership functions, fuzzy sets and rules | 5-6 | Mamdani engine with explicit sets and rules |
| Fuzzy fusion helps when one modality gives an unreliable score (AFGA 96% vs 88% SVM is the cited study's own result, not reproduced here) | 25 | Fingerprint No Match always forces a Low output; a weak face score cannot be rescued by a match |
| Fuzzy: lower stand-alone accuracy than deep models but robust to noisy/incomplete input, low computational cost | 21, 27 | The engine needs only about 500 small membership evaluations per decision; no accuracy claim is made |
| Missing data in score-level fusion is handled by imputation in some work | 4 | Deliberately *not* done: missing or invalid evidence fails closed |
| FAR/FRR/GAR/EER definitions and the FAR-FRR threshold trade-off | 18 | `src/evaluation.py`; Calibration page trade-off plot and EER |
| Presentation-attack/liveness detection needed; accuracy does not imply spoof robustness | 26 | **Not implemented** (stated in the UI and below) |
| Privacy: biometrics cannot be revoked; template protection, minimal sharing | 26 | Local-only storage, template stays on the R307, no biometric data in audit |
| Explainability and auditability of decisions | 26-27 | Full inference trace and per-attempt reason codes |
| Edge/IoT constraints | 26-27 | Light fuzzy layer (see above); the face model still runs on the laptop |
| Data variability / cross-sensor generalization (8-15 point drops reported in other work) | 25, 27 | Thresholds are specific to this webcam and R307; recalibrate if either changes |

## Known limitations

- Face threshold needs labelled genuine/impostor validation; the default fuzzy threshold (75) and set shapes are not
  scientifically optimal.
- **No liveness / presentation-attack detection:** a photo, screen or replay of an enrolled face is not rejected by the
  webcam path, and the R307 firmware here has no spoof check beyond the sensor's own behaviour.
- Binary fingerprint evidence only; a single 1:N R307 match is trusted as an identity.
- No production-grade security: no encryption of local embeddings, no tamper-evident audit log, no lockout/rate limiting.
- Verified only by unit tests with stubs; hardware and browser behavior must be checked on the real laptop.

## Project map

- `src/fuzzy_engine.py` memberships, rules, inference trace, acceptance boundary, optional anchored sets.
- `src/authentication.py` fail-closed orchestration with ordered gates and reason codes.
- `src/evaluation.py` FAR/FRR/GAR/EER, sweep, sample-size warnings. `calibrate_face_threshold.py` CSV tools.
- `src/enrollment_state.py` read-only local enrollment report. `src/user_registry.py` profiles and active flag.
- `src/audit_logger.py` SQLite outcome log. `src/face_verification.py` YuNet/SFace. `src/fingerprint_sensor.py` R307 bridge.
- `app.py` Streamlit UI. `main.py` launcher/CLI. `tests/` hardware-independent unit tests. `src/hardware/` LCD/SD/RFID placeholders.
