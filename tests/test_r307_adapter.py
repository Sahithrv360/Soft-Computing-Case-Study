import json
import tempfile
import unittest
from pathlib import Path
from src.fingerprint_sensor import WemosR307Sensor

class R307AdapterTests(unittest.TestCase):
    def test_allocates_and_persists_user_template_mapping_without_hardware(self):
        with tempfile.TemporaryDirectory() as folder:
            mapping=Path(folder)/"fingerprints.json"
            sensor=WemosR307Sensor("COM42",mapping)
            self.assertEqual(sensor._template_id("user-a",create=True),1)
            sensor._user_ids["user-a"]=1
            sensor._save_mapping()
            self.assertEqual(json.loads(mapping.read_text(encoding="utf-8")),{"user-a":1})
            loaded=WemosR307Sensor("COM42",mapping)
            self.assertEqual(loaded._template_id("user-a"),1)
    def test_rejects_unknown_user_without_enrollment(self):
        with tempfile.TemporaryDirectory() as folder:
            sensor=WemosR307Sensor("COM42",Path(folder)/"missing.json")
            with self.assertRaises(ValueError): sensor._template_id("not-enrolled")
    def test_rejects_duplicate_sensor_template_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            mapping=Path(folder)/"fingerprints.json"
            mapping.write_text('{"a": 3, "b": 3}',encoding="utf-8")
            with self.assertRaises(ValueError): WemosR307Sensor("COM42",mapping)
    def test_identify_maps_sensor_template_to_pseudonymous_user(self):
        with tempfile.TemporaryDirectory() as folder:
            sensor=WemosR307Sensor("COM42",Path(folder)/"fingerprints.json")
            sensor._user_ids={"alice":7}
            sensor._command=lambda command, expected, timeout=None: {
                "event":"identify", "result":"match", "template_id":7}
            self.assertEqual(sensor.identify(),"alice")
    def test_identify_unknown_template_returns_no_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            sensor=WemosR307Sensor("COM42",Path(folder)/"fingerprints.json")
            sensor._user_ids={"alice":7}
            sensor._command=lambda command, expected, timeout=None: {
                "event":"identify", "result":"match", "template_id":9}
            self.assertIsNone(sensor.identify())

if __name__ == "__main__": unittest.main()
