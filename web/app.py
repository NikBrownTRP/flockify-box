"""
Flask web application for Flockify Box.

Provides a mobile-friendly dashboard, playlist management, and settings UI,
plus a REST API consumed by the frontend JavaScript.
"""

import re
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


def init_app(sm, cm, spm, dm=None, bm=None):
    """Initialize app with references to subsystems."""
    global state_machine, config_manager, spotify_manager, display_manager, bluetooth_manager
    state_machine = sm
    config_manager = cm
    spotify_manager = spm
    display_manager = dm
    bluetooth_manager = bm


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_spotify_url(url):
    """Extract a Spotify playlist URI from a URL or URI string.

    Accepts:
      - https://open.spotify.com/playlist/37i9dQZF1DX6z20IXmBjWI?si=...
      - spotify:playlist:37i9dQZF1DX6z20IXmBjWI

    Returns 'spotify:playlist:<id>' or None on failure.
    """
    url = url.strip()

    # Already a URI
    if url.startswith('spotify:playlist:'):
        return url

    # URL form
    parsed = urlparse(url)
    match = re.match(r'^/playlist/([A-Za-z0-9]+)', parsed.path)
    if match:
        return f'spotify:playlist:{match.group(1)}'

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
    spotify_connected = spotify_manager.is_connected() if spotify_manager and spotify_configured else False
    device_name = config.get('spotify', {}).get('device_name', 'flockifybox')
    bt_connected = None
    bt_paired = []
    if bluetooth_manager:
        bt_connected = bluetooth_manager.get_connected_device()
        bt_paired = bluetooth_manager.get_paired_devices()
    return render_template('settings.html',
                           config=config,
                           spotify_configured=spotify_configured,
                           spotify_connected=spotify_connected,
                           device_name=device_name,
                           bt_connected=bt_connected,
                           bt_paired=bt_paired)


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
        return jsonify({'error': 'Invalid Spotify playlist URL'}), 400

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

    # Cache cover art for the display
    new_index = len(config_manager.get('playlists', [])) - 1
    if display_manager and cover_url:
        try:
            playlist_ref = config_manager.get('playlists', [])[new_index]
            playlist_ref['index'] = new_index
            saved_path = display_manager.cache_playlist_cover(playlist_ref, cover_url)
            if saved_path:
                playlist_ref['cover_cached'] = saved_path
                config_manager.save()
        except Exception as e:
            print(f"[web] Error caching cover art: {e}")

    playlist_entry = config_manager.get('playlists', [])[new_index]
    playlist_entry['track_count'] = info.get('track_count', 0)
    return jsonify(playlist_entry), 201


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


@app.route('/api/next_mode', methods=['POST'])
def api_next_mode():
    if not state_machine:
        return jsonify({'error': 'Not initialized'}), 503
    state_machine.next_mode()
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
