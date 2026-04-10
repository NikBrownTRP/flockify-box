"""Tests for AudioRouter — PulseAudio sink routing between Bluetooth and wired."""

import sys
import os
import pytest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock pulsectl at the module level before importing audio_router,
# since pulsectl is a Linux-only package not available on the test host.
mock_pulsectl = MagicMock()
sys.modules['pulsectl'] = mock_pulsectl


def _make_mock_sink(name, description="Sink", state=0, index=0):
    """Create a mock PulseAudio sink object."""
    sink = MagicMock()
    sink.name = name
    sink.description = description
    sink.state = state
    sink.index = index
    return sink


def _make_mock_card(name, profiles=None):
    """Create a mock PulseAudio card object."""
    card = MagicMock()
    card.name = name
    if profiles is None:
        profiles = []
    card.profile_list = profiles
    return card


def _make_mock_profile(name, description=""):
    """Create a mock PulseAudio card profile."""
    profile = MagicMock()
    profile.name = name
    profile.description = description
    return profile


def _make_mock_sink_input(index, app_name="unknown"):
    """Create a mock PulseAudio sink-input."""
    si = MagicMock()
    si.index = index
    si.proplist = {"application.name": app_name}
    return si


@pytest.fixture(autouse=True)
def _reset_pulsectl():
    """Reset the mock Pulse instance before each test."""
    mock_pulse_instance = MagicMock()
    mock_pulse_instance.sink_list.return_value = []
    mock_pulse_instance.card_list.return_value = []
    mock_pulse_instance.sink_input_list.return_value = []
    mock_pulsectl.Pulse.return_value = mock_pulse_instance
    yield mock_pulse_instance


@pytest.fixture
def audio_router(_reset_pulsectl):
    """Create a fresh AudioRouter with mocked pulse."""
    # Ensure a clean import each time
    if 'audio_router' in sys.modules:
        del sys.modules['audio_router']

    from audio_router import AudioRouter
    ar = AudioRouter()
    ar.pulse = None  # Reset so tests control pulse creation
    return ar


@pytest.fixture
def mock_pulse(_reset_pulsectl):
    """Provide the mock pulse instance for direct assertions."""
    return _reset_pulsectl


# ------------------------------------------------------------------
# get_bluetooth_sink()
# ------------------------------------------------------------------

class TestGetBluetoothSink:
    def test_finds_running_bluez_sink(self, audio_router, mock_pulse):
        bt_sink = _make_mock_sink("bluez_sink.XX_XX", "BT Speaker", state=0)
        wired_sink = _make_mock_sink("alsa_output.usb", "USB Audio", state=0)
        mock_pulse.sink_list.return_value = [wired_sink, bt_sink]

        name, desc = audio_router.get_bluetooth_sink()
        assert name == "bluez_sink.XX_XX"
        assert desc == "BT Speaker"

    def test_ignores_non_running_bluez_sink(self, audio_router, mock_pulse):
        bt_sink = _make_mock_sink("bluez_sink.XX_XX", "BT Speaker", state=2)
        mock_pulse.sink_list.return_value = [bt_sink]

        name, desc = audio_router.get_bluetooth_sink()
        assert name is None
        assert desc is None

    def test_returns_none_when_no_bluez(self, audio_router, mock_pulse):
        mock_pulse.sink_list.return_value = [
            _make_mock_sink("alsa_output.usb", "USB Audio")
        ]

        name, desc = audio_router.get_bluetooth_sink()
        assert name is None
        assert desc is None


# ------------------------------------------------------------------
# get_bluetooth_sink_any_state()
# ------------------------------------------------------------------

class TestGetBluetoothSinkAnyState:
    def test_finds_suspended_bluez_sink(self, audio_router, mock_pulse):
        bt_sink = _make_mock_sink("bluez_sink.XX_XX", "BT Speaker", state=2)
        mock_pulse.sink_list.return_value = [bt_sink]

        name, desc, state = audio_router.get_bluetooth_sink_any_state()
        assert name == "bluez_sink.XX_XX"
        assert state == 2

    def test_returns_none_triple_when_absent(self, audio_router, mock_pulse):
        mock_pulse.sink_list.return_value = []

        name, desc, state = audio_router.get_bluetooth_sink_any_state()
        assert name is None
        assert desc is None
        assert state is None


# ------------------------------------------------------------------
# get_wired_sink()
# ------------------------------------------------------------------

