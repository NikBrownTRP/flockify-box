import mpv
import pulsectl
import time
from threading import Thread, Lock

class WebRadioPlayer:
    def __init__(self):
        # Initialize mpv WITHOUT setting audio device yet
        # We'll set it when we play
        self.player = None
        self.pulse = None
        self.pulse_lock = Lock()
        self.current_station = None
        self.monitoring = False
        
        # Try to set correct Bluetooth profile on init
        self.set_bluetooth_a2dp_profile()
    
    def _init_player(self, audio_device=None):
        """Initialize or reinitialize the player with specific audio device"""
        if self.player:
            try:
                self.player.terminate()
            except:
                pass
        
        if audio_device:
            self.player = mpv.MPV(audio_device=audio_device)
            print(f"Initialized MPV with audio device: {audio_device}")
        else:
            self.player = mpv.MPV()
            print("Initialized MPV with default audio")
        
    def _get_pulse(self):
        """Get a pulse connection (creates new one if needed)"""
        if self.pulse is None:
            self.pulse = pulsectl.Pulse('webradio-controller')
        return self.pulse
    
    def _close_pulse(self):
        """Close pulse connection to avoid blocking"""
        if self.pulse is not None:
            try:
                self.pulse.close()
            except:
                pass
            self.pulse = None
    
    def play_station(self, url, audio_device=None):
        """Play a web radio station"""
        try:
            # Close pulse connection before playing to avoid blocking
            self._close_pulse()
            
            # Initialize player with the correct audio device
            self._init_player(audio_device)
            
            self.player.play(url)
            self.current_station = url
            print(f"Playing: {url}")
        except Exception as e:
            print(f"Error playing station: {e}")
    
    def stop(self):
        """Stop playback"""
        if self.player:
            self.player.stop()
        self.current_station = None
        print("Playback stopped")

    def set_volume(self, volume):
        """Set volume (0-100)"""
        if self.player:
            self.player.volume = volume
    
    def set_bluetooth_a2dp_profile(self):
        """Ensure Bluetooth uses A2DP profile for audio playback"""
        try:
            with self.pulse_lock:
                pulse = self._get_pulse()
                cards = pulse.card_list()
                for card in cards:
                    if 'bluez' in card.name.lower():
                        # Look for a2dp profile
                        for profile in card.profile_list:
                            if 'a2dp' in profile.name.lower() and 'sink' in profile.name.lower():
                                try:
                                    pulse.card_profile_set(card, profile.name)
                                    print(f"✓ Set Bluetooth to A2DP profile: {profile.description}")
                                    time.sleep(0.5)
                                    return True
                                except Exception as e:
                                    print(f"Could not set A2DP profile: {e}")
        except Exception as e:
            print(f"Error checking Bluetooth profile: {e}")
        finally:
            self._close_pulse()
        return False
    
    def get_bluetooth_sink(self):
        """Find connected Bluetooth audio sink (must be RUNNING, not SUSPENDED)"""
        with self.pulse_lock:
            try:
                pulse = self._get_pulse()
                sinks = pulse.sink_list()
                for sink in sinks:
                    # Check if it's a Bluetooth device and actually RUNNING (state 0)
                    if 'bluez' in sink.name.lower() and sink.state == 0:
                        return sink.name, sink.description
            finally:
                self._close_pulse()
        return None, None
    
    def get_bluetooth_sink_any_state(self):
        """Find any Bluetooth sink regardless of state"""
        with self.pulse_lock:
            try:
                pulse = self._get_pulse()
                sinks = pulse.sink_list()
                for sink in sinks:
                    if 'bluez' in sink.name.lower():
                        return sink.name, sink.description, sink.state
            finally:
                self._close_pulse()
        return None, None, None
    
    def set_default_sink(self, sink_name):
        """Set default audio sink"""
        with self.pulse_lock:
            try:
                pulse = self._get_pulse()
                # Find the sink
                sinks = pulse.sink_list()
                for sink in sinks:
                    if sink.name == sink_name:
                        pulse.default_set(sink)
                        print(f"Set default sink to: {sink.description}")
                        return True
            except Exception as e:
                print(f"Error setting default sink: {e}")
            finally:
                self._close_pulse()
        return False
    
    def start_radio(self, url, volume=50):
        """Convenient method to start radio with Bluetooth auto-detection"""
        # Find Bluetooth device
        bt_name, bt_desc, bt_state = self.get_bluetooth_sink_any_state()
        
        if bt_name:
            print(f"Found Bluetooth: {bt_desc}")
            # Set as default
            self.set_default_sink(bt_name)
            time.sleep(0.5)
            
            # Play with explicit Bluetooth device
            self.play_station(url, audio_device=f'pulse/{bt_name}')
        else:
            print("No Bluetooth found, using default audio")
            self.play_station(url)
        
        self.set_volume(volume)
        return bt_name is not None

    def get_all_sinks(self):
        """Get all available audio sinks"""
        with self.pulse_lock:
            try:
                pulse = self._get_pulse()
                sinks = pulse.sink_list()
                result = []
                for sink in sinks:
                    result.append({
                        'name': sink.name,
                        'description': sink.description,
                        'state': sink.state
                    })
                return result
            finally:
                self._close_pulse()
        return []

    def ensure_fallback_audio_exists(self):
        """Make sure there's at least one non-Bluetooth audio output available"""
        import subprocess
        
        sinks = self.get_all_sinks()
        non_bt_sinks = [s for s in sinks if 'bluez' not in s['name'].lower()]
        
        if not non_bt_sinks:
            print("\n⚠️  No fallback audio output found. Loading HDMI audio...")
            try:
                # Try to load HDMI audio
                subprocess.run(['pactl', 'load-module', 'module-alsa-sink', 'device=hw:0,0'],
                             capture_output=True, timeout=5)
                print("✓ Loaded HDMI audio output")
                time.sleep(1)
                return True
            except Exception as e:
                print(f"Could not load HDMI audio: {e}")
                return False
        return True

    def switch_audio_output(self):
        """Switch to Bluetooth if available, otherwise use fallback"""
        # Check for Bluetooth (any state)
        bt_name, bt_desc, bt_state = self.get_bluetooth_sink_any_state()
        
        if bt_name:
            print(f"\nFound Bluetooth device: {bt_desc}")
            state_str = "RUNNING" if bt_state == 0 else "SUSPENDED" if bt_state == 2 else f"STATE_{bt_state}"
            print(f"  Current state: {state_str}")
            
            if bt_state == 0:
                print(f"✓ Bluetooth already active, using it")
                return bt_name
            else:
                print(f"  Setting as default to prepare for playback...")
                self.set_default_sink(bt_name)
                return bt_name
        else:
            print("\nNo Bluetooth device found")
            # Find any available sink
            sinks = self.get_all_sinks()
            if sinks:
                # Use first non-Bluetooth sink
                for sink in sinks:
                    if 'bluez' not in sink['name'].lower():
                        print(f"Using fallback: {sink['description']}")
                        self.set_default_sink(sink['name'])
                        return sink['name']
                # If only Bluetooth available, use it anyway
                print(f"Using: {sinks[0]['description']}")
                return sinks[0]['name']
        
        return None
    
    def monitor_audio_devices(self, interval=5):
        """Monitor for Bluetooth connection changes and auto-switch"""
        self.monitoring = True
        last_bt_state = self.get_bluetooth_sink()[0] is not None
        
        while self.monitoring:
            time.sleep(interval)
            bt_name, bt_desc = self.get_bluetooth_sink()
            current_bt_state = bt_name is not None
            
            # If Bluetooth state changed, switch audio
            if current_bt_state != last_bt_state:
                print(f"\n{'='*60}")
                print("Bluetooth connection state changed!")
                print(f"{'='*60}")
                
                if current_bt_state:
                    print(f"✓ Bluetooth connected: {bt_desc}")
                    # Switch to Bluetooth
                    if self.current_station:
                        print("  Restarting playback on Bluetooth...")
                        url = self.current_station
                        self.stop()
                        time.sleep(0.5)
                        self.play_station(url, audio_device=f'pulse/{bt_name}')
                else:
                    print("✗ Bluetooth disconnected")
                    print("  Switching to fallback audio...")
                    if self.current_station:
                        url = self.current_station
                        self.stop()
                        time.sleep(0.5)
                        sink_name = self.switch_audio_output()
                        if sink_name:
                            self.play_station(url, audio_device=f'pulse/{sink_name}')
                        else:
                            self.play_station(url)
                
                last_bt_state = current_bt_state
    
    def start_monitoring(self, interval=5):
        """Start monitoring in background thread"""
        monitor_thread = Thread(target=self.monitor_audio_devices, args=(interval,))
        monitor_thread.daemon = True
        monitor_thread.start()
        print(f"\n✓ Started monitoring Bluetooth (checking every {interval}s)")
    
    def stop_monitoring(self):
        """Stop monitoring"""
        self.monitoring = False
    
    def cleanup(self):
        """Cleanup resources"""
        self.stop_monitoring()
        if self.player:
            try:
                self.player.terminate()
            except:
                pass
        self._close_pulse()

