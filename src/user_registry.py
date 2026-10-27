"""Local account registry for pseudonymous users and minimal profile metadata."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3


class UserRegistry:
    ROLES = {"student", "faculty", "staff"}
    USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
    EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

    def __init__(self, database_path: str | Path):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS registered_users (
                user_id TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                email TEXT,
                department TEXT,
                role TEXT NOT NULL,
                created_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1)""")
            db.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    @classmethod
    def validate_profile(cls, *, user_id: str, full_name: str, email: str = "",
                         department: str = "", role: str = "student") -> dict:
        """Validate and normalise profile fields without touching the database.

        Call this *before* enrolling biometrics so an invalid profile cannot leave
        orphaned face/fingerprint enrollments behind.
        """
        user_id = user_id.strip()
        full_name = full_name.strip()
        email = email.strip().lower()
        department = department.strip()
        role = role.strip().lower()
        if not cls.USER_ID_PATTERN.fullmatch(user_id):
            raise ValueError("User ID must contain 1–32 letters, digits, underscores, or hyphens")
        if not 2 <= len(full_name) <= 100:
            raise ValueError("Full name must contain 2–100 characters")
        if email and not cls.EMAIL_PATTERN.fullmatch(email):
            raise ValueError("Enter a valid email address or leave it blank")
        if len(department) > 100:
            raise ValueError("Department must be 100 characters or fewer")
        if role not in cls.ROLES:
            raise ValueError("Role must be student, faculty, or staff")
        return {"user_id": user_id, "full_name": full_name, "email": email,
                "department": department, "role": role}

    def register(self, *, user_id: str, full_name: str, email: str = "",
                 department: str = "", role: str = "student") -> None:
        profile = self.validate_profile(user_id=user_id, full_name=full_name, email=email,
                                        department=department, role=role)
        user_id, full_name, email = profile["user_id"], profile["full_name"], profile["email"]
        department, role = profile["department"], profile["role"]
        with closing(self._connect()) as db:
            try:
                db.execute("INSERT INTO registered_users(user_id,full_name,email,department,role,created_at) VALUES(?,?,?,?,?,?)",
                           (user_id, full_name, email or None, department or None, role,
                            datetime.now(timezone.utc).isoformat()))
                db.commit()
            except sqlite3.IntegrityError as exc:
                db.rollback()
                raise ValueError(f"User ID {user_id!r} is already registered") from exc

    def get(self, user_id: str) -> dict | None:
        with closing(self._connect()) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM registered_users WHERE user_id=? AND active=1", (user_id,)).fetchone()
            return dict(row) if row else None

    def list_users(self) -> list[dict]:
        with closing(self._connect()) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(
                "SELECT user_id,full_name,email,department,role,created_at,active FROM registered_users ORDER BY full_name COLLATE NOCASE")]

    def is_active(self, user_id: str) -> bool:
        """True only for a registered, active account (unknown IDs are not active)."""
        return self.get(user_id) is not None

    def active_user_ids(self) -> list[str]:
        with closing(self._connect()) as db:
            return [row[0] for row in db.execute(
                "SELECT user_id FROM registered_users WHERE active=1 ORDER BY user_id")]

    def set_active(self, user_id: str, active: bool) -> None:
        with closing(self._connect()) as db:
            cur = db.execute("UPDATE registered_users SET active=? WHERE user_id=?",
                             (int(active), user_id))
            db.commit()
            if cur.rowcount == 0:
                raise ValueError(f"User ID {user_id!r} is not registered")
