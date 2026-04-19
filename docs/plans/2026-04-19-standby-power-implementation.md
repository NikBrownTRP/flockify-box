# Standby Power Fix + Spurious Wake-up Prevention — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate standby power drain and spurious Spotify wake-ups by getting the Pi 5 to draw near-zero current after poweroff, and silencing the box on any unexpected reboot.

**Architecture:** Three changes — (1) `state_machine.py` gains a `silent_mode` flag that suppresses auto-play on startup; (2) `flockify.py` writes a flag file + calls rfkill before poweroff, and reads the flag on startup to set silent mode; (3) `scripts/install.sh` gains an EEPROM step that sets `POWER_OFF_ON_HALT=1`, which makes the Pi 5 PMIC cut all internal rails on halt so the powerbank auto-shuts off.

**Tech Stack:** Python 3, pytest/unittest.mock, Bash, `rpi-eeprom-config` (Pi 4/5), `rfkill`

---

## Task 1: StateMachine `silent_mode` flag

**Files:**
- Modify: `state_machine.py`
- Test: `tests/test_state_machine.py`

Context: `state_machine.py` is the central coordinator. `_activate_mode()` starts playback (calls `self.spotify.play_playlist()` or `self.webradio.play_station()`). `_notify_activity()` is called at the end of every user-triggered action (button press, web UI call). The test file already imports `StateMachine` and has a `state_machine` pytest fixture with mocked deps — append new tests at the bottom.

---

**Step 1: Write failing tests**

Append to `tests/test_state_machine.py`:

```python
# -----------------------------------------------------------------
# Silent mode (clean-shutdown guard)
# -----------------------------------------------------------------

def test_silent_mode_default_false(state_machine):
    """StateMachine initialises with silent_mode=False."""
    assert state_machine.silent_mode is False


def test_activate_mode_skips_playback_in_silent_mode(state_machine):
    """_activate_mode must not call spotify.play_playlist when silent_mode=True."""
    state_machine.silent_mode = True
    state_machine.mode_index = 0  # spotify mode
    state_machine._activate_mode()
    state_machine.spotify.play_playlist.assert_not_called()


def test_activate_mode_plays_normally_when_not_silent(state_machine):
    """_activate_mode calls spotify.play_playlist when silent_mode=False."""
    state_machine.silent_mode = False
    state_machine.mode_index = 0  # spotify mode
    state_machine._activate_mode()
    state_machine.spotify.play_playlist.assert_called_once()


def test_notify_activity_clears_silent_mode(state_machine):
    """First _notify_activity while silent clears the flag."""
    state_machine.silent_mode = True
    state_machine._notify_activity()
    assert state_machine.silent_mode is False


def test_notify_activity_in_silent_mode_triggers_playback(state_machine):
    """First _notify_activity while silent triggers _activate_mode → playback."""
    state_machine.silent_mode = True
    state_machine.mode_index = 0  # spotify mode
    state_machine._notify_activity()
    state_machine.spotify.play_playlist.assert_called_once()


def test_notify_activity_not_silent_does_not_start_playback(state_machine):
    """_notify_activity when NOT in silent mode must not call _activate_mode."""
    state_machine.silent_mode = False
    state_machine.mode_index = 0  # spotify mode
    state_machine._notify_activity()
    state_machine.spotify.play_playlist.assert_not_called()
```

**Step 2: Run tests to verify they fail**

```bash
cd "/Users/niklasbrown/Desktop/Claude Tools/Flockify Box"
python -m pytest tests/test_state_machine.py::test_silent_mode_default_false \
    tests/test_state_machine.py::test_activate_mode_skips_playback_in_silent_mode \
    tests/test_state_machine.py::test_activate_mode_plays_normally_when_not_silent \
    tests/test_state_machine.py::test_notify_activity_clears_silent_mode \
    tests/test_state_machine.py::test_notify_activity_in_silent_mode_triggers_playback \
    tests/test_state_machine.py::test_notify_activity_not_silent_does_not_start_playback \
    -v
```

Expected: all 6 FAIL (AttributeError: `StateMachine` object has no attribute `silent_mode`).

---

**Step 3: Implement `silent_mode` in `state_machine.py`**

In `__init__`, after the `self.idle_dimmer = None` line (line ~22), add:

```python
self.silent_mode = False  # Set True after a clean J2 shutdown; cleared on first user action
```

At the very top of `_activate_mode()`, before the existing `if not self._is_mode_allowed():` check, add:

```python
if self.silent_mode:
    # Box booted silently after a clean shutdown — don't start playback.
    # First user action (via _notify_activity) will clear this and activate.
    return
```

Replace `_notify_activity()` with:

```python
def _notify_activity(self):
    """Tell the idle dimmer that the user just interacted with the box.

    If the box booted in silent mode (after a clean J2 shutdown), the
    first user interaction clears silent mode and starts playback.
    """
    if self.silent_mode:
        self.silent_mode = False
        try:
            with self.lock:
                self._activate_mode()
        except Exception as e:
            print(f"[StateMachine] Error activating from silent mode: {e}")
    if self.idle_dimmer is not None:
        try:
            self.idle_dimmer.notify_activity()
        except Exception as e:
            print(f"[StateMachine] Error notifying idle dimmer: {e}")
```

---

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_state_machine.py -v
```

Expected: all tests PASS (including the 6 new ones and all pre-existing ones).

---

**Step 5: Commit**

```bash
git add state_machine.py tests/test_state_machine.py
git commit -m "feat: add silent_mode to StateMachine — suppress auto-play after clean shutdown"
```

---

## Task 2: Power-button handler + startup flag check in `flockify.py`

**Files:**
- Modify: `flockify.py`

No unit tests for this task — the changes are in daemon threads and the startup sequence, which are covered by manual verification. The logic being tested here is already proven by Task 1's tests.

---

**Step 1: Add the flag-file constant**

Near the top of `flockify.py`, after the `import threading` line, add:

```python
# Path of the clean-shutdown sentinel written by the power-button monitor
# before calling systemctl poweroff. Checked at startup to suppress
# auto-play when the Pi rebooted unexpectedly (e.g. powerbank power cycle).
SHUTDOWN_FLAG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.shutdown_flag')
```

---

**Step 2: Write flag + rfkill in `_monitor_power_button()`**

Find the block in `_monitor_power_button()` that starts with:
```python
print("[power-button] Triggering shutdown...")
_sp.Popen(["sudo", "systemctl", "poweroff"])
```

Replace it with:

```python
# Write clean-shutdown flag so flockify knows the next boot should
# be silent (user deliberately shut down, not a crash/power-cycle).
try:
    with open(SHUTDOWN_FLAG_PATH, 'w') as _f:
        _f.write('1')
    print("[power-button] Wrote clean shutdown flag")
except Exception as _e:
    print(f"[power-button] Could not write shutdown flag: {_e}")

# Disable WiFi + Bluetooth before halt — belt-and-suspenders to
# further reduce current draw while systemd winds down services.
try:
    import subprocess as _sp2
    _sp2.run(["sudo", "rfkill", "block", "all"],
             check=False, capture_output=True, timeout=3)
    print("[power-button] rfkill: WiFi + BT disabled")
except Exception as _e:
    print(f"[power-button] rfkill error (non-fatal): {_e}")

print("[power-button] Triggering shutdown...")
_sp.Popen(["sudo", "systemctl", "poweroff"])
```

---

**Step 3: Check flag at startup**

In `main()`, locate the comment `# 11. Resume state` and the `try:` block that follows it. The existing block starts with:

```python
try:
    in_night = (
        time_scheduler is not None
        and time_scheduler.get_current_period() == 'night'
    )
    if in_night:
        print("[flockify] Booted during night period — skipping resume (sleeping)")
    else:
        with state_machine.lock:
            state_machine._activate_mode()
        ...
```

Add the flag check so the block reads:

```python
try:
    # Check for clean-shutdown flag (J2 was pressed intentionally).
    _clean_shutdown = os.path.exists(SHUTDOWN_FLAG_PATH)
    if _clean_shutdown:
        try:
            os.remove(SHUTDOWN_FLAG_PATH)
        except Exception:
            pass
        state_machine.silent_mode = True
        print("[flockify] Clean shutdown flag found — booting in silent mode (first button press starts playback)")
        try:
            display_manager.show_sleep_screen()
        except Exception:
            pass

    in_night = (
        time_scheduler is not None
        and time_scheduler.get_current_period() == 'night'
    )
    if in_night:
        print("[flockify] Booted during night period — skipping resume (sleeping)")
    elif _clean_shutdown:
        print("[flockify] Silent mode — waiting for first user interaction")
    else:
        with state_machine.lock:
            state_machine._activate_mode()
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
            # Also auto-skip past any playlist that isn't allowed in
            # quiet. _activate_mode's internal check only falls back
            # to webradio — next_mode() actually cycles to the next
            # allowed playlist if one exists.
            if not state_machine._is_mode_allowed():
                print("[flockify] Booted into quiet with restricted playlist — auto-skipping")
                state_machine.next_mode()
        print("[flockify] Resumed playback from saved state")
except Exception as e:
    print(f"[flockify] WARNING: Failed to resume state: {e}")
```