"""
SIMPLE USAGE EXAMPLE (in your own code):

Save this file as webradio_lib.py, then in your code:

from webradio_lib import WebRadioPlayer
import time

# Create radio player
radio = WebRadioPlayer()

# Start playing (handles Bluetooth automatically)
radio.start_radio("http://ice1.somafm.com/groovesalad-128-mp3", volume=50)

# Start monitoring for Bluetooth changes (optional)
radio.start_monitoring(interval=5)

# Keep running
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    radio.cleanup()
"""

"""
ADVANCED USAGE:

# Manual control
radio2 = WebRadioPlayer()

# Find and use Bluetooth manually
bt_name, bt_desc, _ = radio2.get_bluetooth_sink_any_state()
if bt_name:
    radio2.set_default_sink(bt_name)
    radio2.play_station("http://ice1.somafm.com/groovesalad-128-mp3", 
                        audio_device=f'pulse/{bt_name}')
else:
    radio2.play_station("http://ice1.somafm.com/groovesalad-128-mp3")

radio2.set_volume(75)

# Change stations
radio2.stop()
radio2.play_station("http://other-url")

# Cleanup
radio2.cleanup()
"""


# =============================================================================
# MAIN DEMO (runs when script is executed directly)
# =============================================================================
if __name__ == "__main__":
    radio = WebRadioPlayer()
    
    print("=" * 60)
    print("Web Radio Player with Auto Audio Switching")
    print("=" * 60)
    
    # Find Bluetooth device
    bt_name, bt_desc, bt_state = radio.get_bluetooth_sink_any_state()
    
    if bt_name:
        print(f"\n✓ Bluetooth device found: {bt_desc}")
        # Set as default
        radio.set_default_sink(bt_name)
        print("  Set as default audio output")
        time.sleep(1)
        
        # Play with explicit Bluetooth device (like command line that works)
        print("\nStarting playback on Bluetooth...")
        radio.play_station(
            "http://ice1.somafm.com/groovesalad-128-mp3",
            audio_device=f'pulse/{bt_name}'
        )
    else:
        print("\nNo Bluetooth found, using default audio...")
        radio.play_station("http://ice1.somafm.com/groovesalad-128-mp3")
    
    radio.set_volume(50)
    
    # Give it a moment to start
    time.sleep(3)
    
    # Check if Bluetooth activated
    active_bt_name, active_bt_desc = radio.get_bluetooth_sink()
    if active_bt_name:
        print(f"\n✓✓✓ SUCCESS! Audio playing through: {active_bt_desc} ✓✓✓")
    else:
        print("\n🎵 Audio should be playing...")
        print("   Can you hear it in your headphones?")
    
    # List all available sinks for debugging
    print("\n📻 Available audio outputs:")
    all_sinks = radio.get_all_sinks()
    for sink in all_sinks:
        state = "RUNNING ✓" if sink['state'] == 0 else "SUSPENDED" if sink['state'] == 2 else f"STATE_{sink['state']}"
        print(f"   - {sink['description']}: {state}")
    
    # Start monitoring for changes
    radio.start_monitoring(interval=3)
    
    print("\n" + "=" * 60)
    print("Radio is playing. Press Ctrl+C to stop.")
    print("Turn Bluetooth headphones on/off to test auto-switching.")
    print("=" * 60 + "\n")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        radio.cleanup()
