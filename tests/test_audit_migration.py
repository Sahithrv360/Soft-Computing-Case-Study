import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from src.audit_logger import AuditLogger


class AuditMigrationTests(unittest.TestCase):
    def test_old_database_without_reason_column_is_upgraded_in_place(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "old.sqlite3"
            db = sqlite3.connect(path)
            db.execute("""CREATE TABLE attempts (id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, user_id TEXT NOT NULL,
                face_outcome TEXT, fingerprint_outcome TEXT, fuzzy_score REAL, decision TEXT NOT NULL,
                error_category TEXT, mock_hardware INTEGER NOT NULL)""")
            db.execute("INSERT INTO attempts(timestamp,user_id,decision,mock_hardware) VALUES('t','old','DENY',0)")
            db.commit(); db.close()
            logger = AuditLogger(path)
            logger.log_attempt(user_id="new", face_outcome="MATCH:new", fingerprint_outcome="MATCH:new",
                               fuzzy_score=83.2, decision="ACCEPT", reason="ACCEPTED")
            rows = {r["user_id"]: r for r in logger.get_attempts()}
            self.assertEqual(len(rows), 2)                      # old row preserved
            self.assertIsNone(rows["old"]["reason"])
            self.assertEqual(rows["new"]["reason"], "ACCEPTED")
            AuditLogger(path)                                    # opening twice is safe

    def test_schema_has_no_biometric_columns(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "a.sqlite3"; AuditLogger(path)
            with closing(sqlite3.connect(path)) as db:
                cols = {r[1] for r in db.execute("PRAGMA table_info(attempts)")}
            self.assertFalse({c for c in cols if any(w in c for w in ("embed", "template", "image", "photo"))})


if __name__ == "__main__":
    unittest.main()
