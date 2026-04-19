# Design: Standby Power Fix + Spurious Wake-up Prevention

**Date:** 2026-04-19
**Hardware:** Raspberry Pi 5

---

## Problem

Two user-reported issues share a single root cause:

1. **High standby power drain** — a 10,000 mAh powerbank is empty after a day when the box is "off" (J2 pressed).
2. **Spurious wake-ups** — after a J2 poweroff, the box sometimes powers back on and starts playing music without user interaction.

### Root cause

When `systemctl poweroff` halts the Pi 5 CPU, the USB controller, WiFi chip, I²S DAC, and voltage regulators continue drawing power from the powerbank (~1.5–2 W). The powerbank cannot detect that the load is "gone" so it never auto-shuts off. Over time (typically after many hours or when the battery runs low) the powerbank pulses its output to probe for a connected device. This power pulse causes the Pi 5 to reboot — flockify starts, `_activate_mode()` runs, and music plays.

---

## Solution overview

Four parts, in order of impact:

| Part | What | Impact |
|---|---|---|
| 1 | Pi 5 EEPROM `POWER_OFF_ON_HALT=1` | Drops halt current from ~1.5 W to ~few mW |
| 2 | rfkill + clean shutdown flag before poweroff | Belt-and-suspenders; signals intentional shutdown |
| 3 | Startup silent mode when flag present | Prevents auto-play even if Pi unexpectedly reboots |
| 4 | Install script EEPROM step | Makes Part 1 automatic and idempotent |

---

## Part 1 — Pi 5 EEPROM: `POWER_OFF_ON_HALT=1`

The Pi 5 PMIC (RP1) supports a config option that cuts all internal power rails when the system halts, leaving only the PMIC's own quiescent draw (~few mW). This is functionally equivalent to a hard power-off.

**Config key:** `POWER_OFF_ON_HALT=1` in the Pi EEPROM config (read/written via `rpi-eeprom-config`).

**Effect:**
- After `systemctl poweroff`, Pi draws < 10 mW
- Powerbank detects current drop → auto-shuts off within seconds
- Powerbank's pulse-probe never happens → no spurious reboot
- To power on again: press powerbank button (restores 5V) then press J2

**Limitation:** Requires a reboot after applying to take effect.

---

## Part 2 — Pre-shutdown: rfkill + clean shutdown flag

Inside `_monitor_power_button()` in `flockify.py`, immediately before `Popen(["sudo", "systemctl", "poweroff"])`:

1. **Write flag file** at `SHUTDOWN_FLAG_PATH = /home/pi/flockify/.shutdown_flag`
2. **rfkill block all** — disables WiFi and Bluetooth, reducing current further during the shutdown sequence and preventing any network activity during halt

This runs in the existing power-button monitoring thread, so no new services or threads are needed.

---

## Part 3 — Startup silent mode

In `flockify.py` `main()`, after all subsystems are initialised and before the resume-state block (step 11), check for the flag file:

- If flag exists: delete it, set `state_machine.silent_mode = True`, show sleep screen, skip `_activate_mode()`
- If flag absent: normal startup (existing behaviour)

In `state_machine.py`:

- Add `self.silent_mode = False` to `__init__`
- In `_activate_mode()`: if `self.silent_mode` is True, skip the Spotify/webradio play calls (display update still runs so the cover art is shown)
- In `notify_activity()`: if `self.silent_mode` is True, clear it before notifying the idle dimmer, then call `_activate_mode()` to actually start playback

The result: after a clean shutdown, the box boots silently showing the playlist cover. The first button press (or web UI interaction) starts playback as normal.

---

## Part 4 — Install script EEPROM step

New step in `scripts/install.sh` after the existing lowpower service step:

1. Read current EEPROM config via `rpi-eeprom-config`
2. If `POWER_OFF_ON_HALT` is already `1`: print "already set, skipping"
3. Otherwise: append `POWER_OFF_ON_HALT=1`, write to temp file, apply via `rpi-eeprom-config --apply`
4. Print reminder that a reboot is needed for the EEPROM change to take effect

Detection of Pi 4 vs Pi 5 is not needed — `POWER_OFF_ON_HALT=1` is valid on both; `rpi-eeprom-config` is only present on Pi 4/5, so the step is wrapped in a `command -v rpi-eeprom-config` guard to be safe on older hardware.

---

## Files changed

| File | Change |
|---|---|
| `flockify.py` | `_monitor_power_button()`: write flag + rfkill before poweroff; `main()`: check flag, set silent_mode |
| `state_machine.py` | Add `silent_mode` flag; skip playback in `_activate_mode()` when set; clear + resume in `notify_activity()` |
| `scripts/install.sh` | New step: detect and apply EEPROM `POWER_OFF_ON_HALT=1` |

No new files, services, or hardware changes required.

---

## Success criteria

- After J2 press, powerbank auto-shuts off within a few minutes (observable via powerbank LEDs going dark)
- Box does not start playing after powerbank auto-restores power
- After deliberate powerbank restart → J2 press, box boots silently
- First button press resumes playback correctly
- Normal (non-shutdown) reboots are unaffected
