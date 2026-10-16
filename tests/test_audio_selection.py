from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from app import App


class DeviceChoice:
    def __init__(self, selected=""):
        self.selected = selected
        self.values = []

    def get(self):
        return self.selected

    def __setitem__(self, key, value):
        self.values = value

    def __getitem__(self, key):
        return self.values

    def current(self, index=None):
        if index is None:
            return self.values.index(self.selected)
        self.selected = self.values[index]

    def set(self, value):
        self.selected = value


class AudioSelectionTests(unittest.TestCase):
    def test_start_keeps_earbuds_when_windows_defaults_to_monitor(self):
        microphone = {"index": 12, "name": "Microphone Array (Realtek(R) Audio)"}
        monitor = {"index": 14, "name": "DELL U2715H [Loopback]"}
        earbuds = {"index": 24, "name": "Headphones (Pixel Buds Pro de Ryan) [Loopback]"}
        app = NS(
            busy=False,
            mode=NS(get=lambda: "Online meeting + microphone"),
            mic=DeviceChoice("Microphone Array (Realtek(R) Audio)  [12]"),
            output=DeviceChoice("Headphones (Pixel Buds Pro de Ryan) [Loopback]  [20]"),
            settings={}, status=Mock(), begin=Mock(),
        )
        app.refresh_devices = lambda: App.refresh_devices(app)
        with patch("audio_capture.devices", return_value=([microphone], [monitor, earbuds], 12, 14)):
            App.start(app)
        app.begin.assert_called_once_with(
            [("Microphone", microphone), ("Meeting audio", earbuds)], None)
        app.status.set.assert_not_called()

    def test_reopening_restores_saved_playback_and_missing_device_uses_default(self):
        monitor = {"index": 14, "name": "DELL U2715H [Loopback]"}
        earbuds = {"index": 24, "name": "Headphones (Pixel Buds Pro de Ryan) [Loopback]"}
        app = NS(mic=DeviceChoice(), output=DeviceChoice(), status=Mock(),
                 settings={"output": "Headphones (Pixel Buds Pro de Ryan) [Loopback]  [20]"})
        with patch("audio_capture.devices", return_value=([], [monitor, earbuds], None, 14)):
            App.refresh_devices(app)
        self.assertEqual(app.output.get(), "Headphones (Pixel Buds Pro de Ryan) [Loopback]  [24]")
        with patch("audio_capture.devices", return_value=([], [monitor], None, 14)):
            App.refresh_devices(app)
        self.assertEqual(app.output.get(), "DELL U2715H [Loopback]  [14]")
        app.status.set.assert_not_called()


if __name__ == "__main__":
    unittest.main()
