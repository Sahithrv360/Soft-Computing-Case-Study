import unittest
from src.fingerprint_sensor import SerialPortInfo
from main import resolve_selected_port

class SerialSelectionTests(unittest.TestCase):
    def setUp(self):
        self.ports=[SerialPortInfo("COM9","Prolific USB Serial","USB VID:PID=067B:2303"),
                    SerialPortInfo("COM3","Bluetooth","BTHENUM")]
    def test_accepts_full_name(self):
        self.assertEqual(resolve_selected_port("COM9",self.ports),"COM9")
    def test_accepts_numeric_shorthand(self):
        self.assertEqual(resolve_selected_port("9",self.ports),"COM9")
    def test_rejects_undetected_port(self):
        with self.assertRaises(ValueError): resolve_selected_port("10",self.ports)
    def test_blank_cancels(self):
        self.assertIsNone(resolve_selected_port(" ",self.ports))

if __name__ == "__main__": unittest.main()
