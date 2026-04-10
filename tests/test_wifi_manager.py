"""Tests for WiFiManager — scanning, connecting, saved networks, AP management."""

import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wifi_manager import WiFiManager, AP_FLAG_FILE, AP_CON_NAME


# ------------------------------------------------------------------
# is_ap_active()
# ------------------------------------------------------------------

class TestIsApActive:
    def setup_method(self):
        self.wm = WiFiManager()

    @patch('wifi_manager.os.path.exists', return_value=True)
    def test_returns_true_when_flag_file_exists(self, mock_exists):
        assert self.wm.is_ap_active() is True
        mock_exists.assert_called_once_with(AP_FLAG_FILE)

    @patch('wifi_manager.os.path.exists', return_value=False)
    def test_returns_false_when_flag_file_absent(self, mock_exists):
        assert self.wm.is_ap_active() is False
        mock_exists.assert_called_once_with(AP_FLAG_FILE)


# ------------------------------------------------------------------
# get_status()
# ------------------------------------------------------------------

class TestGetStatus:
    def setup_method(self):
        self.wm = WiFiManager()

    @patch('wifi_manager.os.path.exists', return_value=False)
    @patch('wifi_manager.subprocess.run')
    def test_connected_with_ip(self, mock_run, mock_exists):
        """Connected to a real network with an IP address."""
        device_output = (
            "GENERAL.STATE:100 (connected)\n"
            "GENERAL.CONNECTION:MyHomeWiFi"
        )
        ip_output = "IP4.ADDRESS[1]:192.168.1.42/24"

        mock_run.side_effect = [
            MagicMock(stdout=device_output, returncode=0),
            MagicMock(stdout=ip_output, returncode=0),
        ]

        status = self.wm.get_status()
        assert status["connected"] is True
        assert status["ssid"] == "MyHomeWiFi"
        assert status["ip"] == "192.168.1.42"
        assert status["ap_active"] is False

    @patch('wifi_manager.os.path.exists', return_value=False)
    @patch('wifi_manager.subprocess.run')
    def test_disconnected(self, mock_run, mock_exists):
        """Disconnected from all networks."""
        device_output = (
            "GENERAL.STATE:30 (disconnected)\n"
            "GENERAL.CONNECTION:--"
        )
        mock_run.return_value = MagicMock(stdout=device_output, returncode=0)

        status = self.wm.get_status()
        assert status["connected"] is False
        assert status["ssid"] is None
        assert status["ip"] is None

    @patch('wifi_manager.os.path.exists', return_value=True)
    @patch('wifi_manager.subprocess.run')
    def test_ap_active_connected_to_ap(self, mock_run, mock_exists):
        """Connected to AP hotspot -- ssid should be None (AP is excluded)."""
        device_output = (
            "GENERAL.STATE:100 (connected)\n"
            "GENERAL.CONNECTION:FlockifyAP"
        )
        ip_output = "IP4.ADDRESS[1]:10.42.0.1/24"

        mock_run.side_effect = [
            MagicMock(stdout=device_output, returncode=0),
            MagicMock(stdout=ip_output, returncode=0),
        ]

        status = self.wm.get_status()
        assert status["connected"] is True
        assert status["ssid"] is None  # AP name excluded
        assert status["ap_active"] is True

    @patch('wifi_manager.os.path.exists', return_value=False)
    @patch('wifi_manager.subprocess.run')
    def test_not_connected_no_ip_lookup(self, mock_run, mock_exists):
        """When disconnected, IP lookup should not be attempted."""
        device_output = "GENERAL.STATE:30 (disconnected)\nGENERAL.CONNECTION:--"
        mock_run.return_value = MagicMock(stdout=device_output, returncode=0)

        self.wm.get_status()
        # Only one subprocess call (device show), no IP lookup
        assert mock_run.call_count == 1


# ------------------------------------------------------------------
# scan()
# ------------------------------------------------------------------

