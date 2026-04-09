# Flockify Box

A Raspberry Pi 5 music player for kids that plays Spotify playlists and web radio, with physical button controls, a small SPI display, and a web-based configuration interface.

## Features

- **Spotify Connect** — Play up to 10 Spotify playlists via Raspotify (librespot)
- **Web Radio** — Stream one configurable web radio station (default: Radino)
- **Physical Buttons** — 5 GPIO buttons: volume up/down, next/prev track, next playlist/mode
- **1.83" SPI Display** — Shows playlist cover art or web radio image, with Bluetooth icon overlay
- **Web Interface** — Configure playlists, settings, Bluetooth, and schedules from any device on your WiFi
- **Bluetooth + Wired Audio** — Automatic switching between Bluetooth headphones and wired speakers
- **Time-based Scheduling** — Nighttime lockout (sleep screen, no music), quiet hours (lower volume/brightness), and normal daytime mode
- **Bluetooth Management** — Scan, pair, connect, disconnect, and forget Bluetooth devices from the web UI

## Hardware Requirements

| Component | Details |
|-----------|---------|
| Raspberry Pi 5 | 2GB model (or higher) |
| SPI Display | 1.83" ST7789 LCD (240x280 pixels) |
| USB Audio Adapter | For 3.5mm wired speaker output (Pi 5 has no headphone jack) |
| 5x Momentary Buttons | Connected between GPIO and GND |
| Bluetooth Speaker/Headphones | Optional, for wireless audio |
| MicroSD Card | 16GB+ with Raspberry Pi OS |
| Power Supply | USB-C, 5V 3A recommended |

## GPIO Wiring

Each button connects its GPIO pin to GND when pressed. Internal pull-up resistors are used (no external resistors needed).

| Button | GPIO Pin | Header Pin | Function |
|--------|----------|------------|----------|
| Volume Up | 5 | 29 | Increase volume |
| Volume Down | 6 | 31 | Decrease volume |
| Next Track | 16 | 36 | Skip to next track (Spotify only) |
| Prev Track | 26 | 37 | Go to previous track (Spotify only) |
| Next Playlist | 12 | 32 | Cycle through playlists + web radio |

**Pins to avoid** (already in use): GPIO 8, 9, 10, 11 (SPI display), GPIO 13 (display backlight PWM), GPIO 25 (display DC), GPIO 27 (display RST), GPIO 18, 19, 21 (I²S → MAX98357A amp), GPIO 5, 6, 12, 16, 26 (buttons).

### MAX98357A Amp Wiring (I²S)

| Amp Pin | GPIO | Header Pin | Notes |
|---------|------|------------|-------|
| VIN     | 5V   | 2          | Use pin 2, keep pin 4 free |
| GND     | GND  | 6          | |
| BCLK    | 18   | 12         | I²S bit clock |
| LRC     | 19   | 35         | I²S word-select |
| DIN     | 21   | 40         | I²S data in |
| SD/GAIN | —    | —          | Leave NC for default 9 dB gain |

Enable the DAC overlay in `/boot/firmware/config.txt`:

```
dtparam=i2s=on
dtoverlay=hifiberry-dac
# Optional — disable onboard HDMI audio so PipeWire picks the DAC as default:
# dtparam=audio=off
```

Reboot; the DAC will appear as an ALSA card (e.g. `snd_rpi_hifiberry_dac`) and PipeWire will expose it as a sink. Flockify's existing audio router treats any non-Bluetooth sink as "wired", so the amp will be used automatically whenever Bluetooth isn't connected.

### SPI Display Wiring

| Display Pin | GPIO | Header Pin |
|-------------|------|------------|
| SCK | 11 (SPI0 SCLK) | 23 |
| SDA (MOSI) | 10 (SPI0 MOSI) | 19 |
| CS | 8 (SPI0 CE0) | 24 |
| DC | 25 | 22 |
| RST | 27 | 13 |
| BL | 13 (PWM) | 33 |
| VCC | — | 1 (3.3V) |
| GND | — | 6 (GND) |

**Required: 10 kΩ pull-down resistor between GPIO 13 (pin 33) and GND (pin 34).**
Without it, the display backlight stays lit after a J2 soft-off because the
ST7789 module has an internal pull-up on its BL line and the Pi 5's 3.3 V
rail remains alive during soft-off. The pull-down unconditionally grounds
the pin whenever flockify isn't actively driving it; during normal operation
the GPIO drive current (~16 mA) dominates the ~0.33 mA leakage through the
resistor so there's no visible brightness loss. Any value 4.7 k–22 kΩ works.

### Power Button (J2 header)

Solder a momentary pushbutton across the Pi 5's **J2** (`PWR_BTN`) header
next to the USB-C socket. Short press while running = clean soft-shutdown;
short press from halted = wake and boot. No software configuration needed.
Combined with the pull-down resistor above, the display goes dark
immediately on shutdown and stays dark through the entire halted state.

## Installation

### 1. Prepare the Raspberry Pi

