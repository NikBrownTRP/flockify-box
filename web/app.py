"""
Flask web application for Flockify Box.

Provides a mobile-friendly dashboard, playlist management, and settings UI,
plus a REST API consumed by the frontend JavaScript.
"""

import os
import re
import subprocess
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import Flask, render_template, request, jsonify, redirect

app = Flask(__name__,
            template_folder='templates',
            static_folder='static')

# These get set by flockify.py after app creation
state_machine = None
config_manager = None
spotify_manager = None
display_manager = None
bluetooth_manager = None
wifi_manager = None


def init_app(sm, cm, spm, dm=None, bm=None, wm=None):
    """Initialize app with references to subsystems."""
    global state_machine, config_manager, spotify_manager, display_manager, bluetooth_manager, wifi_manager
    state_machine = sm
    config_manager = cm
    spotify_manager = spm
    display_manager = dm
    bluetooth_manager = bm
    wifi_manager = wm


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_spotify_url(url):
    """Extract a Spotify context URI from a URL or URI string.

    Accepts both playlists AND albums (Spotify's start_playback API
    treats both as valid context_uri values). Examples:
      - https://open.spotify.com/playlist/37i9dQZF1DX6z20IXmBjWI?si=...
      - https://open.spotify.com/album/7zU1NSsPQbHwXXoEHWa1g8?si=...
      - https://open.spotify.com/intl-de/playlist/...
      - https://open.spotify.com/de/album/...
      - spotify:playlist:37i9dQZF1DX6z20IXmBjWI
      - spotify:album:7zU1NSsPQbHwXXoEHWa1g8
      - spotify:user:foo:playlist:37i9dQZF1DX6z20IXmBjWI (legacy)

    Returns 'spotify:playlist:<id>' or 'spotify:album:<id>' or None.
    """
    url = url.strip()
    if not url:
        return None

    # URI forms (handles legacy spotify:user:xxx:playlist:ID too)
    uri_match = re.search(r'spotify:(?:user:[^:]+:)?(playlist|album):([A-Za-z0-9]+)', url)
    if uri_match:
        return f'spotify:{uri_match.group(1)}:{uri_match.group(2)}'

    # URL form — use re.search instead of re.match so locale prefixes
    # like /intl-de or /de don't break parsing
    parsed = urlparse(url)
    path_match = re.search(r'/(playlist|album)/([A-Za-z0-9]+)', parsed.path)
    if path_match:
        return f'spotify:{path_match.group(1)}:{path_match.group(2)}'

    return None


# ------------------------------------------------------------------
# Page routes
# ------------------------------------------------------------------

@app.route('/')
def index():
    status = state_machine.get_status() if state_machine else {}
    return render_template('index.html', status=status)


@app.route('/playlists')
def playlists_page():
    playlists = config_manager.get('playlists', []) if config_manager else []
    webradio = config_manager.get('webradio', {}) if config_manager else {}
    max_playlists = config_manager.MAX_PLAYLISTS if config_manager else 10
    return render_template('playlists.html',
                           playlists=playlists,
                           webradio=webradio,
                           max_playlists=max_playlists)


@app.route('/settings')
def settings_page():
    config = config_manager.config if config_manager else {}
    spotify_configured = spotify_manager.is_configured() if spotify_manager else False
    spotify_has_creds = spotify_manager.has_credentials() if spotify_manager else False
    spotify_connected = spotify_manager.is_connected() if spotify_manager and spotify_configured else False
    device_name = config.get('spotify', {}).get('device_name', 'flockifybox')
    bt_connected = None
    bt_paired = []
    if bluetooth_manager:
        bt_connected = bluetooth_manager.get_connected_device()
        bt_paired = bluetooth_manager.get_paired_devices()
    wifi_status = wifi_manager.get_status() if wifi_manager else {}
    wifi_saved = wifi_manager.get_saved_networks() if wifi_manager else []
    return render_template('settings.html',
                           config=config,
                           spotify_configured=spotify_configured,
                           spotify_has_creds=spotify_has_creds,
                           spotify_connected=spotify_connected,
                           device_name=device_name,
                           bt_connected=bt_connected,
                           bt_paired=bt_paired,
                           wifi_status=wifi_status,
                           wifi_saved=wifi_saved)


