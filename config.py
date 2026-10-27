"""Central, conservative defaults for the educational prototype."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATABASE_PATH = DATA_DIR / "authentication.sqlite3"
FACE_MODEL_DIR = DATA_DIR / "models"
FACE_DETECTOR_MODEL = FACE_MODEL_DIR / "face_detection_yunet_2023mar.onnx"
FACE_EMBEDDING_MODEL = FACE_MODEL_DIR / "face_recognition_sface_2021dec.onnx"
FACE_THRESHOLD: float | None = None  # Set only after calibration on representative validation data.
AUTHENTICATION_THRESHOLD = 75.0
# Default False: the fuzzy face sets keep their fixed shape (a fingerprint match then needs a face
# score of about 83.5 to reach ACCEPT). True positions the sets around the calibrated face
# threshold instead (see FaceSets.anchored). Enable only after calibrating on real labelled data.
FUZZY_ANCHOR_FACE_SETS = False
FUZZY_ANCHOR_RAMP = 10.0


def get_face_threshold() -> float | None:
    """Use configured threshold or the locally saved GUI threshold, if valid."""
    if FACE_THRESHOLD is not None:
        return FACE_THRESHOLD
    try:
        value = float(json.loads((DATA_DIR / "face_threshold.json").read_text(encoding="utf-8"))["threshold"])
        return value if 0 <= value <= 100 else None
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
