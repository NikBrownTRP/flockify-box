"""
BluetoothManager — Wraps bluetoothctl for Bluetooth device management.

Provides scan, pair, connect, disconnect, and forget operations
accessible from the Flask web UI.
"""

import subprocess
import re
import time
from threading import Thread, Lock


class BluetoothManager:
    def __init__(self):
        self.scan_lock = Lock()
        self._scan_results = []
        self._scanning = False

    def _run(self, args, timeout=10):
        """Run a bluetoothctl command and return stdout."""
        try:
            result = subprocess.run(
                ['bluetoothctl'] + args,
                capture_output=True, text=True, timeout=timeout
            )
            return result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            print(f"[bluetooth] Command timed out: bluetoothctl {' '.join(args)}")
            return ''
        except Exception as e:
            print(f"[bluetooth] Error running bluetoothctl: {e}")
            return ''

    def get_paired_devices(self):
        """List all paired devices with connection status."""
        output = self._run(['devices', 'Paired'])
        # Fallback: if 'devices Paired' not supported, use 'paired-devices'
        if not output.strip():
            output = self._run(['paired-devices'])
        devices = self._parse_devices(output)
        # Enrich with connection status
        info_output = self._run(['info'], timeout=5)
        connected_addr = None
        match = re.search(r'Device\s+([0-9A-F:]{17})', info_output)
        if match and 'Connected: yes' in info_output:
            connected_addr = match.group(1)
        for dev in devices:
            dev['connected'] = (dev['address'] == connected_addr)
            dev['paired'] = True
        return devices

    def get_connected_device(self):
        """Return the currently connected device, or None."""
        paired = self.get_paired_devices()
        for dev in paired:
            if dev.get('connected'):
                return dev
        return None

    def scan(self, duration=8):
        """Scan for nearby Bluetooth devices. Blocks for `duration` seconds."""
        with self.scan_lock:
            self._scanning = True
            # Power on and set agent
            self._run(['power', 'on'], timeout=5)
            self._run(['agent', 'on'], timeout=5)
            self._run(['default-agent'], timeout=5)
            # Run scan with timeout
            output = self._run(['--timeout', str(duration), 'scan', 'on'],
                               timeout=duration + 5)
            self._scanning = False
        # Now get all discovered devices
        all_output = self._run(['devices'])
        devices = self._parse_devices(all_output)
        # Mark which are already paired
        paired = {d['address'] for d in self.get_paired_devices()}
        for dev in devices:
            dev['paired'] = dev['address'] in paired
        self._scan_results = devices
        return devices

    def pair(self, address):
        """Pair, trust, and connect to a device."""
        address = self._sanitize_address(address)
        if not address:
            return {'ok': False, 'error': 'Invalid Bluetooth address'}
        # Ensure agent is ready
        self._run(['power', 'on'], timeout=5)
        self._run(['agent', 'on'], timeout=5)
        self._run(['default-agent'], timeout=5)
        # Pair
        output = self._run(['pair', address], timeout=15)
        if 'Failed' in output and 'Already Exists' not in output:
            return {'ok': False, 'error': f'Pairing failed: {output.strip()}'}
        # Trust (so it auto-connects in future)
        self._run(['trust', address], timeout=5)
        # Connect
        output = self._run(['connect', address], timeout=15)
        if 'Failed' in output:
            return {'ok': False, 'error': f'Connection failed: {output.strip()}'}
        return {'ok': True}

    def connect(self, address):
        """Connect to an already-paired device."""
        address = self._sanitize_address(address)
        if not address:
            return {'ok': False, 'error': 'Invalid Bluetooth address'}
        output = self._run(['connect', address], timeout=15)
        if 'Failed' in output:
            return {'ok': False, 'error': f'Connection failed: {output.strip()}'}
        return {'ok': True}

    def disconnect(self, address):
        """Disconnect a device."""
        address = self._sanitize_address(address)
        if not address:
            return {'ok': False, 'error': 'Invalid Bluetooth address'}
        output = self._run(['disconnect', address], timeout=10)
        if 'Failed' in output:
            return {'ok': False, 'error': f'Disconnect failed: {output.strip()}'}
        return {'ok': True}

    def forget(self, address):
        """Remove/forget a paired device."""
        address = self._sanitize_address(address)
        if not address:
            return {'ok': False, 'error': 'Invalid Bluetooth address'}
        output = self._run(['remove', address], timeout=10)
        if 'not available' in output:
            return {'ok': False, 'error': f'Device not found: {output.strip()}'}
        return {'ok': True}

    def _parse_devices(self, output):
        """Parse bluetoothctl device list output into structured dicts."""
        devices = []
        seen = set()
        for line in output.splitlines():
            match = re.match(r'.*Device\s+([0-9A-Fa-f:]{17})\s+(.+)', line)
            if match:
                addr = match.group(1).upper()
                name = match.group(2).strip()
                if addr not in seen and name != addr:
                    seen.add(addr)
                    devices.append({
                        'address': addr,
                        'name': name,
                        'paired': False,
                        'connected': False,
                    })
        return devices

    def _sanitize_address(self, address):
        """Validate and sanitize a Bluetooth MAC address to prevent injection."""
        if not address:
            return None
        address = address.strip().upper()
        if re.match(r'^[0-9A-F]{2}(:[0-9A-F]{2}){5}$', address):
            return address
        return None