1. Flash **Raspberry Pi OS (64-bit, Bookworm)** to your MicroSD card using Raspberry Pi Imager
2. Enable SSH and configure WiFi in the imager settings
3. Boot the Pi and SSH in: `ssh pi@raspberrypi.local`

### 2. Copy the project files

From your Mac/PC, copy the entire project to the Pi:

```bash
scp -r "/path/to/Flockify Box" pi@raspberrypi.local:~/flockify
```

### 3. Run the installer

```bash
ssh pi@raspberrypi.local
cd ~/flockify
sudo bash scripts/install.sh
```

This will:
- Install system packages (mpv, PulseAudio, avahi, etc.)
- Install and configure **Raspotify** (Spotify Connect receiver, device name: `flockifybox`)
- Create a Python virtual environment with all dependencies
- Enable SPI interface
- Set hostname to `flockifybox`
- Add user `pi` to required groups (spi, gpio, pulse, bluetooth)
- Install and enable the systemd service
- Create required directories

### 4. Reboot

```bash
sudo reboot
```

After reboot, the Flockify Box service starts automatically.

## First-Time Setup

### 1. Open the web interface

From any device on the same WiFi network, open:

```
http://flockifybox.local:5000
```

> If `.local` doesn't resolve, find the Pi's IP address with `hostname -I` on the Pi, then use `http://<IP>:5000`.

### 2. Connect Spotify

