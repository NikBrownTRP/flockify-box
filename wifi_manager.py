"""
WiFiManager — NetworkManager wrapper for scanning, connecting to, and
managing WiFi networks via nmcli.

Also manages the fallback AP hotspot: when the Pi can't find a known
WiFi network on boot, scripts/wifi-ap.sh creates a hotspot. This class
provides the connect() method that tears down the AP, joins a real
network, and brings the AP back if the join fails.
"""

import os
import re
import subprocess
import time
from threading import Lock


AP_CON_NAME = "FlockifyAP"
AP_FLAG_FILE = "/run/flockify-ap-active"


class WiFiManager:
    def __init__(self):
        self._lock = Lock()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _run(self, args, timeout=15):
        """Run an nmcli command and return (stdout, returncode)."""
        try:
            result = subprocess.run(
                ["nmcli"] + args,
                capture_output=True, text=True, timeout=timeout,
            )
            return result.stdout.strip(), result.returncode
        except subprocess.TimeoutExpired:
            print(f"[WiFiManager] nmcli timed out: {args}")
            return "", 1
        except Exception as e:
            print(f"[WiFiManager] nmcli error: {e}")
            return "", 1

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def is_ap_active(self):
        """True if the fallback AP hotspot is currently running."""
        return os.path.exists(AP_FLAG_FILE)

    def get_status(self):
        """Return dict with current WiFi state.

        Keys: connected (bool), ssid (str|None), ip (str|None),
              ap_active (bool).
        """
        status = {
            "connected": False,
            "ssid": None,
            "ip": None,
            "ap_active": self.is_ap_active(),
        }
        out, rc = self._run(
            ["-t", "-f", "GENERAL.STATE,GENERAL.CONNECTION",
             "device", "show", "wlan0"]
        )
        for line in out.splitlines():
            key, _, val = line.partition(":")
            if "STATE" in key and "connected" in val and "disconnected" not in val:
                status["connected"] = True
            if "CONNECTION" in key and val and val != "--":
                ssid = val.strip()
                if ssid != AP_CON_NAME:
                    status["ssid"] = ssid
        # Get IP if connected
        if status["connected"]:
            out2, _ = self._run(
                ["-t", "-f", "IP4.ADDRESS", "device", "show", "wlan0"]
            )
            for line in out2.splitlines():
                if "ADDRESS" in line:
                    _, _, addr = line.partition(":")
                    status["ip"] = addr.split("/")[0].strip()
                    break
        return status

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def scan(self):
        """Scan for available WiFi networks.

        Returns a list of dicts sorted by signal strength (strongest first):
        [{"ssid": str, "signal": int, "security": str, "in_use": bool}]
        """
        with self._lock:
            # Trigger a fresh scan (may take a few seconds)
            self._run(["device", "wifi", "rescan"], timeout=10)
            time.sleep(2)  # give the scan time to complete

            out, rc = self._run(
                ["-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY",
                 "device", "wifi", "list"]
            )

        networks = {}
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) < 4:
                continue
            in_use = parts[0].strip() == "*"
            ssid = parts[1].strip()
            if not ssid:
                continue  # hidden networks
            try:
                signal = int(parts[2].strip())
            except ValueError:
                signal = 0
            security = parts[3].strip()

            # Deduplicate by SSID — keep the strongest signal
            if ssid not in networks or signal > networks[ssid]["signal"]:
                networks[ssid] = {
                    "ssid": ssid,
                    "signal": signal,
                    "security": security,
                    "in_use": in_use,
                }

        result = sorted(networks.values(), key=lambda n: n["signal"], reverse=True)
        return result

    # ------------------------------------------------------------------
    # Connecting
    # ------------------------------------------------------------------

    def connect(self, ssid, password):
        """Connect to a WiFi network.

        If the AP hotspot is active, it is torn down first. If the
        connection attempt fails, the AP is restarted so the user can
        retry from the web UI.

        Returns dict: {"ok": bool, "error": str|None}
        """
        if not ssid:
            return {"ok": False, "error": "SSID is required"}

        was_ap = self.is_ap_active()

        # Tear down the AP before attempting to connect.
        if was_ap:
            print(f"[WiFiManager] Tearing down AP to connect to {ssid}")
            self._run(["connection", "down", AP_CON_NAME], timeout=10)
            time.sleep(2)

        # Attempt the connection.
        print(f"[WiFiManager] Connecting to {ssid}...")
        args = ["device", "wifi", "connect", ssid]
        if password:
            args += ["password", password]
        out, rc = self._run(args, timeout=30)

        if rc == 0:
            # Connection succeeded.
            print(f"[WiFiManager] Connected to {ssid}")
            # Remove the AP flag file.
            try:
                os.remove(AP_FLAG_FILE)
            except FileNotFoundError:
                pass
            # Clean up the AP connection profile.
            self._run(["connection", "delete", AP_CON_NAME], timeout=5)
            return {"ok": True, "error": None}

        # Connection failed — restart the AP so the user can retry.
        error_msg = out or "Connection failed"
        print(f"[WiFiManager] Failed to connect to {ssid}: {error_msg}")

        if was_ap:
            print("[WiFiManager] Restarting AP for retry")
            self._run(["connection", "up", AP_CON_NAME], timeout=15)

        return {"ok": False, "error": error_msg}

    # ------------------------------------------------------------------
    # Saved networks
    # ------------------------------------------------------------------

    def get_saved_networks(self):
        """Return a list of saved WiFi network names."""
        out, rc = self._run(
            ["-t", "-f", "NAME,TYPE", "connection", "show"]
        )
        networks = []
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 2:
                name = parts[0].strip()
                conn_type = parts[1].strip()
                if "wireless" in conn_type and name != AP_CON_NAME:
                    networks.append(name)
        return networks

    def forget_network(self, name):
        """Delete a saved WiFi connection profile.

        Returns dict: {"ok": bool, "error": str|None}
        """
        if not name or name == AP_CON_NAME:
            return {"ok": False, "error": "Cannot delete this network"}
        out, rc = self._run(["connection", "delete", name], timeout=10)
        if rc == 0:
            print(f"[WiFiManager] Forgot network: {name}")
            return {"ok": True, "error": None}
        return {"ok": False, "error": out or "Failed to delete network"}
