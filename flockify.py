#!/usr/bin/env python3
"""Flockify Box — Raspberry Pi Music Player"""

import sys
import os
import signal
import argparse
import threading

# Add project root to path for lib imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_manager import ConfigManager
from audio_router import AudioRouter
from display_manager import DisplayManager
from spotify_manager import SpotifyManager
from state_machine import StateMachine
from bluetooth_manager import BluetoothManager
from wifi_manager import WiFiManager
from time_scheduler import TimeScheduler
from idle_dimmer import IdleDimmer
from lib.webradio_player import WebRadioPlayer
from web.app import app, init_app

# Global references for shutdown handler
button_controller = None
state_machine = None
audio_router = None
webradio_player = None
display_manager = None
time_scheduler = None
idle_dimmer = None
_shutdown_done = False


def shutdown(signum, frame):
    """Gracefully shut down all subsystems.

    Idempotent: sys.exit(0) at the bottom raises SystemExit, which the
    main loop's except block also catches and re-calls shutdown() — the
    guard flag below prevents the second run from racing against the
    first and hitting "unknown handle" errors on the already-closed
    lgpio chip (which was corrupting the display clear sequence and
    leaving the old image stuck on the panel after poweroff).
    """
    global _shutdown_done
    if _shutdown_done:
        return
    _shutdown_done = True
    print("\nShutting down Flockify Box...")
    if idle_dimmer is not None:
        try:
            idle_dimmer.stop()
        except Exception as e:
            print(f"Error stopping idle dimmer: {e}")
    if time_scheduler is not None:
        try:
            time_scheduler.stop()
        except Exception as e:
            print(f"Error stopping scheduler: {e}")
    if button_controller is not None:
        try:
            button_controller.stop()
        except Exception as e:
            print(f"Error stopping buttons: {e}")
    if state_machine is not None:
        try:
            state_machine._save_state()
        except Exception as e:
            print(f"Error saving state: {e}")
    if audio_router is not None:
        try:
            audio_router.cleanup()
        except Exception as e:
            print(f"Error cleaning up audio router: {e}")
    if webradio_player is not None:
        try:
            webradio_player.cleanup()
        except Exception as e:
            print(f"Error cleaning up webradio player: {e}")
    if display_manager is not None:
        try:
            display_manager.cleanup()
        except Exception as e:
            print(f"Error cleaning up display: {e}")
    sys.exit(0)