1. Go to the **Settings** page
2. You need a **Spotify Developer App**:
   - Go to [https://developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
   - Log in with **your** Spotify account (any account, not necessarily the one that will play music)
   - Click **"Create app"**
   - App name: `Flockify Box`, description: anything
   - **Redirect URI**: `http://127.0.0.1:5000/callback`
   - Select **Web API**
   - Save the app
3. Copy the **Client ID** and **Client Secret** from the app dashboard
4. Enter them on the Settings page and click **"Connect to Spotify"**

> **Important**: The OAuth redirect uses `127.0.0.1`, so you need to do this step either:
> - From a browser **on the Pi itself** (e.g., via VNC), or
> - Via SSH port forwarding: `ssh -L 5000:127.0.0.1:5000 pi@flockifybox.local`, then open `http://127.0.0.1:5000/settings` on your computer

5. When redirected to Spotify, log in with the **account that will play music** (e.g., your daughter's account). This is the account whose playlists will be available.
6. After authorization, you'll be redirected back. The refresh token is saved automatically.

### 3. Add Playlists

1. Go to the **Playlists** page
2. Paste a Spotify playlist URL (e.g., `https://open.spotify.com/playlist/37i9dQZF1DX6z20IXmBjWI`) and click **Add**
3. Add up to 10 playlists
4. Configure the web radio station name and stream URL (default: Radino)

### 4. Pair Bluetooth (optional)

1. Go to the **Settings** page, scroll to **Bluetooth**
2. Put your Bluetooth speaker/headphones in pairing mode
3. Click **"Scan for Devices"** — wait ~8 seconds
4. Click **"Pair"** next to your device
5. Audio will automatically switch to Bluetooth when connected

### 5. Configure Schedule (optional)

1. On the **Settings** page, enable the **Schedule**
2. Set your time periods:
   - **Nighttime**: e.g., 20:00 to 06:00 — display shows sleep screen, all buttons locked, no music
   - **Wake-up**: e.g., 06:00 to 07:00 — music allowed at reduced volume
   - **Go-to-bed**: e.g., 19:00 to 20:00 — music allowed at reduced volume
3. Adjust quiet volume/backlight and night backlight levels
4. Click **Save Schedule**

## How It Works

### Mode Cycling

The "Next Playlist" button cycles through all configured modes in order:

```
Playlist 1 → Playlist 2 → ... → Playlist N → Web Radio → Playlist 1
```

### Audio Routing

- **Bluetooth connected**: Audio plays through Bluetooth (BT icon shown on display)
- **Bluetooth disconnected**: Audio automatically switches to wired speakers (USB audio adapter)
- The system monitors Bluetooth connectivity every 5 seconds and switches seamlessly

### Time Schedule (if enabled)

| Period | Behavior |
|--------|----------|
| Night | Sleep screen on display, all buttons locked, playback stopped |
| Quiet (wake-up/bedtime) | Music plays, volume capped at quiet max, display dimmer |
| Day | Normal operation, full volume and brightness |

## File Structure

```
flockify/
├── flockify.py              # Main entry point
├── config_manager.py        # JSON config with atomic saves
├── config_default.json      # Default configuration template
├── audio_router.py          # PulseAudio BT/wired switching
├── spotify_manager.py       # Spotify Web API (spotipy)
├── state_machine.py         # Central coordinator
├── display_manager.py       # SPI display + BT icon overlay
├── button_controller.py     # 5 GPIO buttons
├── bluetooth_manager.py     # bluetoothctl wrapper
├── time_scheduler.py        # Night/quiet/day scheduling
├── web/
│   ├── app.py               # Flask web server + REST API
│   ├── templates/            # HTML pages (dashboard, playlists, settings)
│   └── static/               # CSS + JavaScript
├── lib/
│   ├── webradio_player.py   # mpv-based audio streaming
│   ├── spi_display_lib.py   # ST7789 SPI display driver
│   └── rpi_button_script.py # GPIO button handler (gpiod)
├── images/
│   ├── radino.png           # Default web radio image
│   ├── bluetooth_icon.png   # BT overlay icon
│   └── cache/               # Downloaded Spotify cover art
├── scripts/install.sh       # System installer
├── systemd/flockify.service # Auto-start service
└── requirements.txt         # Python dependencies
```

## Manual Control

```bash
# Start the service
sudo systemctl start flockify

# Stop the service
sudo systemctl stop flockify

# View live logs
journalctl -u flockify -f

# Run in development mode (no GPIO/SPI hardware)
python3 flockify.py --no-hardware
```

## Troubleshooting

### Web UI not accessible
- Check the Pi is on WiFi: `hostname -I`
- Check the service is running: `sudo systemctl status flockify`
- Try the IP address directly: `http://<PI_IP>:5000`

### No sound
- Check PulseAudio: `pactl info`
- List audio sinks: `pactl list sinks short`
- Check USB audio adapter is connected: `aplay -l`

### Spotify not working
- Verify Raspotify is running: `sudo systemctl status raspotify`
- Check Spotify credentials in web UI Settings page
- Ensure the Spotify account has an active Premium subscription
- The Raspotify device may take a few seconds to appear after boot

### Bluetooth won't pair
- Ensure the target device is in pairing mode
- Check Bluetooth is powered on: `bluetoothctl show` → look for `Powered: yes`
- Try manually: `bluetoothctl scan on`, then `pair <address>`

### Display not working
- Verify SPI is enabled: `ls /dev/spidev0.*` (should show `spidev0.0`)
- Check wiring: DC→GPIO25, RST→GPIO27, BL→GPIO13
- Test display separately: `python3 -c "from lib.spi_display_lib import SPIDisplay; d = SPIDisplay(); d.init(); d.clear((255,0,0))"`

## Auto-update from GitHub

The box checks for updates from GitHub on every boot (before the music player starts). If new commits are available on the `main` branch, they're pulled automatically. If `requirements.txt` changed, Python dependencies are reinstalled.

- **Trigger**: On boot, via `flockify-update.service` (runs before `flockify.service`)
- **Branch**: `main` only
- **Merge strategy**: Fast-forward only (never creates merge commits, refuses on divergence)
- **Timeout**: 90 seconds — if GitHub is unreachable, the box boots with the existing code
- **Auth**: SSH deploy key (read-only) generated during install

### First-time setup

After running `install.sh`, the script generates an SSH deploy key and prints its public key. You need to add it to the GitHub repo:

1. Copy the public key printed by the installer
2. Go to [https://github.com/NikBrownTRP/flockify-box/settings/keys/new](https://github.com/NikBrownTRP/flockify-box/settings/keys/new)
3. Title: `flockifybox-pi`
4. Paste the key
5. Leave **"Allow write access"** unchecked (read-only is safer)
6. Click **Add key**

The next reboot will successfully pull updates.

### Verifying auto-update

```bash
# View last update attempt
sudo journalctl -u flockify-update -n 50

# Trigger manually
sudo systemctl start flockify-update

# Check the deploy key works
sudo -u pi ssh -T git@github.com
```

### Disabling auto-update

```bash
sudo systemctl disable flockify-update
```

The box will still run normally — updates just become manual (`cd /home/pi/flockify && git pull`).

## Low Power Mode

The install script enables low power mode automatically to reduce heat and power consumption during long music sessions. Optimizations:

- **CPU governor**: `powersave` (pins to minimum frequency, only ramps up when needed)
- **HDMI output**: disabled (saves ~150mW, not needed for headless music box)
- **WiFi power saving**: enabled
- **Raspotify bitrate**: 96 kbps (still fine quality for kids' music on a small speaker)
- **Relaxed polling intervals**: Bluetooth monitor 10s, time scheduler 60s

### Verifying low power mode

Run these on the Pi after boot:

```bash
# Check CPU governor (should print "powersave" for each core)
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

# Check CPU frequency (should be at minimum ~600000 kHz when idle)
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq

# Check throttling status (should be 0x0 = no throttling)
vcgencmd get_throttled

# Check CPU temperature
vcgencmd measure_temp

# Check WiFi power saving
iw dev wlan0 get power_save

# Check low power service status
sudo systemctl status flockify-lowpower
```

### Re-enabling HDMI (e.g., for debugging)

```bash
vcgencmd display_power 1
```

### Disabling low power mode

```bash
sudo systemctl disable --now flockify-lowpower
sudo reboot
```

## Dependencies

**System packages**: python3, libmpv, pulseaudio, pulseaudio-module-bluetooth, avahi-daemon, raspotify

**Python packages**: flask, spotipy, python-mpv, pulsectl, requests, Pillow, numpy, gpiod, lgpio, spidev
