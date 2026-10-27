# AGENTS.md

Compact agent guidance for this repository.

## Project

Educational multimodal biometric authentication prototype. Not production security software.

Combines a Streamlit app (`app.py`), local Python modules (`src/`), an Arduino R307 fingerprint bridge, and a Mamdani fuzzy decision layer, built around the method in `s11831-026-10731-3.pdf`.

## Commands

Windows PowerShell, Python 3.12. Repo venv is `.venv` (activate with `.\.venv\Scripts\Activate.ps1`; verify it points to a valid interpreter before relying on it).

- `python -m pip install -r requirements.txt`
- `python -m unittest discover -s tests -v`
- `python main.py` — Streamlit app (also runnable as `streamlit run app.py`); flags: `--cli`, `--mock`, `--fingerprint-port COM11`
- `python calibrate_face_threshold.py <scores.csv> --target-far 0.01`

## Hard requirements

- Accept only when face and fingerprint identify the same registered user and the fuzzy score meets `AUTHENTICATION_THRESHOLD` (provisional default 75).
- Face acceptance uses calibrated `FACE_THRESHOLD` on the cosine-similarity-mapped 0–100 scale; it is unset by default, so verification fails closed until calibrated.
- Missing evidence, invalid values, sensor failures, or identity mismatches fail closed; no ACCEPT path may be reachable with bad evidence.
- Fingerprint evidence is binary (Match / No Match); never invent or persist numeric confidence.
- Fuzzy engine: Mamdani-style min/max inference, centroid defuzzification over integer outputs 0–100; conservative rules (No Match → Low; Match with Low/Medium face → Low; Match with High face → High/Very High).
- No webcam liveness detection; photos or replays can spoof capture. No production-security or paper-level accuracy claims are justified.

## Gotchas

- Close the Arduino Serial Monitor before Python opens the COM port; a port can be held by only one program at a time.
- If the COM port fails to open, check the current COM assignment, cable/adapter, driver status, and whether another program owns the port.
- Face detector/recognizer models must be manually downloaded into `data/models/` as `face_detection_yunet_2023mar.onnx` and `face_recognition_sface_2021dec.onnx`; they are not in the repo.
- Uno/R307 is the active hardware path (D2/D3 wiring, USB serial 115200 baud). Wemos D1 R1 + R307 is legacy reference only and lacks the `IDENTIFY` command.
- LCD, SD, and RFID modules are interface placeholders, not connected hardware.
- Keyboard activation uses a focused text field with a printable-key trigger; keep the visible button fallback.
- Keep biometric material local; audit records must not contain images, embeddings, or fingerprint templates.

## Source layout

- `app.py` — Streamlit pages: register, authenticate, fuzzy demo, calibration, audit, hardware.
- `main.py` — CLI entry (`--cli`, `--mock`, `--fingerprint-port`).
- `src/` — fuzzy engine, face verification, fingerprint sensor/bridge, authentication, user registry, audit logger, evaluation, enrollment state, hardware placeholders.
- `tests/` — hardware-independent unit tests.
- `arduino/` — Uno (active) and Wemos (legacy) sketches.

## Instruction sources

- `README.md` — setup, architecture, limitations, calibration workflow.
- `CLAUDE_PROMPT.md` — original task brief; historical context, not auto-applied.
- `s11831-026-10731-3.pdf` — reference method; read before methodology changes and cite page numbers for paper-derived claims.