---

**Step 4: Verify syntax**

```bash
cd "/Users/niklasbrown/Desktop/Claude Tools/Flockify Box"
python -m py_compile flockify.py && echo "OK"
```

Expected: `OK` (no output = no syntax errors).

---

**Step 5: Commit**

```bash
git add flockify.py
git commit -m "feat: write shutdown flag + rfkill before poweroff; boot silent after clean shutdown"
```

---

## Task 3: Install script — Pi 4/5 EEPROM `POWER_OFF_ON_HALT=1`

**Files:**
- Modify: `scripts/install.sh`

---

**Step 1: Add EEPROM step**

In `scripts/install.sh`, find the block:

```bash
echo "    Low power mode service installed and enabled."
echo "    - CPU governor: powersave"
echo "    - HDMI output: disabled"
echo "    - WiFi power saving: enabled"
echo "    - go-librespot bitrate: 320 kbps"
```

Immediately after that block, insert:

```bash
# =============================================================================
# Step 11b2: Configure EEPROM POWER_OFF_ON_HALT (Pi 4/5 only)
# =============================================================================
echo ">>> Step 11b2: Configuring EEPROM POWER_OFF_ON_HALT=1..."

if command -v rpi-eeprom-config >/dev/null 2>&1; then
    CURRENT_EEPROM=$(rpi-eeprom-config 2>/dev/null || true)
    if echo "$CURRENT_EEPROM" | grep -q '^POWER_OFF_ON_HALT=1'; then
        echo "    POWER_OFF_ON_HALT=1 already set — skipping."
    else
        EEPROM_TMP=$(mktemp)
        if echo "$CURRENT_EEPROM" | grep -q '^POWER_OFF_ON_HALT'; then
            # Key exists with a different value — replace it
            echo "$CURRENT_EEPROM" | sed 's/^POWER_OFF_ON_HALT=.*/POWER_OFF_ON_HALT=1/' > "$EEPROM_TMP"
        else
            # Key absent — append it
            echo "$CURRENT_EEPROM" > "$EEPROM_TMP"
            echo 'POWER_OFF_ON_HALT=1' >> "$EEPROM_TMP"
        fi
        rpi-eeprom-config --apply "$EEPROM_TMP"
        rm -f "$EEPROM_TMP"
        echo "    EEPROM updated: POWER_OFF_ON_HALT=1"
        echo "    *** A reboot is required for this change to take effect. ***"
        echo "    After reboot: pressing J2 will cut all Pi power rails on halt."
        echo "    The powerbank will auto-shutoff when current drops to near-zero."
    fi
else
    echo "    rpi-eeprom-config not found — EEPROM step skipped (Pi 3/Zero)."
fi
```

---

**Step 2: Verify install.sh syntax**

```bash
bash -n scripts/install.sh && echo "OK"
```

Expected: `OK`.

---

**Step 3: Commit**

```bash
git add scripts/install.sh
git commit -m "feat: apply POWER_OFF_ON_HALT=1 EEPROM config during install (Pi 4/5)"
```

---

## Manual verification (on the Pi)

After deploying and rebooting (for EEPROM to take effect):

1. **Power drain fix**: Press J2 → wait ~10 seconds → check powerbank LED panel goes dark (auto-shutoff triggered). Previously it would stay lit indefinitely.

2. **Silent mode**: After step 1, press the powerbank button to restore power. Pi boots. Confirm: no music starts automatically. Display shows the sleep screen.

3. **Wake on button press**: Press any physical button (e.g. volume up). Confirm: music starts playing. Subsequent button presses perform their normal actions.

4. **Normal reboot unaffected**: `sudo reboot` (without J2). Confirm: box resumes playback normally on reboot (no silent mode, because the flag file was not written).

5. **Night mode unaffected**: If the time scheduler is active and it's night, confirm that night mode still takes priority over silent mode (night check runs after the flag check and does not call `_activate_mode()` either — both paths lead to silent box, which is correct).
