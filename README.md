# Flockify Box 🐯

A Raspberry Pi 5 music player built for kids — Spotify playlists, web radio, physical buttons, a tiny SPI display, and a parent-friendly web interface, all in one box.

**[📖 Full Setup Guide & Documentation](https://nikbrowntrp.github.io/flockify-box/)** — interactive page with shopping list, wiring diagrams, and step-by-step instructions (also available in German).

## Features

- **Spotify Connect** — Play up to 10 Spotify playlists/albums via go-librespot at 320 kbps
- **Web Radio** — Stream one configurable web radio station (default: Radino) with EBU R128 loudness normalisation
- **Physical Buttons** — 5 GPIO buttons: volume up/down, next/prev track, next playlist/mode
- **Power Button** — J2 header for clean shutdown/wake with visual feedback (shutdown tiger screen)
- **1.83" SPI Display** — Shows playlist covers, boot/sleep/shutdown tiger screens, volume overlay, BT icon
- **Web Interface** — Dashboard, playlist management, WiFi/Bluetooth/Spotify/schedule configuration
- **Bluetooth + Wired Audio** — Automatic 5-second switching between BT and MAX98357A I²S amp
- **Time Schedule** — Night lockout (sleep screen, buttons locked), quiet hours (reduced volume/brightness), day mode
- **WiFi AP Hotspot** — No known WiFi? The box creates a "FlockifyBox" hotspot for phone-based setup
- **Auto-Update** — Pulls from GitHub on every boot (fast-forward only, 90s timeout)
- **Low Power** — CPU powersave governor, HDMI off, WiFi power saving
- **Idle Dimmer** — Display dims to 20% after 60s of no interaction, restores on button press
- **Spotify Self-Heal** — Automatic recovery from zombie Connect sessions

## Hardware

| Component | Details |
|-----------|---------|
| Raspberry Pi 5 | 2 GB model (or higher) |
| MicroSD Card | 16 GB+ with Raspberry Pi OS (64-bit, Bookworm/Trixie) |
| USB-C Power Supply | 5V 3A recommended (5A meets Pi 5 spec) |
| Powerbank (optional) | ≥3 A continuous, no low-current auto-cutoff. Cheap 2 A banks cause undervoltage and shut off prematurely. |
| SPI Display | 1.83" ST7789 LCD (240x280 pixels, visible area 240x285) |
| MAX98357A | I²S DAC + Class D amplifier breakout |
| Speaker | 4–8 Ohm, 3W, connected directly to MAX98357A output |
| 5x Momentary Buttons | For volume, track, and mode control |
| 1x Power Button | Momentary pushbutton for Pi 5 J2 header |
| 10 kΩ Resistor | Pull-down between GPIO 13 and GND (backlight off on shutdown) |
| Jumper Wires | Female-to-female for GPIO connections |
| Enclosure | Your choice — wood, 3D print, cardboard |
| Bluetooth Speaker/Headphones | Optional, for wireless audio |

## GPIO Wiring

Each button connects its GPIO pin to GND when pressed. Internal pull-up resistors are used.

### Buttons

| Button | GPIO | Pin | Function |
|--------|------|-----|----------|
| Volume Up | 5 | 29 | Increase volume |
| Volume Down | 6 | 31 | Decrease volume |
| Next Track | 16 | 36 | Skip to next track (Spotify only) |
| Prev Track | 26 | 37 | Previous track (Spotify only) |
| Next Mode | 12 | 32 | Cycle playlists + web radio |

### SPI Display (ST7789)

| Display Pin | GPIO | Pin |
|-------------|------|-----|
| SCK | 11 (SPI0 SCLK) | 23 |
| SDA (MOSI) | 10 (SPI0 MOSI) | 19 |
| CS | 8 (SPI0 CE0) | 24 |
| DC | 25 | 22 |
| RST | 27 | 13 |
| BL | 13 (PWM) | 33 |
| VCC | 3.3V | 1 |
| GND | GND | 6 |

> **Required:** 10 kΩ pull-down resistor between pin 33 (GPIO 13) and pin 34 (GND). Without it, the display backlight stays on after J2 soft-off. Any value 4.7–22 kΩ works. The resistor legs can piggyback on the existing BL DuPont connector at pin 33.

### MAX98357A Amplifier (I²S)

| Amp Pin | GPIO | Pin | Notes |
|---------|------|-----|-------|
| VIN | 5V | 2 | Use pin 2, keep pin 4 free |
| GND | GND | 6 | Shared with display GND |
| BCLK | 18 | 12 | I²S bit clock |
| LRC | 19 | 35 | I²S word-select |
| DIN | 21 | 40 | I²S data in |
| SD/GAIN | — | — | Leave NC for default 9 dB gain |

### Power Button (J2)

Solder a momentary pushbutton across the Pi 5's **J2** (`PWR_BTN`) header next to the USB-C socket. Short press = clean shutdown (shows goodbye tiger, then display off). Press again from halted = wake and boot.

### Pins in Use

GPIO 5, 6, 8, 9, 10, 11, 12, 13, 16, 18, 19, 21, 25, 26, 27.

## Installation

### 1. Flash the SD Card

Flash **Raspberry Pi OS (64-bit)** using Raspberry Pi Imager. Enable SSH and configure WiFi in the imager settings.

### 2. Clone and Install

```bash
ssh pi@raspberrypi.local
git clone https://github.com/NikBrownTRP/flockify-box.git ~/flockify
cd ~/flockify
sudo bash scripts/install.sh
sudo reboot
```

The installer handles: system packages, go-librespot (Spotify Connect at 320 kbps), Python venv, SPI + I²S DAC overlays, hostname (`flockifybox`), user groups, and all systemd services.

### 3. Enable I²S DAC

The installer adds the overlay automatically. Verify after reboot:

```bash
aplay -l   # Should show "snd_rpi_hifiberry_dac"
```

### 4. Open the Web UI

```
http://flockifybox.local:5000
```

If the Pi has no WiFi connection, it creates a **FlockifyBox** hotspot (password: `flockify123`). Connect your phone and visit `http://192.168.4.1:5000`.

### 5. Connect Spotify

1. Create a [Spotify Developer App](https://developer.spotify.com/dashboard)
2. Set redirect URI to `http://flockifybox.local:5000/callback`
3. Add your Spotify account as a user in the Developer Dashboard
4. Enter Client ID + Secret in **Settings → Spotify Connection**
5. Complete the OAuth flow

### 6. Add Playlists

Go to the **Playlists** page, paste Spotify playlist/album URLs (up to 10), and press the mode button to cycle through them.

## Display Screens

| Screen | Image | When Shown |
|--------|-------|------------|
| Boot | `boot_tiger.png` | Power on → first ~15s of boot |
| Sleep | `sleep_tiger.png` | Night period (schedule active) |
| Shutdown | `shutdown_tiger.png` | J2 press → 1.5s → display off |
| Playlist cover | Downloaded from Spotify | During Spotify playback |
| Radino | `radino.png` | During web radio playback |

The boot splash service (`flockify-boot-splash`) shows the boot tiger very early in the boot sequence. During night hours, it automatically shows the sleep tiger at 5% brightness instead — no bright flash in the bedroom.

## Audio Architecture

Both players (go-librespot + mpv) run at internal unity volume. The user's volume knob controls a single gain stage — the PipeWire default-sink volume — keeping the full signal amplitude through the digital path.

| Setting | Value | Purpose |
|---------|-------|---------|
| `max_output_percent` | 60 | Kid-safe ceiling: knob=100 → sink at 60% |
| `webradio_volume` | 25 | Trims mpv to match Spotify's normalised level |
| go-librespot normalisation | `config.yml` | Format, bitrate, and normalisation are configured in go-librespot's config.yml |
| mpv `loudnorm` filter | I=-16:TP=-1.5 | EBU R128 normalisation for webradio streams |

## Systemd Services

| Service | Type | Purpose |
|---------|------|---------|
| `flockify.service` | simple | Main music player app |
| `flockify-boot-splash.service` | oneshot | Early SPI display boot image |
| `flockify-wifi-ap.service` | oneshot | WiFi hotspot if no known network |
| `flockify-update.service` | oneshot | Auto-update from GitHub on boot |
| `flockify-lowpower.service` | oneshot | CPU powersave + WiFi power saving |
| `go-librespot.service` | simple | Spotify Connect (go-librespot) |

## File Structure

```
flockify/
├── flockify.py              # Main entry point + shutdown handler
├── config_manager.py        # JSON config with atomic saves
├── config_default.json      # Default configuration template
├── audio_router.py          # PipeWire BT/wired switching
├── spotify_manager.py       # Spotify Web API + self-heal
├── state_machine.py         # Central coordinator (modes, volume, schedule)
├── display_manager.py       # SPI display + BT icon + volume overlay
├── button_controller.py     # 5 GPIO buttons (gpiod)
├── bluetooth_manager.py     # bluetoothctl wrapper
├── wifi_manager.py          # nmcli wrapper (scan, connect, AP, forget)
├── time_scheduler.py        # Night/quiet/day period scheduling
├── idle_dimmer.py           # Display dim after 60s idle
├── webradio_player.py       # mpv streaming with loudnorm filter
├── web/
│   ├── app.py               # Flask server + REST API
│   ├── templates/           # Dashboard, playlists, settings pages
│   └── static/              # CSS + JavaScript
├── lib/
│   └── spi_display_lib.py   # ST7789 SPI display driver (F32-capable)
├── images/
│   ├── boot_tiger.png       # Boot splash (cheerful tiger)
│   ├── sleep_tiger.png      # Night mode (tiger with teddy)
│   ├── shutdown_tiger.png   # Shutdown feedback (waving goodbye)
│   ├── radino.png           # Web radio station image
│   ├── bluetooth_icon.png   # BT overlay icon
│   ├── volume/              # Volume overlay speaker frames
│   └── cache/               # Downloaded Spotify cover art
├── scripts/
│   ├── install.sh           # System installer
│   ├── wifi-ap.sh           # WiFi AP hotspot boot script
│   ├── show_boot_splash.py  # Early boot display (schedule-aware)
│   └── flockify-backlight-off  # systemd-shutdown display cleanup
├── config/
│   └── go-librespot.yml     # go-librespot configuration (format, bitrate, normalisation)
├── systemd/                 # All .service files (including go-librespot.service)
├── docs/
│   └── index.html           # Project intro page (EN/DE, GitHub Pages)
├── tests/                   # 166 pytest tests (runs without Pi hardware)
└── requirements.txt         # Python dependencies
```

## Troubleshooting

### Web UI not accessible
- No WiFi? Connect to the **FlockifyBox** hotspot (pw: `flockify123`) → `http://192.168.4.1:5000`
- Check service: `sudo systemctl status flockify`
- Try IP directly: `hostname -I` on the Pi → `http://<IP>:5000`

### No sound
- Check sinks: `pactl list sinks short`
- Verify DAC: `aplay -l` (should show `snd_rpi_hifiberry_dac`)
- Check wiring to MAX98357A and speaker

### Spotify playback stuck (no audio, 404/429 errors)
go-librespot persists credentials automatically. If playback fails after a power cycle, pair from your phone once (Spotify → device icon → **flockifybox**). This should only be needed on first setup.

### Display not working
- SPI enabled? `ls /dev/spidev0.*`
- Wiring: DC→GPIO25, RST→GPIO27, BL→GPIO13
- Test: `python3 -c "from lib.spi_display_lib import SPIDisplay; d = SPIDisplay(); d.init(); d.clear((255,0,0))"`

### Bluetooth won't connect
- Target device in pairing mode?
- `bluetoothctl show` → `Powered: yes`?
- Manual: `bluetoothctl scan on` → `pair <address>`

### Short battery life when running idle
"Standby" via the J2 power button cuts all rails (`POWER_OFF_ON_HALT=1`) — battery drain is near zero in that state. If the box is *running* idle and dies in ~1 day on a 10 Ah powerbank, check that WiFi power-save actually engaged:

```bash
iw dev wlan0 get power_save        # expect: Power save: on
vcgencmd get_throttled             # expect: 0x0 (any nonzero = undervoltage/throttle)
systemctl status flockify-lowpower
```

If `iw` is missing (`command not found`), the lowpower service silently no-ops the WiFi step. Fix with `sudo apt-get install -y iw && sudo systemctl restart flockify-lowpower`. Repeated undervoltage events in `dmesg` (`hwmon … Undervoltage detected!`) mean the powerbank can't sustain peak current — use a bank rated ≥3 A continuous.

## Auto-Update

Pulls from GitHub `main` branch on every boot via `flockify-update.service`. Fast-forward only, 90s timeout. Requires a read-only SSH deploy key added to the GitHub repo (generated during install).

```bash
# View last update
sudo journalctl -u flockify-update -n 50

# Trigger manually
sudo systemctl start flockify-update

# Disable
sudo systemctl disable flockify-update
```

## Testing

```bash
python3 -m pytest tests/ -v   # 166 tests, runs on macOS without Pi hardware
```

## Dependencies

**System**: python3, libmpv, pulseaudio, pulseaudio-module-bluetooth, avahi-daemon, go-librespot, NetworkManager

**Python**: flask, spotipy, python-mpv, pulsectl, requests, Pillow, numpy, lgpio, spidev
