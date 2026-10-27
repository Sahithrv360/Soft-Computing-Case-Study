"""SQLite audit records contain outcomes and reason codes only, never biometric
samples, embeddings or templates."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any
from contextlib import closing


class AuditLogger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, user_id TEXT NOT NULL,
                face_outcome TEXT, fingerprint_outcome TEXT, fuzzy_score REAL,
                decision TEXT NOT NULL, error_category TEXT, mock_hardware INTEGER NOT NULL)""")
            # Older databases lack the outcome-reason column; add it without touching rows.
            columns = {row[1] for row in db.execute("PRAGMA table_info(attempts)")}
            if "reason" not in columns:
                db.execute("ALTER TABLE attempts ADD COLUMN reason TEXT")
            db.commit()
    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)
    def log_attempt(self, *, user_id: str, face_outcome: str | None, fingerprint_outcome: str | None,
                    fuzzy_score: float | None, decision: str, error_category: str | None = None,
                    mock_hardware: bool = False, timestamp: str | None = None,
                    reason: str | None = None) -> int:
        with closing(self._connect()) as db:
            try:
                cur = db.execute("INSERT INTO attempts(timestamp,user_id,face_outcome,fingerprint_outcome,fuzzy_score,decision,error_category,mock_hardware,reason) VALUES(?,?,?,?,?,?,?,?,?)",
                    (timestamp or datetime.now(timezone.utc).isoformat(), user_id, face_outcome,
                     fingerprint_outcome, fuzzy_score, decision, error_category, int(mock_hardware), reason))
                db.commit()
                return int(cur.lastrowid)
            except Exception:
                db.rollback()
                raise
    def get_attempts(self, limit: int = 100) -> list[dict[str, Any]]:
        with closing(self._connect()) as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute("SELECT * FROM attempts ORDER BY id DESC LIMIT ?", (limit,))]
