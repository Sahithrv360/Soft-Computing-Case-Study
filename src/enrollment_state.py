"""Read-only report of what is already enrolled locally.

Looks only at *which* files/IDs exist. It never opens or returns embeddings,
fingerprint templates or images, so it is safe to display. Use it before
re-enrolling anyone: the Register page reuses an existing face embedding or
fingerprint mapping for the same ID instead of overwriting it.
"""
from __future__ import annotations

import json
from pathlib import Path


def _fingerprint_ids(mapping_path: Path) -> set[str]:
    try:
        raw = json.loads(mapping_path.read_text(encoding="utf-8"))
        return set(raw) if isinstance(raw, dict) else set()
    except (OSError, ValueError):
        return set()


def enrollment_status(data_dir: Path, registered: list[dict]) -> list[dict]:
    """One row per known ID: registry status plus which modalities are enrolled."""
    face_ids = {p.stem for p in (data_dir / "users").glob("*.npy")} if (data_dir / "users").is_dir() else set()
    finger_ids = _fingerprint_ids(data_dir / "fingerprint_ids.json")
    by_id = {row["user_id"]: row for row in registered}
    rows = []
    for user_id in sorted(set(by_id) | face_ids | finger_ids):
        row = by_id.get(user_id)
        face, finger = user_id in face_ids, user_id in finger_ids
        if row is None:
            note = "enrolled but not registered: cannot be accepted (register the profile to link it)"
        elif not row.get("active", 1):
            note = "deactivated: cannot be accepted"
        elif face and finger:
            note = "ready"
        else:
            note = "missing " + " and ".join(m for m, ok in (("face", face), ("fingerprint", finger)) if not ok)
        rows.append({"user_id": user_id, "registered": row is not None,
                     "active": bool(row and row.get("active", 1)),
                     "face_enrolled": face, "fingerprint_enrolled": finger, "status": note})
    return rows
