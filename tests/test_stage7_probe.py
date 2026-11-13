"""USB inventory must not equate a probe or serial bridge with a target MCU."""

import plistlib
import unittest

from cybertron.stage7_probe import summarize_usb_registry


class Stage7ProbeTests(unittest.TestCase):
    def test_stlink_and_native_esp_usb_are_separate(self):
        data = plistlib.dumps([{"IORegistryEntryChildren": [
            {"USB Product Name": "STM32 STLink", "idVendor": 0x0483,
             "idProduct": 0x3748, "USB Serial Number": "do-not-emit"},
            {"USB Product Name": "USB JTAG/serial debug unit", "idVendor": 0x303A,
             "idProduct": 0x1001},
        ]}])
        report = summarize_usb_registry(data)
        self.assertEqual(len(report["stlink_probes"]), 1)
        self.assertEqual(len(report["esp32_native_usb_candidates"]), 1)
        self.assertNotIn("do-not-emit", str(report))

    def test_generic_serial_device_is_not_identified_as_esp32(self):
        data = plistlib.dumps([{"USB Product Name": "USB Single Serial",
                               "idVendor": 0x1A86, "idProduct": 0x55D3}])
        report = summarize_usb_registry(data)
        self.assertEqual(report["esp32_native_usb_candidates"], [])
        self.assertEqual(len(report["other_usb_serial_candidates"]), 1)


if __name__ == "__main__":
    unittest.main()