@app.route('/callback')
def spotify_callback():
    code = request.args.get('code')
    if code and spotify_manager:
        spotify_manager.handle_callback(code)
    return redirect('/settings')


# ------------------------------------------------------------------
# API routes
# ------------------------------------------------------------------

@app.route('/api/status')
def api_status():
    if not state_machine:
        return jsonify({'error': 'Not initialized'}), 503
    return jsonify(state_machine.get_status())


@app.route('/api/playlists', methods=['GET'])
def api_get_playlists():
    playlists = config_manager.get('playlists', []) if config_manager else []
    return jsonify(playlists)


@app.route('/api/playlists', methods=['POST'])
def api_add_playlist():
    if not config_manager or not spotify_manager:
        return jsonify({'error': 'Not initialized'}), 503

    data = request.get_json(force=True)
    url = data.get('url', '')

    uri = _parse_spotify_url(url)
    if not uri:
        return jsonify({'error': 'Invalid Spotify playlist or album URL'}), 400

    # Check limit
    playlists = config_manager.get('playlists', [])
    if len(playlists) >= config_manager.MAX_PLAYLISTS:
        return jsonify({'error': f'Maximum of {config_manager.MAX_PLAYLISTS} playlists reached'}), 400

    # Fetch playlist info from Spotify
    info = spotify_manager.get_playlist_info(uri)
    if not info:
        return jsonify({'error': 'Could not fetch playlist info from Spotify'}), 400

    name = info['name']
    cover_url = info.get('cover_url', '')

    # Add to config
    config_manager.add_playlist(name=name, uri=uri, cover_url=cover_url)

    # Cache cover art for the display. The cache file is keyed by the
    # Spotify ID (extracted from the URI inside cache_playlist_cover), so
    # this is collision-free across reorder/delete/re-add cycles.
    new_index = len(config_manager.get('playlists', [])) - 1
    if display_manager and cover_url:
        try:
            playlist_ref = config_manager.get('playlists', [])[new_index]
            saved_path = display_manager.cache_playlist_cover(playlist_ref, cover_url)
            if saved_path:
                playlist_ref['cover_cached'] = saved_path
                config_manager.save()
        except Exception as e:
            print(f"[web] Error caching cover art: {e}")

    playlist_entry = config_manager.get('playlists', [])[new_index]
    playlist_entry['track_count'] = info.get('track_count', 0)
    return jsonify(playlist_entry), 201


@app.route('/api/playlists/<int:idx>', methods=['PATCH'])
def api_update_playlist(idx):
    if not config_manager:
        return jsonify({'error': 'Not initialized'}), 503
    data = request.get_json(force=True)
    playlists = config_manager.get('playlists', [])
    if idx < 0 or idx >= len(playlists):
        return jsonify({'error': 'Invalid index'}), 404
    updates = {}
    if 'allowed_periods' in data:
        ap = data['allowed_periods']
        if isinstance(ap, list) and all(p in ('day', 'quiet') for p in ap):
            updates['allowed_periods'] = ap
        else:
            return jsonify({'error': 'Invalid allowed_periods'}), 400
    if updates:
        config_manager.update_playlist(idx, updates)
    return jsonify({'ok': True})


@app.route('/api/playlists/<int:idx>', methods=['DELETE'])
def api_remove_playlist(idx):
    if not config_manager:
        return jsonify({'error': 'Not initialized'}), 503
    try:
        config_manager.remove_playlist(idx)
        return jsonify({'ok': True})
    except (IndexError, KeyError):
        return jsonify({'error': 'Invalid index'}), 400


@app.route('/api/playlists/reorder', methods=['POST'])
def api_reorder_playlists():
    if not config_manager:
        return jsonify({'error': 'Not initialized'}), 503
    data = request.get_json(force=True)
    order = data.get('order', [])
    try:
        config_manager.reorder_playlists(order)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/settings', methods=['POST'])
