"""
AudioRouter — PulseAudio sink manager for routing audio between
Bluetooth and wired (USB audio adapter / 3.5mm jack) outputs.

Extracted from webradio_player.py so it can be shared by both
webradio mode (mpv) and Spotify mode (Raspotify).
"""

import pulsectl
import time
from threading import Thread, Lock


class AudioRouter:
    def __init__(self):
        self.pulse = None
        self.pulse_lock = Lock()
        self.monitoring = False
        self._monitor_thread = None
        self._on_output_change = None  # callback for output changes
        # Detect current output immediately so status is correct before
        # the monitor thread runs its first poll.
        try:
            self.current_output = self.get_active_output()
        except Exception:
            self.current_output = "wired"

    # ------------------------------------------------------------------
    # Pulse connection helpers (lazy create / close after use)
    # ------------------------------------------------------------------

    def _get_pulse(self):
        """Get a pulse connection (creates new one if needed)."""
        if self.pulse is None:
            self.pulse = pulsectl.Pulse('audio-router')
        return self.pulse

    def _close_pulse(self):
        """Close pulse connection to avoid blocking."""
        if self.pulse is not None:
            try:
                self.pulse.close()
            except Exception:
                pass
            self.pulse = None

    # ------------------------------------------------------------------
    # Sink discovery
    # ------------------------------------------------------------------

    def get_bluetooth_sink(self):
        """Find a Bluetooth A2DP sink that is RUNNING (state == 0).

        Returns (name, description) or (None, None).
        """
        with self.pulse_lock:
            try:
                pulse = self._get_pulse()
                for sink in pulse.sink_list():
                    if 'bluez' in sink.name.lower() and sink.state == 0:
                        return sink.name, sink.description
            except Exception as e:
                print(f"Error finding Bluetooth sink: {e}")
            finally:
                self._close_pulse()
        return None, None

    def get_bluetooth_sink_any_state(self):
        """Find any Bluetooth sink regardless of state.

        Returns (name, description, state) or (None, None, None).
        """
        with self.pulse_lock:
            try:
                pulse = self._get_pulse()
                for sink in pulse.sink_list():
                    if 'bluez' in sink.name.lower():
                        return sink.name, sink.description, sink.state
            except Exception as e:
                print(f"Error finding Bluetooth sink: {e}")
            finally:
                self._close_pulse()
        return None, None, None

    def get_wired_sink(self):
        """Find a non-Bluetooth sink (USB audio adapter, HDMI, etc.).

        Returns (name, description) or (None, None).
        """
        with self.pulse_lock:
            try:
                pulse = self._get_pulse()
                for sink in pulse.sink_list():
                    if 'bluez' not in sink.name.lower():
                        return sink.name, sink.description
            except Exception as e:
                print(f"Error finding wired sink: {e}")
            finally:
                self._close_pulse()
        return None, None

    def get_active_output(self):
        """Return 'bluetooth' if a BT sink exists in any state, else 'wired'.

        A Bluetooth headphone that isn't currently playing audio will be in
        SUSPENDED state (state == 2), which is normal. We only care whether
        the sink EXISTS, not whether audio is flowing through it right now.
        """
        bt_name, _, _ = self.get_bluetooth_sink_any_state()
        return "bluetooth" if bt_name else "wired"

    def get_all_sinks(self):
        """List all sinks with name / description / state."""
        with self.pulse_lock:
            try:
                pulse = self._get_pulse()
                return [
                    {
                        'name': sink.name,
                        'description': sink.description,
                        'state': sink.state,
                    }
                    for sink in pulse.sink_list()
                ]
            except Exception as e:
                print(f"Error listing sinks: {e}")
            finally:
                self._close_pulse()
        return []

    # ------------------------------------------------------------------
    # Sink control
    # ------------------------------------------------------------------

    def set_default_sink(self, sink_name):
        """Set PulseAudio default sink by name. Returns True on success."""
        with self.pulse_lock:
            try:
                pulse = self._get_pulse()
                for sink in pulse.sink_list():
                    if sink.name == sink_name:
                        pulse.default_set(sink)
                        print(f"Set default sink to: {sink.description}")
                        return True
            except Exception as e:
                print(f"Error setting default sink: {e}")
            finally:
                self._close_pulse()
        return False

    def move_all_streams(self, sink_name):
        """Move all active PulseAudio sink-inputs to *sink_name*.

        This is the key to seamless switching — currently playing audio
        is moved without restarting the player.
        """
        with self.pulse_lock:
            try:
                pulse = self._get_pulse()
                # Resolve the target sink index
                target_index = None
                for sink in pulse.sink_list():
                    if sink.name == sink_name:
                        target_index = sink.index
                        break
                if target_index is None:
                    print(f"Sink not found: {sink_name}")
                    return False

                moved = 0
                for si in pulse.sink_input_list():
                    try:
                        pulse.sink_input_move(si.index, target_index)
                        moved += 1
                    except Exception as e:
                        print(f"Could not move stream {si.index}: {e}")

                if moved:
                    print(f"Moved {moved} stream(s) to sink index {target_index}")
                return True
            except Exception as e:
                print(f"Error moving streams: {e}")
            finally:
                self._close_pulse()
        return False

    # ------------------------------------------------------------------
    # High-level switching
    # ------------------------------------------------------------------

    def switch_to_bluetooth(self):
        """Find BT sink, set as default, move streams. Returns True/False."""
        bt_name, bt_desc, bt_state = self.get_bluetooth_sink_any_state()
        if bt_name is None:
            print("No Bluetooth sink found")
            return False

        print(f"Switching to Bluetooth: {bt_desc}")
        self.set_default_sink(bt_name)
        time.sleep(0.3)
        self.move_all_streams(bt_name)
        self.current_output = "bluetooth"
        return True

    def switch_to_wired(self):
        """Find wired sink, set as default, move streams. Returns True/False."""
        wired_name, wired_desc = self.get_wired_sink()
        if wired_name is None:
            print("No wired sink found")
            return False

        print(f"Switching to wired: {wired_desc}")
        self.set_default_sink(wired_name)
        time.sleep(0.3)
        self.move_all_streams(wired_name)
        self.current_output = "wired"
        return True

    # ------------------------------------------------------------------
    # Bluetooth profile helper
    # ------------------------------------------------------------------

    def set_bluetooth_a2dp_profile(self):
        """Ensure Bluetooth card uses A2DP sink profile for audio playback."""
        with self.pulse_lock:
            try:
                pulse = self._get_pulse()
                for card in pulse.card_list():
                    if 'bluez' in card.name.lower():
                        for profile in card.profile_list:
                            if 'a2dp' in profile.name.lower() and 'sink' in profile.name.lower():
                                try:
                                    pulse.card_profile_set(card, profile.name)
                                    print(f"Set Bluetooth to A2DP profile: {profile.description}")
                                    time.sleep(0.5)
                                    return True
                                except Exception as e:
                                    print(f"Could not set A2DP profile: {e}")
            except Exception as e:
                print(f"Error checking Bluetooth profile: {e}")
            finally:
                self._close_pulse()
        return False

    # ------------------------------------------------------------------
    # Background monitoring
    # ------------------------------------------------------------------

    def monitor(self, callback, interval=10):
        """Polling loop — runs in a background thread.

        Checks every *interval* seconds whether the audio output has
        changed (Bluetooth connected / disconnected).  Calls
        ``callback("bluetooth")`` or ``callback("wired")`` on change.
        """
        last_output = self.get_active_output()
        self.current_output = last_output

        while self.monitoring:
            time.sleep(interval)
            if not self.monitoring:
                break

            current = self.get_active_output()

            if current != last_output:
                print(f"Audio output changed: {last_output} -> {current}")

                if current == "bluetooth":
                    self.set_bluetooth_a2dp_profile()
                    self.switch_to_bluetooth()
                else:
                    self.switch_to_wired()

                self.current_output = current
                last_output = current

                try:
                    callback(current)
                except Exception as e:
                    print(f"Output-change callback error: {e}")

    def start_monitoring(self, callback, interval=10):
        """Start the monitor thread."""
        if self.monitoring:
            return
        self.monitoring = True
        self._on_output_change = callback
        self._monitor_thread = Thread(
            target=self.monitor, args=(callback, interval), daemon=True
        )
        self._monitor_thread.start()
        print(f"Started audio output monitoring (every {interval}s)")

    def stop_monitoring(self):
        """Stop the monitor thread."""
        self.monitoring = False
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=10)
            self._monitor_thread = None
        print("Stopped audio output monitoring")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup(self):
        """Stop monitoring and close the pulse connection."""
        self.stop_monitoring()
        self._close_pulse()