class TestScan:
    def setup_method(self):
        self.wm = WiFiManager()

    @patch('wifi_manager.time.sleep')
    @patch('wifi_manager.subprocess.run')
    def test_parse_and_sort_by_signal(self, mock_run, mock_sleep):
        scan_output = (
            " :Network_A:45:WPA2\n"
            " :Network_B:80:WPA2\n"
            "*:Network_C:60:WPA1"
        )
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=0),  # rescan
            MagicMock(stdout=scan_output, returncode=0),  # list
        ]

        results = self.wm.scan()
        assert len(results) == 3
        # Sorted by signal descending
        assert results[0]["ssid"] == "Network_B"
        assert results[0]["signal"] == 80
        assert results[1]["ssid"] == "Network_C"
        assert results[1]["in_use"] is True
        assert results[2]["ssid"] == "Network_A"

    @patch('wifi_manager.time.sleep')
    @patch('wifi_manager.subprocess.run')
    def test_deduplication_keeps_strongest(self, mock_run, mock_sleep):
        scan_output = (
            " :DupeNet:30:WPA2\n"
            " :DupeNet:75:WPA2\n"
            " :DupeNet:50:WPA2"
        )
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=0),
            MagicMock(stdout=scan_output, returncode=0),
        ]

        results = self.wm.scan()
        assert len(results) == 1
        assert results[0]["ssid"] == "DupeNet"
        assert results[0]["signal"] == 75

    @patch('wifi_manager.time.sleep')
    @patch('wifi_manager.subprocess.run')
    def test_hidden_networks_skipped(self, mock_run, mock_sleep):
        scan_output = " ::50:WPA2\n :Visible:70:WPA2"
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=0),
            MagicMock(stdout=scan_output, returncode=0),
        ]

        results = self.wm.scan()
        assert len(results) == 1
        assert results[0]["ssid"] == "Visible"

    @patch('wifi_manager.time.sleep')
    @patch('wifi_manager.subprocess.run')
    def test_invalid_signal_defaults_to_zero(self, mock_run, mock_sleep):
        scan_output = " :BadSignal:abc:WPA2"
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=0),
            MagicMock(stdout=scan_output, returncode=0),
        ]

        results = self.wm.scan()
        assert len(results) == 1
        assert results[0]["signal"] == 0

    @patch('wifi_manager.time.sleep')
    @patch('wifi_manager.subprocess.run')
    def test_empty_scan_results(self, mock_run, mock_sleep):
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=0),
            MagicMock(stdout="", returncode=0),
        ]

        results = self.wm.scan()
        assert results == []


# ------------------------------------------------------------------
# connect()
# ------------------------------------------------------------------