def api_settings():
    if not config_manager:
        return jsonify({'error': 'Not initialized'}), 503
    data = request.get_json(force=True)

    if 'max_volume' in data:
        config_manager.set('max_volume', int(data['max_volume']))
    if 'volume_step' in data:
        config_manager.set('volume_step', int(data['volume_step']))
    if 'backlight' in data:
        display_cfg = config_manager.get('display', {})
        display_cfg['backlight'] = int(data['backlight'])
        config_manager.set('display', display_cfg)
        if display_manager:
            display_manager.set_backlight(int(data['backlight']))
    if 'webradio_name' in data or 'webradio_url' in data:
        webradio = config_manager.get('webradio', {})
        name = data.get('webradio_name', webradio.get('name', ''))
        url = data.get('webradio_url', webradio.get('url', ''))
        image_path = webradio.get('image_path', '')
        config_manager.update_webradio(name, url, image_path)

    return jsonify({'ok': True})


@app.route('/api/spotify/connect', methods=['POST'])
def api_spotify_connect():
    if not spotify_manager:
        return jsonify({'error': 'Not initialized'}), 503
    data = request.get_json(force=True)
    client_id = data.get('client_id', '')
    client_secret = data.get('client_secret', '')

    if not client_id or not client_secret:
        return jsonify({'error': 'Client ID and secret are required'}), 400

    try:
        auth_url = spotify_manager.get_auth_url(client_id, client_secret)
        return jsonify({'auth_url': auth_url})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/spotify/reauth', methods=['POST'])
def api_spotify_reauth():
    """Start a new OAuth flow using already-saved client_id/secret."""
    if not spotify_manager:
        return jsonify({'error': 'Not initialized'}), 503
    try:
        auth_url = spotify_manager.reauth_url()
        if not auth_url:
            return jsonify({'error': 'No saved credentials'}), 400
        return jsonify({'auth_url': auth_url})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/spotify/logout', methods=['POST'])
def api_spotify_logout():
    """Clear refresh token but keep client_id/secret."""
    if not spotify_manager:
        return jsonify({'error': 'Not initialized'}), 503
    try:
        spotify_manager.logout()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/spotify/clear', methods=['POST'])
def api_spotify_clear():
    """Fully clear Spotify credentials (client_id, secret, refresh_token)."""
    if not spotify_manager:
        return jsonify({'error': 'Not initialized'}), 503
    try:
        spotify_manager.clear_credentials()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ------------------------------------------------------------------
# WiFi API
# ------------------------------------------------------------------

@app.route('/api/wifi/status')
def api_wifi_status():
    """Return current WiFi state + AP active flag."""
    if not wifi_manager:
        return jsonify({'error': 'WiFi manager not initialized'}), 503
    return jsonify(wifi_manager.get_status())


@app.route('/api/wifi/scan', methods=['POST'])
def api_wifi_scan():
    """Scan for available WiFi networks."""
    if not wifi_manager:
        return jsonify({'error': 'WiFi manager not initialized'}), 503
    try:
        networks = wifi_manager.scan()
        return jsonify({'ok': True, 'networks': networks})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/wifi/connect', methods=['POST'])
def api_wifi_connect():
    """Connect to a WiFi network. Body: {ssid, password}."""
    if not wifi_manager:
        return jsonify({'error': 'WiFi manager not initialized'}), 503
    data = request.get_json(force=True)
    ssid = data.get('ssid', '').strip()
    password = data.get('password', '').strip()
    if not ssid:
        return jsonify({'error': 'SSID is required'}), 400
    result = wifi_manager.connect(ssid, password)
    if result['ok']:
        return jsonify(result)
    return jsonify(result), 500


@app.route('/api/wifi/networks', methods=['GET'])
def api_wifi_saved():
    """List saved/known WiFi networks."""
    if not wifi_manager:
        return jsonify({'error': 'WiFi manager not initialized'}), 503
    return jsonify({'networks': wifi_manager.get_saved_networks()})


@app.route('/api/wifi/networks/<name>', methods=['DELETE'])
def api_wifi_forget(name):
    """Forget a saved WiFi network."""
    if not wifi_manager:
        return jsonify({'error': 'WiFi manager not initialized'}), 503
    result = wifi_manager.forget_network(name)
    if result['ok']:
        return jsonify(result)
    return jsonify(result), 500