def main():
    global button_controller, state_machine, audio_router, webradio_player, display_manager, time_scheduler, idle_dimmer

    # ------------------------------------------------------------------
    # 1. Parse args
    # ------------------------------------------------------------------
    parser = argparse.ArgumentParser(description="Flockify Box — Raspberry Pi Music Player")
    parser.add_argument(
        "--no-hardware",
        action="store_true",
        help="Run without GPIO/SPI hardware (development mode)",
    )
    args = parser.parse_args()

    hardware_mode = not args.no_hardware

    # ------------------------------------------------------------------
    # 2. Load config
    # ------------------------------------------------------------------
    try:
        config_manager = ConfigManager()
        print("[flockify] Configuration loaded")
    except Exception as e:
        print(f"[flockify] FATAL: Failed to load configuration: {e}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 3. Init AudioRouter
    # ------------------------------------------------------------------
    try:
        audio_router = AudioRouter()
        audio_router.set_bluetooth_a2dp_profile()
        print("[flockify] Audio router initialized")
    except Exception as e:
        print(f"[flockify] FATAL: Failed to initialize audio router: {e}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 4. Init Display
    # ------------------------------------------------------------------
    try:
        if hardware_mode:
            from lib.spi_display_lib import SPIDisplay
            spi_display = SPIDisplay()
            spi_display.init()
            display_manager = DisplayManager(spi_display)
        else:
            display_manager = DisplayManager(None)
            print("[flockify] Running without hardware display")

        # Peek the schedule BEFORE picking the splash so we don't flash a
        # bright boot image in a dark bedroom. The full TimeScheduler isn't
        # constructed yet (it needs state_machine), so we read the same
        # config directly and compute the period with a tiny helper.
        try:
            from datetime import datetime as _dt
            _sched = (config_manager.get("schedule") or {})
            _period = "day"
            if _sched.get("enabled", False):
                _n = _dt.now()
                _mins = _n.hour * 60 + _n.minute

                def _hhmm(s, d):
                    try:
                        h, m = s.split(":")
                        return int(h) * 60 + int(m)
                    except Exception:
                        return d

                def _in(w, s, e):
                    if s == e:
                        return False
                    return (s <= w < e) if s < e else (w >= s or w < e)

                _ns = _hhmm(_sched.get("night_start", "20:00"), 20 * 60)
                _ne = _hhmm(_sched.get("night_end", "06:00"), 6 * 60)
                if _in(_mins, _ns, _ne):
                    _period = "night"
                else:
                    _bs = _hhmm(_sched.get("bedtime_start", "19:00"), 19 * 60)
                    _be = _hhmm(_sched.get("bedtime_end", "20:00"), 20 * 60)
                    _ws = _hhmm(_sched.get("wakeup_start", "06:00"), 6 * 60)
                    _we = _hhmm(_sched.get("wakeup_end", "07:00"), 7 * 60)
                    if _in(_mins, _bs, _be) or _in(_mins, _ws, _we):
                        _period = "quiet"
        except Exception:
            _period = "day"

        # Pick splash image + backlight per period. During night we show the
        # sleep tiger at 5% so the display is dim from the very first frame
        # flockify.py draws — no 20-second bright window between the boot
        # splash and the scheduler applying its settings.
        images_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")
        if _period == "night":
            splash_path = os.path.join(images_dir, "sleep_tiger.png")
            _initial_backlight = _sched.get("night_backlight", 5)
        elif _period == "quiet":
            splash_path = os.path.join(images_dir, "boot_tiger.png")
            _initial_backlight = _sched.get("quiet_backlight", 40)
        else:
            splash_path = os.path.join(images_dir, "boot_tiger.png")
            _initial_backlight = config_manager.get("display", {}).get("backlight", 80)

        if not os.path.isfile(splash_path):
            splash_path = os.path.join(images_dir, "radino.png")

        if hardware_mode and spi_display is not None:
            # Drop to the target backlight BEFORE pushing any frame — otherwise
            # the SPI init leaves PWM at 100% and the first frame flashes full
            # brightness for a few ms.
            try:
                spi_display.set_backlight(_initial_backlight)
            except Exception:
                pass
        display_manager.show_splash(splash_path)
        print(f"[flockify] Display initialized (period={_period}, backlight={_initial_backlight}%)")
    except Exception as e:
        print(f"[flockify] WARNING: Display init failed, continuing without display: {e}")
        display_manager = DisplayManager(None)

    # ------------------------------------------------------------------
    # 5. Init WebRadioPlayer
    # ------------------------------------------------------------------
    try:
        webradio_player = WebRadioPlayer()
        print("[flockify] Web radio player initialized")
    except Exception as e:
        print(f"[flockify] FATAL: Failed to initialize web radio player: {e}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 6. Init SpotifyManager
    # ------------------------------------------------------------------
    try:
        spotify_manager = SpotifyManager(config_manager)
        if not spotify_manager.is_configured():
            print("[flockify] WARNING: Spotify not configured — use the web UI to set up credentials")
        else:
            print("[flockify] Spotify manager initialized")
    except Exception as e:
        print(f"[flockify] WARNING: Spotify init failed, continuing without Spotify: {e}")
        spotify_manager = SpotifyManager.__new__(SpotifyManager)
        spotify_manager.config = config_manager
        spotify_manager.sp = None
        spotify_manager._device_id = None
        spotify_manager._rate_limit_until = 0.0
        spotify_manager._stuck_failures = []
        spotify_manager._waiting_for_pairing = False
        spotify_manager.on_pairing_required = None

    # Wire the auto-escalation callback so the SPI display shows a
    # "please re-pair Spotify from your phone" prompt the moment
    # spotify_manager.reset_pairing() runs (either from the web UI
    # button or from auto-escalation in play_playlist).
    def _on_pairing_required():
        try:
            if display_manager is not None:
                # If a dedicated pairing-prompt image exists use it;
                # otherwise fall back to the existing sleep tiger with
                # a console note. We re-use show_splash to get the
                # letterboxing + backlight behaviour.
                import os
                candidate = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "images",
                    "spotify_repair.png",
                )
                if os.path.isfile(candidate):
                    display_manager.show_splash(candidate)
                    print("[flockify] Showed Spotify re-pair prompt on display")
        except Exception as e:
            print(f"[flockify] Could not show re-pair prompt: {e}")

    try:
        spotify_manager.on_pairing_required = _on_pairing_required
    except Exception:
        pass

    # ------------------------------------------------------------------
    # 7. Init StateMachine
    # ------------------------------------------------------------------
    try:
        state_machine = StateMachine(
            config_manager, spotify_manager, webradio_player,
            display_manager, audio_router,
        )
        print("[flockify] State machine initialized")
    except Exception as e:
        print(f"[flockify] FATAL: Failed to initialize state machine: {e}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 8. Init ButtonController (hardware only)
    # ------------------------------------------------------------------
    if hardware_mode:
        try:
            from button_controller import ButtonController
            button_controller = ButtonController(state_machine)
            button_controller.start()
            print("[flockify] Button controller started")
        except Exception as e:
            print(f"[flockify] WARNING: Failed to initialize buttons: {e}")
            button_controller = None

    # ------------------------------------------------------------------
    # 8b. Init TimeScheduler
    # ------------------------------------------------------------------
    try:
        time_scheduler = TimeScheduler(config_manager, state_machine, display_manager)
        state_machine.time_scheduler = time_scheduler
        print("[flockify] Time scheduler initialized")
    except Exception as e:
        print(f"[flockify] WARNING: Time scheduler init failed: {e}")
        time_scheduler = None

    # ------------------------------------------------------------------
    # 8b2. Init IdleDimmer (depends on display_manager + time_scheduler + config)
    # ------------------------------------------------------------------
    try:
        idle_dimmer = IdleDimmer(display_manager, time_scheduler, config_manager)
        state_machine.idle_dimmer = idle_dimmer
        print("[flockify] Idle dimmer initialized")
    except Exception as e:
        print(f"[flockify] WARNING: Idle dimmer init failed: {e}")
        idle_dimmer = None

    # ------------------------------------------------------------------
    # 8c. Init BluetoothManager
    # ------------------------------------------------------------------
    try:
        bluetooth_mgr = BluetoothManager()
        print("[flockify] Bluetooth manager initialized")
    except Exception as e:
        print(f"[flockify] WARNING: Bluetooth manager init failed: {e}")
        bluetooth_mgr = None

    # ------------------------------------------------------------------
    # 8d. Init WiFiManager
    # ------------------------------------------------------------------
    try:
        wifi_mgr = WiFiManager()
        print("[flockify] WiFi manager initialized")
    except Exception as e:
        print(f"[flockify] WARNING: WiFi manager init failed: {e}")
        wifi_mgr = None

    # ------------------------------------------------------------------
    # 9. Init Flask web server
    # ------------------------------------------------------------------
    init_app(state_machine, config_manager, spotify_manager, display_manager, bluetooth_mgr, wifi_mgr)

    flask_thread = threading.Thread(
        target=lambda: app.run(
            host="0.0.0.0",
            port=5000,
            use_reloader=False,
            debug=False,
        ),
        daemon=True,
    )
    flask_thread.start()
    print("[flockify] Web server started on http://0.0.0.0:5000")

    # ------------------------------------------------------------------
    # 10. Start audio monitoring
    # ------------------------------------------------------------------
    audio_router.start_monitoring(
        callback=state_machine.on_audio_output_changed,
        interval=5,
    )

    # Start time scheduler
    if time_scheduler:
        time_scheduler.start()

    # Start idle dimmer
    if idle_dimmer:
        idle_dimmer.start()

    # ------------------------------------------------------------------
    # 11. Resume state
    # ------------------------------------------------------------------
    # Respect the time schedule: if we booted into the 'night' period,
    # the scheduler's _apply_period(night) has already paused playback
    # and shown the sleep screen — resuming would trample both.
    try:
        in_night = (
            time_scheduler is not None
            and time_scheduler.get_current_period() == 'night'
        )
        if in_night:
            print("[flockify] Booted during night period — skipping resume (sleeping)")
        else:
            with state_machine.lock:
                state_machine._activate_mode(boot_resume=True)
            # Set initial Bluetooth icon state
            current_output = audio_router.get_active_output()
            display_manager.set_bluetooth_active(current_output == "bluetooth")
            # If we booted into quiet period, the scheduler has already
            # capped max volume; _activate_mode above re-pushed the stored
            # volume, which may exceed the cap. Re-apply quiet clamp.
            if time_scheduler is not None and time_scheduler.get_current_period() == 'quiet':
                quiet_max = time_scheduler.get_effective_max_volume()
                if state_machine.volume > quiet_max:
                    state_machine.set_volume(quiet_max)
            print("[flockify] Resumed playback from saved state")
    except Exception as e:
        print(f"[flockify] WARNING: Failed to resume state: {e}")

    # ------------------------------------------------------------------
    # 12. Print status
    # ------------------------------------------------------------------
    print("=" * 50)
    print("  Flockify Box is running!")
    print(f"  Web UI: http://0.0.0.0:5000")
    if not hardware_mode:
        print("  Mode: Development (no hardware)")
    print("=" * 50)

    # ------------------------------------------------------------------
    # 13. Main loop — wait for signals
    # ------------------------------------------------------------------
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Use threading.Event().wait() for cross-platform compatibility
    stop_event = threading.Event()
    try:
        stop_event.wait()
    except (KeyboardInterrupt, SystemExit):
        shutdown(None, None)


if __name__ == "__main__":
    main()