class TestConnect:
    def setup_method(self):
        self.wm = WiFiManager()

    def test_empty_ssid_returns_error(self):
        result = self.wm.connect("", "password123")
        assert result["ok"] is False
        assert result["error"] == "SSID is required"

    @patch('wifi_manager.os.remove')
    @patch('wifi_manager.os.path.exists', return_value=False)
    @patch('wifi_manager.time.sleep')
    @patch('wifi_manager.subprocess.run')
    def test_success_no_ap(self, mock_run, mock_sleep, mock_exists, mock_remove):
        """Successful connection when AP was not active."""
        mock_run.return_value = MagicMock(stdout="Success", returncode=0)

        result = self.wm.connect("MyNetwork", "pass123")
        assert result["ok"] is True
        assert result["error"] is None

    @patch('wifi_manager.os.remove')
    @patch('wifi_manager.os.path.exists', return_value=True)
    @patch('wifi_manager.time.sleep')
    @patch('wifi_manager.subprocess.run')
    def test_success_tears_down_ap(self, mock_run, mock_sleep, mock_exists, mock_remove):
        """When AP is active, it is torn down before connecting."""
        mock_run.return_value = MagicMock(stdout="Success", returncode=0)

        result = self.wm.connect("MyNetwork", "pass123")
        assert result["ok"] is True

        # Check AP was torn down: first nmcli call should be connection down
        first_call_args = mock_run.call_args_list[0][0][0]
        assert "down" in first_call_args
        assert AP_CON_NAME in first_call_args

        # Flag file should be removed on success
        mock_remove.assert_called_once_with(AP_FLAG_FILE)

    @patch('wifi_manager.os.remove', side_effect=FileNotFoundError)
    @patch('wifi_manager.os.path.exists', return_value=True)
    @patch('wifi_manager.time.sleep')
    @patch('wifi_manager.subprocess.run')
    def test_success_flag_file_already_gone(self, mock_run, mock_sleep, mock_exists, mock_remove):
        """FileNotFoundError on flag removal is silently ignored."""
        mock_run.return_value = MagicMock(stdout="Success", returncode=0)

        result = self.wm.connect("MyNetwork", "pass123")
        assert result["ok"] is True

    @patch('wifi_manager.os.path.exists', return_value=True)
    @patch('wifi_manager.time.sleep')
    @patch('wifi_manager.subprocess.run')
    def test_failure_restarts_ap(self, mock_run, mock_sleep, mock_exists):
        """When connection fails and AP was active, AP is restarted."""
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=0),   # connection down AP
            MagicMock(stdout="Error: no network", returncode=1),  # wifi connect
            MagicMock(stdout="", returncode=0),   # connection up AP
        ]

        result = self.wm.connect("BadNetwork", "pass")
        assert result["ok"] is False
        assert result["error"] == "Error: no network"

        # AP should have been restarted
        last_call_args = mock_run.call_args_list[-1][0][0]
        assert "up" in last_call_args
        assert AP_CON_NAME in last_call_args

    @patch('wifi_manager.os.path.exists', return_value=False)
    @patch('wifi_manager.time.sleep')
    @patch('wifi_manager.subprocess.run')
    def test_failure_no_ap_no_restart(self, mock_run, mock_sleep, mock_exists):
        """When connection fails but AP was NOT active, no restart."""
        mock_run.return_value = MagicMock(stdout="Connection failed", returncode=1)

        result = self.wm.connect("BadNetwork", "pass")
        assert result["ok"] is False

        # Should NOT have called connection up
        call_args_list = [c[0][0] for c in mock_run.call_args_list]
        for args in call_args_list:
            assert "up" not in args or AP_CON_NAME not in args

    @patch('wifi_manager.os.remove')
    @patch('wifi_manager.os.path.exists', return_value=False)
    @patch('wifi_manager.time.sleep')
    @patch('wifi_manager.subprocess.run')
    def test_connect_without_password(self, mock_run, mock_sleep, mock_exists, mock_remove):
        """Connect to an open network (no password)."""
        mock_run.return_value = MagicMock(stdout="Success", returncode=0)

        result = self.wm.connect("OpenNet", None)
        assert result["ok"] is True

        # The wifi connect call should NOT include password args
        connect_call = mock_run.call_args_list[0][0][0]
        assert "password" not in connect_call


# ------------------------------------------------------------------
# get_saved_networks()
# ------------------------------------------------------------------

class TestGetSavedNetworks:
    def setup_method(self):
        self.wm = WiFiManager()

    @patch('wifi_manager.subprocess.run')
    def test_parse_saved_networks(self, mock_run):
        output = (
            "HomeWiFi:802-11-wireless\n"
            "FlockifyAP:802-11-wireless\n"
            "CoffeeShop:802-11-wireless\n"
            "Wired:802-3-ethernet"
        )
        mock_run.return_value = MagicMock(stdout=output, returncode=0)

        networks = self.wm.get_saved_networks()
        assert "HomeWiFi" in networks
        assert "CoffeeShop" in networks
        # AP and non-wireless excluded
        assert "FlockifyAP" not in networks
        assert "Wired" not in networks

    @patch('wifi_manager.subprocess.run')
    def test_empty_saved_networks(self, mock_run):
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        assert self.wm.get_saved_networks() == []


# ------------------------------------------------------------------
# forget_network()
# ------------------------------------------------------------------

class TestForgetNetwork:
    def setup_method(self):
        self.wm = WiFiManager()

    @patch('wifi_manager.subprocess.run')
    def test_forget_success(self, mock_run):
        mock_run.return_value = MagicMock(stdout="deleted", returncode=0)
        result = self.wm.forget_network("OldWiFi")
        assert result["ok"] is True
        assert result["error"] is None

    @patch('wifi_manager.subprocess.run')
    def test_forget_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="Error: no such connection", returncode=1
        )
        result = self.wm.forget_network("NonExistent")
        assert result["ok"] is False
        assert "no such connection" in result["error"]

    def test_reject_flockify_ap_deletion(self):
        result = self.wm.forget_network(AP_CON_NAME)
        assert result["ok"] is False
        assert "Cannot delete" in result["error"]

    def test_reject_empty_name(self):
        result = self.wm.forget_network("")
        assert result["ok"] is False

    def test_reject_none_name(self):
        result = self.wm.forget_network(None)
        assert result["ok"] is False
