# Claude Code task prompt

Act as a senior Python, biometric systems, and embedded-systems engineer. Work directly in this project.

## Start with the reference

Read `s11831-026-10731-3.pdf` completely enough to understand its method, equations, figures, tables, assumptions, and limitations. Before editing, summarize the paper's method and map its recommendations to this educational prototype. Cite page numbers for paper-derived claims. Do not present the paper's results as results from this project or copy performance claims as if validated here.

## Inspect the current project before changing it

Inspect the Streamlit app, Python modules, tests, Arduino sketches, README, and dependency list. Preserve useful work and avoid wholesale rewrites. The project currently includes:

- `app.py`: Streamlit registration, automatic authentication, face calibration, fuzzy demo, audit, and hardware pages.
- `src/fuzzy_engine.py`: Mamdani-style fuzzy inference using a face score from 0–100 and binary R307 match/no-match evidence. It uses membership functions, min/max inference, centroid defuzzification, and a configurable decision threshold. Do not invent fingerprint confidence values.
- `src/face_verification.py`: OpenCV YuNet/SFace embeddings, local enrollment, one-to-many face identification, and comparison scoring.
- `src/fingerprint_sensor.py` and `src/authentication.py`: Python serial bridge and fail-closed authentication requiring face and fingerprint to identify the same user.
- `src/user_registry.py`: validated local SQLite account/profile records.
- `src/audit_logger.py`: SQLite authentication audit records.
- `arduino/arduino_uno_r307/arduino_uno_r307.ino`: Arduino Uno/R307 bridge with `PING`, `ENROLL`, `VERIFY`, and `IDENTIFY` commands.
- `tests/`: hardware-independent unit tests.

Target environment: Windows, PowerShell, Python 3.12, laptop webcam, Arduino Uno, R307 fingerprint sensor. The Uno/R307 `PING` and fingerprint enrollment have worked. The Uno sketch uses D2/D3 for the sensor and USB serial for the PC. Wemos and the PL2303 adapter are not the active hardware path.

The user previously enrolled face and fingerprint data under pseudonymous IDs. Do not package or expose biometric samples, embeddings, templates, local databases, or calibration data. Check existing local enrollment state before recommending re-enrollment.

## Goals

1. Compare the existing design to the PDF and recommend only concrete, relevant improvements.
2. Keep registration and authentication clear: ask for an ID during registration only; identify the user automatically during verification.
3. Accept only when face and fingerprint identify the same active registered user and the fuzzy result passes its configured threshold.
4. Explain and show crisp inputs, fuzzy membership values, rule activation, aggregation, defuzzified output, and decision threshold.
5. Keep missing evidence, sensor failures, invalid values, and identity mismatches fail-closed.
6. Keep biometric material local and out of audit records. Do not store raw face images, face embeddings in audit tables, fingerprint images, or templates on the PC.
7. Keep the Streamlit app local because it uses the laptop webcam and Uno COM port. Do not imply a remote Streamlit server can access local hardware.
8. Make keyboard activation reliable and understandable. The app currently uses a focused text field where a printable key triggers activation. Provide a visible button fallback; do not claim a browser can detect all keys while the page is unfocused.
9. Keep the prototype's limitations clear: face threshold needs labelled genuine/impostor validation; the default is not scientifically optimal; webcam liveness detection is not implemented; no production-security or paper-level accuracy claim is justified.

## Work process

- First inspect and report current behavior, gaps, and a short plan.
- Then implement concrete improvements directly in the project.
- Add or update tests for registration validation, fuzzy rules, face/fingerprint identity agreement, missing evidence, sensor failures, audit logging, and fail-closed behavior.
- Run tests with the actual Python 3.12 environment if available. Check that `.venv` points to a valid interpreter before using it. Never claim tests or hardware checks that were not observed.
- Update PowerShell setup and launch instructions, dependencies, and README architecture/limitations.
- Preserve the Arduino protocol unless a specific change is needed; if firmware behavior changes, state that the user must upload the updated sketch.
- Do not fabricate evaluation data or biometric accuracy results. Explain which data would be needed for meaningful FAR, FRR, precision, recall, and F1 measurements.

## Final report

Summarize files changed, improvements based on the PDF with page references, commands to install/run/test, observed test and hardware results, and remaining calibration/privacy/hardware limitations.
