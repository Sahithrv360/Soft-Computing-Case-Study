import tempfile
import unittest
from pathlib import Path
from src.audit_logger import AuditLogger

class AuditTests(unittest.TestCase):
    def test_insert_and_retrieve(self):
        with tempfile.TemporaryDirectory() as d:
            logger=AuditLogger(Path(d)/"a.sqlite3")
            rowid=logger.log_attempt(user_id="pseudonym",face_outcome="MATCH",fingerprint_outcome="MATCH",
                fuzzy_score=90.2,decision="ACCEPT",mock_hardware=True)
            row=logger.get_attempts()[0]
            self.assertEqual(row["id"],rowid); self.assertEqual(row["decision"],"ACCEPT")
            self.assertEqual(row["mock_hardware"],1); self.assertNotIn("embedding",row)

if __name__ == "__main__": unittest.main()