class TestGetWiredSink:
    def test_finds_non_bluez_sink(self, audio_router, mock_pulse):
        bt_sink = _make_mock_sink("bluez_sink.XX", "BT Speaker")
        wired = _make_mock_sink("alsa_output.usb", "USB Audio")
        mock_pulse.sink_list.return_value = [bt_sink, wired]

        name, desc = audio_router.get_wired_sink()
        assert name == "alsa_output.usb"
        assert desc == "USB Audio"

    def test_returns_none_when_only_bluez(self, audio_router, mock_pulse):
        mock_pulse.sink_list.return_value = [
            _make_mock_sink("bluez_sink.XX", "BT Speaker")
        ]

        name, desc = audio_router.get_wired_sink()
        assert name is None
        assert desc is None


# ------------------------------------------------------------------
# get_active_output()
# ------------------------------------------------------------------

class TestGetActiveOutput:
    def test_returns_bluetooth_when_bt_exists(self, mock_pulse):
        mock_pulse.sink_list.return_value = [
            _make_mock_sink("bluez_sink.XX", "BT", state=2)
        ]

        if 'audio_router' in sys.modules:
            del sys.modules['audio_router']
        from audio_router import AudioRouter
        ar = AudioRouter()
        assert ar.current_output == "bluetooth"

    def test_returns_wired_when_no_bt(self, mock_pulse):
        mock_pulse.sink_list.return_value = [
            _make_mock_sink("alsa_output.usb", "USB")
        ]

        if 'audio_router' in sys.modules:
            del sys.modules['audio_router']
        from audio_router import AudioRouter
        ar = AudioRouter()
        assert ar.current_output == "wired"


# ------------------------------------------------------------------
# set_default_sink()
# ------------------------------------------------------------------

class TestSetDefaultSink:
    def test_sets_matching_sink(self, audio_router, mock_pulse):
        target = _make_mock_sink("alsa_output.usb", "USB Audio")
        mock_pulse.sink_list.return_value = [target]

        result = audio_router.set_default_sink("alsa_output.usb")
        assert result is True
        mock_pulse.default_set.assert_called_once_with(target)

    def test_returns_false_for_unknown_sink(self, audio_router, mock_pulse):
        mock_pulse.sink_list.return_value = []

        result = audio_router.set_default_sink("nonexistent")
        assert result is False


# ------------------------------------------------------------------
# move_all_streams()
# ------------------------------------------------------------------

class TestMoveAllStreams:
    def test_moves_sink_inputs(self, audio_router, mock_pulse):
        target = _make_mock_sink("alsa_output.usb", "USB", index=5)
        mock_pulse.sink_list.return_value = [target]

        si1 = _make_mock_sink_input(10, "mpv")
        si2 = _make_mock_sink_input(11, "librespot")
        mock_pulse.sink_input_list.return_value = [si1, si2]

        result = audio_router.move_all_streams("alsa_output.usb")
        assert result is True
        assert mock_pulse.sink_input_move.call_count == 2
        mock_pulse.sink_input_move.assert_any_call(10, 5)
        mock_pulse.sink_input_move.assert_any_call(11, 5)

    def test_returns_false_when_sink_not_found(self, audio_router, mock_pulse):
        mock_pulse.sink_list.return_value = []

        result = audio_router.move_all_streams("nonexistent")
        assert result is False

    def test_returns_true_with_no_streams(self, audio_router, mock_pulse):
        target = _make_mock_sink("alsa_output.usb", "USB", index=5)
        mock_pulse.sink_list.return_value = [target]
        mock_pulse.sink_input_list.return_value = []

        result = audio_router.move_all_streams("alsa_output.usb")
        assert result is True


# ------------------------------------------------------------------
# switch_to_bluetooth()
# ------------------------------------------------------------------

class TestSwitchToBluetooth:
    @patch('audio_router.time.sleep')
    def test_full_flow(self, mock_sleep, audio_router, mock_pulse):
        bt = _make_mock_sink("bluez_sink.XX", "BT Speaker", state=2, index=3)
        mock_pulse.sink_list.return_value = [bt]
        mock_pulse.sink_input_list.return_value = []

        result = audio_router.switch_to_bluetooth()
        assert result is True
        assert audio_router.current_output == "bluetooth"

    def test_returns_false_when_no_bt(self, audio_router, mock_pulse):
        mock_pulse.sink_list.return_value = [
            _make_mock_sink("alsa_output.usb", "USB")
        ]

        result = audio_router.switch_to_bluetooth()
        assert result is False