@app.route('/api/next_mode', methods=['POST'])
def api_next_mode():
    if not state_machine:
        return jsonify({'error': 'Not initialized'}), 503
    state_machine.next_mode()
    return jsonify({'ok': True})


@app.route('/api/prev_mode', methods=['POST'])
def api_prev_mode():
    if not state_machine:
        return jsonify({'error': 'Not initialized'}), 503
    state_machine.prev_mode()
    return jsonify({'ok': True})


@app.route('/api/play_pause', methods=['POST'])
def api_play_pause():
    if not state_machine:
        return jsonify({'error': 'Not initialized'}), 503
    state_machine.play_pause()
    return jsonify({'ok': True})


@app.route('/api/next_track', methods=['POST'])
def api_next_track():
    if not state_machine:
        return jsonify({'error': 'Not initialized'}), 503
    state_machine.next_track()
    return jsonify({'ok': True})


@app.route('/api/prev_track', methods=['POST'])
def api_prev_track():
    if not state_machine:
        return jsonify({'error': 'Not initialized'}), 503
    state_machine.prev_track()
    return jsonify({'ok': True})


@app.route('/api/play/<int:idx>', methods=['POST'])
def api_play(idx):
    if not state_machine:
        return jsonify({'error': 'Not initialized'}), 503
    state_machine.set_mode(idx)
    return jsonify({'ok': True})


@app.route('/api/schedule', methods=['POST'])
def api_schedule():
    if not config_manager:
        return jsonify({'error': 'Not initialized'}), 503
    data = request.get_json(force=True)
    schedule = config_manager.get('schedule', {})
    for key in ('enabled', 'night_start', 'night_end', 'night_backlight',
                'wakeup_start', 'wakeup_end', 'bedtime_start', 'bedtime_end',
                'quiet_max_volume', 'quiet_backlight'):
        if key in data:
            schedule[key] = data[key]
    config_manager.set('schedule', schedule)
    return jsonify({'ok': True})


@app.route('/api/volume', methods=['POST'])
def api_volume():
    if not state_machine:
        return jsonify({'error': 'Not initialized'}), 503
    data = request.get_json(force=True)
    vol = data.get('volume', 50)
    state_machine.set_volume(int(vol))
    return jsonify({'ok': True})


# ------------------------------------------------------------------
# Bluetooth API routes
# ------------------------------------------------------------------

@app.route('/api/bluetooth/scan', methods=['POST'])
def api_bt_scan():
    if not bluetooth_manager:
        return jsonify({'error': 'Bluetooth not available'}), 503
    try:
        devices = bluetooth_manager.scan(duration=8)
        return jsonify(devices)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/bluetooth/devices', methods=['GET'])
def api_bt_devices():
    if not bluetooth_manager:
        return jsonify({'error': 'Bluetooth not available'}), 503
    try:
        devices = bluetooth_manager.get_paired_devices()
        return jsonify(devices)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/bluetooth/pair', methods=['POST'])
def api_bt_pair():
    if not bluetooth_manager:
        return jsonify({'error': 'Bluetooth not available'}), 503
    data = request.get_json(force=True)
    address = data.get('address', '')
    result = bluetooth_manager.pair(address)
    if result.get('ok'):
        return jsonify(result)
    return jsonify(result), 400


@app.route('/api/bluetooth/connect', methods=['POST'])
def api_bt_connect():
    if not bluetooth_manager:
        return jsonify({'error': 'Bluetooth not available'}), 503
    data = request.get_json(force=True)
    address = data.get('address', '')
    result = bluetooth_manager.connect(address)
    if result.get('ok'):
        return jsonify(result)
    return jsonify(result), 400


@app.route('/api/bluetooth/disconnect', methods=['POST'])
def api_bt_disconnect():
    if not bluetooth_manager:
        return jsonify({'error': 'Bluetooth not available'}), 503
    data = request.get_json(force=True)
    address = data.get('address', '')
    result = bluetooth_manager.disconnect(address)
    if result.get('ok'):
        return jsonify(result)
    return jsonify(result), 400


