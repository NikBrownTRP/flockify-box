import pytest
from unittest.mock import patch, MagicMock
import subprocess

from bluetooth_manager import BluetoothManager


class TestSanitizeAddress:
    def setup_method(self):
        self.bm = BluetoothManager()

    def test_sanitize_valid_address(self):
        assert self.bm._sanitize_address("AA:BB:CC:DD:EE:FF") == "AA:BB:CC:DD:EE:FF"

    def test_sanitize_lowercase(self):
        assert self.bm._sanitize_address("aa:bb:cc:dd:ee:ff") == "AA:BB:CC:DD:EE:FF"

    def test_sanitize_invalid_short(self):
        assert self.bm._sanitize_address("AA:BB:CC") is None

    def test_sanitize_empty(self):
        assert self.bm._sanitize_address("") is None

    def test_sanitize_none(self):
        assert self.bm._sanitize_address(None) is None

    def test_sanitize_injection(self):
        assert self.bm._sanitize_address("AA:BB:CC:DD:EE:FF; rm -rf /") is None


class TestParseDevices:
    def setup_method(self):
        self.bm = BluetoothManager()

    def test_parse_devices_normal(self):
        output = (
            "Device AA:BB:CC:DD:EE:01 Speaker One\n"
            "Device AA:BB:CC:DD:EE:02 Headphones Two\n"
        )
        devices = self.bm._parse_devices(output)
        assert len(devices) == 2
        assert devices[0]['address'] == "AA:BB:CC:DD:EE:01"
        assert devices[0]['name'] == "Speaker One"
        assert devices[1]['address'] == "AA:BB:CC:DD:EE:02"
        assert devices[1]['name'] == "Headphones Two"

    def test_parse_devices_empty(self):
        assert self.bm._parse_devices("") == []

    def test_parse_devices_skips_unnamed(self):
        """Devices whose name equals their address are skipped."""
        output = "Device AA:BB:CC:DD:EE:01 AA:BB:CC:DD:EE:01\n"
        devices = self.bm._parse_devices(output)
        assert devices == []

    def test_parse_devices_dedup(self):
        """Duplicate addresses only appear once."""
        output = (
            "Device AA:BB:CC:DD:EE:01 Speaker One\n"
            "Device AA:BB:CC:DD:EE:01 Speaker One\n"
        )
        devices = self.bm._parse_devices(output)
        assert len(devices) == 1


class TestPair:
    def setup_method(self):
        self.bm = BluetoothManager()

    def test_pair_invalid_address(self):
        result = self.bm.pair("not-an-address")
        assert result['ok'] is False
        assert 'Invalid' in result['error']

    @patch('bluetooth_manager.subprocess.run')
    def test_pair_success(self, mock_run):
        """Successful pair calls pair, trust, and connect."""
        mock_run.return_value = MagicMock(
            stdout='Success', stderr='', returncode=0
        )
        result = self.bm.pair("AA:BB:CC:DD:EE:FF")
        assert result['ok'] is True

        # Collect all bluetoothctl sub-commands used
        calls = mock_run.call_args_list
        commands = [c[0][0] for c in calls]
        # Flatten to find the relevant sub-commands
        subcmds = [cmd[1] if len(cmd) > 1 else None for cmd in commands]

        assert ['bluetoothctl', 'pair', 'AA:BB:CC:DD:EE:FF'] in commands
        assert ['bluetoothctl', 'trust', 'AA:BB:CC:DD:EE:FF'] in commands
        assert ['bluetoothctl', 'connect', 'AA:BB:CC:DD:EE:FF'] in commands