# ------------------------------------------------------------------
# switch_to_wired()
# ------------------------------------------------------------------

class TestSwitchToWired:
    @patch('subprocess.run')
    @patch('audio_router.time.sleep')
    def test_full_flow_with_volume_enforcement(self, mock_sleep, mock_subproc, audio_router, mock_pulse):
        wired = _make_mock_sink("alsa_output.usb", "USB Audio", index=1)
        mock_pulse.sink_list.return_value = [wired]
        mock_pulse.sink_input_list.return_value = []

        result = audio_router.switch_to_wired()
        assert result is True
        assert audio_router.current_output == "wired"

        # Verify pactl 100% volume enforcement
        mock_subproc.assert_called_once_with(
            ["pactl", "set-sink-volume", "alsa_output.usb", "100%"],
            check=False,
            capture_output=True,
            timeout=3,
        )

    def test_returns_false_when_no_wired(self, audio_router, mock_pulse):
        mock_pulse.sink_list.return_value = [
            _make_mock_sink("bluez_sink.XX", "BT")
        ]

        result = audio_router.switch_to_wired()
        assert result is False


# ------------------------------------------------------------------
# set_bluetooth_a2dp_profile()
# ------------------------------------------------------------------

class TestSetBluetoothA2dpProfile:
    @patch('audio_router.time.sleep')
    def test_sets_a2dp_sink_profile(self, mock_sleep, audio_router, mock_pulse):
        a2dp_profile = _make_mock_profile(
            "a2dp-sink", "High Fidelity Playback (A2DP Sink)"
        )
        other_profile = _make_mock_profile("headset-head-unit", "HSP/HFP")
        card = _make_mock_card("bluez_card.XX", [other_profile, a2dp_profile])
        mock_pulse.card_list.return_value = [card]

        result = audio_router.set_bluetooth_a2dp_profile()
        assert result is True
        mock_pulse.card_profile_set.assert_called_once_with(card, "a2dp-sink")

    def test_returns_false_when_no_bluez_card(self, audio_router, mock_pulse):
        mock_pulse.card_list.return_value = []

        result = audio_router.set_bluetooth_a2dp_profile()
        assert result is False

    def test_returns_false_when_no_a2dp_profile(self, audio_router, mock_pulse):
        hfp = _make_mock_profile("headset-head-unit", "HSP/HFP")
        card = _make_mock_card("bluez_card.XX", [hfp])
        mock_pulse.card_list.return_value = [card]

        result = audio_router.set_bluetooth_a2dp_profile()
        assert result is False


# ------------------------------------------------------------------
# set_application_sink_input_volume()
# ------------------------------------------------------------------

class TestSetApplicationSinkInputVolume:
    @patch('subprocess.run')
    def test_finds_and_sets_volume(self, mock_subproc, audio_router, mock_pulse):
        si = _make_mock_sink_input(42, "librespot")
        mock_pulse.sink_input_list.return_value = [si]

        result = audio_router.set_application_sink_input_volume("librespot", 250)
        assert result is True
        mock_subproc.assert_called_once_with(
            ["pactl", "set-sink-input-volume", "42", "250%"],
            check=True,
            capture_output=True,
            timeout=3,
        )

    def test_returns_false_when_no_match(self, audio_router, mock_pulse):
        si = _make_mock_sink_input(42, "mpv")
        mock_pulse.sink_input_list.return_value = [si]

        result = audio_router.set_application_sink_input_volume("librespot", 250)
        assert result is False

    @patch('subprocess.run')
    def test_case_insensitive_match(self, mock_subproc, audio_router, mock_pulse):
        si = _make_mock_sink_input(7, "Librespot")
        mock_pulse.sink_input_list.return_value = [si]

        result = audio_router.set_application_sink_input_volume("LIBRESPOT", 100)
        assert result is True

    @patch('subprocess.run')
    def test_returns_false_when_pactl_fails(self, mock_subproc, audio_router, mock_pulse):
        si = _make_mock_sink_input(42, "librespot")
        mock_pulse.sink_input_list.return_value = [si]
        mock_subproc.side_effect = Exception("pactl error")

        result = audio_router.set_application_sink_input_volume("librespot", 250)
        assert result is False