@app.route('/api/bluetooth/devices/<address>', methods=['DELETE'])
def api_bt_forget(address):
    if not bluetooth_manager:
        return jsonify({'error': 'Bluetooth not available'}), 503
    result = bluetooth_manager.forget(address)
    if result.get('ok'):
        return jsonify(result)
    return jsonify(result), 400


# ------------------------------------------------------------------
# Software updates — check GitHub for new commits and trigger update
# ------------------------------------------------------------------

# Repo root: web/app.py is two levels under the project root.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_UPDATE_SCRIPT = os.path.join(_REPO_ROOT, 'scripts', 'manual-update.sh')

# Cache the most recent check so frequent page loads / refreshes don't
# hammer GitHub.
_update_check_cache = {'data': None, 'ts': 0.0}
_UPDATE_CHECK_TTL = 30  # seconds


def _git(args, timeout=10):
    """Run a git command in the repo, return stdout (stripped) or None."""
    try:
        out = subprocess.check_output(
            ['git', '-C', _REPO_ROOT] + args,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return out.decode('utf-8', errors='replace').strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError):
        return None


def _check_for_updates():
    """Compare local HEAD against origin/main. Returns dict for the API."""
    now = time.time()
    cached = _update_check_cache['data']
    if cached and (now - _update_check_cache['ts']) < _UPDATE_CHECK_TTL:
        return cached

    result = {
        'current_sha': None,
        'current_subject': None,
        'latest_sha': None,
        'latest_subject': None,
        'update_available': False,
        'behind_count': 0,
        'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'error': None,
    }

    if not os.path.isdir(os.path.join(_REPO_ROOT, '.git')):
        result['error'] = 'not_a_git_checkout'
        _update_check_cache.update(data=result, ts=now)
        return result

    # Local state — never fail because of this
    head = _git(['rev-parse', 'HEAD'])
    if head:
        result['current_sha'] = head[:7]
        subject = _git(['log', '-1', '--pretty=%s', 'HEAD'])
        if subject:
            result['current_subject'] = subject

    # Fetch latest refs (silent). Short timeout so the UI never hangs long.
    fetch_out = _git(['fetch', '--quiet', 'origin', 'main'], timeout=10)
    if fetch_out is None:
        result['error'] = 'offline'
        _update_check_cache.update(data=result, ts=now)
        return result

    remote = _git(['rev-parse', 'origin/main'])
    if not remote:
        result['error'] = 'no_remote_ref'
        _update_check_cache.update(data=result, ts=now)
        return result
    result['latest_sha'] = remote[:7]
    remote_subject = _git(['log', '-1', '--pretty=%s', 'origin/main'])
    if remote_subject:
        result['latest_subject'] = remote_subject

    # Count commits we're behind
    behind = _git(['rev-list', '--count', 'HEAD..origin/main'])
    try:
        result['behind_count'] = int(behind) if behind else 0
    except ValueError:
        result['behind_count'] = 0
    result['update_available'] = result['behind_count'] > 0

    _update_check_cache.update(data=result, ts=now)
    return result


@app.route('/api/update/check', methods=['GET'])
def api_update_check():
    if request.args.get('refresh') == '1':
        _update_check_cache['data'] = None  # bust cache on explicit refresh
    return jsonify(_check_for_updates())


@app.route('/api/update/start', methods=['POST'])
def api_update_start():
    """Kick off the manual update via systemd-run so it survives Flask
    restarting itself. Returns immediately."""
    if not os.path.isfile(_UPDATE_SCRIPT):
        return jsonify({'started': False,
                        'error': 'update script missing'}), 500

    cmd = [
        'sudo', '-n',
        '/usr/bin/systemd-run',
        '--unit=flockify-manual-update',
        '--collect',
        _UPDATE_SCRIPT,
    ]
    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=10)
    except subprocess.CalledProcessError as e:
        return jsonify({
            'started': False,
            'error': e.output.decode('utf-8', errors='replace').strip()
                     or 'systemd-run failed',
        }), 500
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return jsonify({'started': False, 'error': str(e)}), 500

    # Bust the cache so the next check after restart shows the new SHA.
    _update_check_cache['data'] = None
    return jsonify({'started': True})
