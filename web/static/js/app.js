/* ================================================================
   Flockify Box — Frontend JavaScript
   Vanilla JS, no dependencies. Polls status every 3 seconds on the
   dashboard; handles playlist management and settings forms.
   ================================================================ */

(function () {
    'use strict';

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------

    function api(method, path, body) {
        var opts = {
            method: method,
            headers: { 'Content-Type': 'application/json' }
        };
        if (body !== undefined) {
            opts.body = JSON.stringify(body);
        }
        return fetch(path, opts).then(function (res) {
            return res.json().then(function (data) {
                if (!res.ok) {
                    throw new Error(data.error || 'Request failed');
                }
                return data;
            });
        });
    }

    function showError(id, message) {
        var el = document.getElementById(id);
        if (!el) return;
        el.textContent = message;
        el.style.display = 'block';
        setTimeout(function () { el.style.display = 'none'; }, 5000);
    }

    function showSuccess(id, message) {
        var el = document.getElementById(id);
        if (!el) return;
        el.textContent = message || 'Saved';
        el.style.display = 'block';
        setTimeout(function () { el.style.display = 'none'; }, 3000);
    }

    // Simple debounce
    function debounce(fn, delay) {
        var timer;
        return function () {
            var args = arguments;
            var ctx = this;
            clearTimeout(timer);
            timer = setTimeout(function () { fn.apply(ctx, args); }, delay);
        };
    }

    // Create an SVG icon element safely (no innerHTML)
    function createSvgIcon(pathData) {
        var ns = 'http://www.w3.org/2000/svg';
        var svg = document.createElementNS(ns, 'svg');
        svg.setAttribute('class', 'icon');
        svg.setAttribute('viewBox', '0 0 24 24');
        svg.setAttribute('width', '18');
        svg.setAttribute('height', '18');
        svg.setAttribute('fill', 'currentColor');
        var path = document.createElementNS(ns, 'path');
        path.setAttribute('d', pathData);
        svg.appendChild(path);
        return svg;
    }

    var ICON_BLUETOOTH = 'M17.71 7.71L12 2h-1v7.59L6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 11 14.41V22h1l5.71-5.71-4.3-4.29 4.3-4.29zM13 5.83l1.88 1.88L13 9.59V5.83zm1.88 10.46L13 18.17v-3.76l1.88 1.88z';
    var ICON_SPEAKER = 'M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z';

    // ------------------------------------------------------------------
    // Dashboard — Status polling
    // ------------------------------------------------------------------

    var statusInterval = null;

    function fetchStatus() {
        api('GET', '/api/status').then(function (s) {
            // Mode badge
            var badge = document.getElementById('mode-badge');
            if (badge) {
                badge.textContent = s.mode === 'webradio' ? 'Web Radio' : 'Spotify';
                badge.className = 'mode-badge' + (s.mode === 'webradio' ? ' webradio' : '');
            }

            // Playlist / station name
            var name = document.getElementById('playlist-name');
            if (name) {
                name.textContent = s.playlist_name || '--';
            }

            // Track info (Spotify only)
            var trackInfo = document.getElementById('track-info');
            if (trackInfo) {
                if (s.mode === 'spotify' && s.track) {
                    trackInfo.style.display = '';
                    document.getElementById('track-name').textContent = s.track.name || '';
                    document.getElementById('track-artist').textContent = s.track.artist || '';
                } else {
                    trackInfo.style.display = 'none';
                }
            }

            // Audio output (safe DOM construction, no innerHTML)
            var output = document.getElementById('audio-output');
            if (output) {
                while (output.firstChild) {
                    output.removeChild(output.firstChild);
                }
                var isBT = s.audio_output === 'bluetooth';
                output.appendChild(createSvgIcon(isBT ? ICON_BLUETOOTH : ICON_SPEAKER));
                output.appendChild(document.createTextNode(' ' + (isBT ? 'Bluetooth' : 'Speaker')));
            }

            // Volume slider
            var slider = document.getElementById('volume-slider');
            if (slider && !slider.matches(':active')) {
                slider.max = s.max_volume || 80;
                slider.value = s.volume;
            }
            var volVal = document.getElementById('volume-value');
            if (volVal && slider && !slider.matches(':active')) {
                volVal.textContent = s.volume;
            }

            // Mode indicator
            var indicator = document.getElementById('mode-indicator');
            if (indicator) {
                indicator.textContent = (s.mode_index + 1);
            }
        }).catch(function () {
            // Silently retry on next poll
        });
    }

    // ------------------------------------------------------------------
    // Dashboard — Volume control
    // ------------------------------------------------------------------

    var sendVolume = debounce(function (val) {
        api('POST', '/api/volume', { volume: parseInt(val, 10) });
    }, 200);

    function initVolumeSlider() {
        var slider = document.getElementById('volume-slider');
        if (!slider) return;
        slider.addEventListener('input', function () {
            var volVal = document.getElementById('volume-value');
            if (volVal) volVal.textContent = slider.value;
            sendVolume(slider.value);
        });
    }

    // ------------------------------------------------------------------
    // Dashboard — Mode navigation
    // ------------------------------------------------------------------

    window.nextMode = function () {
        api('POST', '/api/next_mode').then(function () {
            setTimeout(fetchStatus, 500);
        });
    };

    window.prevMode = function () {
        api('GET', '/api/status').then(function (s) {
            var total = (s.total_modes || 1);
            var prev = (s.mode_index - 1 + total) % total;
            api('POST', '/api/play/' + prev);
            setTimeout(fetchStatus, 500);
        });
    };

    // ------------------------------------------------------------------
    // Playlists — Add
    // ------------------------------------------------------------------

    window.addPlaylist = function (e) {
        e.preventDefault();
        var input = document.getElementById('playlist-url');
        var btn = document.getElementById('btn-add-playlist');
        var url = input.value.trim();
        if (!url) return;

        btn.classList.add('loading');
        btn.textContent = 'Adding...';

        api('POST', '/api/playlists', { url: url }).then(function () {
            window.location.reload();
        }).catch(function (err) {
            showError('playlist-error', err.message);
            btn.classList.remove('loading');
            btn.textContent = 'Add';
        });
    };

    // ------------------------------------------------------------------
    // Playlists — Remove
    // ------------------------------------------------------------------

    window.removePlaylist = function (idx) {
        if (!confirm('Remove this playlist?')) return;
        api('DELETE', '/api/playlists/' + idx).then(function () {
            window.location.reload();
        }).catch(function (err) {
            showError('playlist-error', err.message);
        });
    };

    // ------------------------------------------------------------------
    // Playlists — Reorder (move up/down)
    // ------------------------------------------------------------------

    window.movePlaylist = function (fromIdx, toIdx) {
        // Build a new order array by swapping
        api('GET', '/api/playlists').then(function (playlists) {
            var order = [];
            for (var i = 0; i < playlists.length; i++) {
                order.push(i);
            }
            // Swap
            order[fromIdx] = toIdx;
            order[toIdx] = fromIdx;

            api('POST', '/api/playlists/reorder', { order: order }).then(function () {
                window.location.reload();
            }).catch(function (err) {
                showError('playlist-error', err.message);
            });
        });
    };

    // ------------------------------------------------------------------
    // Playlists — Save webradio
    // ------------------------------------------------------------------

    window.saveWebradio = function (e) {
        e.preventDefault();
        var name = document.getElementById('webradio-name').value.trim();
        var url = document.getElementById('webradio-url').value.trim();

        api('POST', '/api/settings', {
            webradio_name: name,
            webradio_url: url
        }).then(function () {
            showSuccess('webradio-success', 'Saved');
        }).catch(function (err) {
            showError('webradio-error', err.message);
        });
    };

    // ------------------------------------------------------------------
    // Settings — Save
    // ------------------------------------------------------------------

    window.saveSettings = function () {
        var maxVolume = document.getElementById('max-volume');
        var volumeStep = document.getElementById('volume-step');
        var backlight = document.getElementById('backlight');

        var data = {};
        if (maxVolume) data.max_volume = parseInt(maxVolume.value, 10);
        if (volumeStep) data.volume_step = parseInt(volumeStep.value, 10);
        if (backlight) data.backlight = parseInt(backlight.value, 10);

        api('POST', '/api/settings', data).then(function () {
            showSuccess('settings-success', 'Settings saved');
        }).catch(function (err) {
            showError('settings-error', err.message);
        });
    };

    // ------------------------------------------------------------------
    // Settings — Spotify connect
    // ------------------------------------------------------------------

    window.connectSpotify = function (e) {
        e.preventDefault();
        var clientId = document.getElementById('client-id').value.trim();
        var clientSecret = document.getElementById('client-secret').value.trim();

        if (!clientId || !clientSecret) {
            showError('spotify-error', 'Both Client ID and Client Secret are required');
            return;
        }

        api('POST', '/api/spotify/connect', {
            client_id: clientId,
            client_secret: clientSecret
        }).then(function (data) {
            if (data.auth_url) {
                window.location.href = data.auth_url;
            }
        }).catch(function (err) {
            showError('spotify-error', err.message);
        });
    };

    // ------------------------------------------------------------------
    // Settings — Slider value display updates
    // ------------------------------------------------------------------

    function initSettingsSliders() {
        var maxVolume = document.getElementById('max-volume');
        var maxVolumeVal = document.getElementById('max-volume-value');
        if (maxVolume && maxVolumeVal) {
            maxVolume.addEventListener('input', function () {
                maxVolumeVal.textContent = maxVolume.value;
            });
        }

        var backlight = document.getElementById('backlight');
        var backlightVal = document.getElementById('backlight-value');
        if (backlight && backlightVal) {
            backlight.addEventListener('input', function () {
                backlightVal.textContent = backlight.value;
            });
        }
    }

    // ------------------------------------------------------------------
    // Init
    // ------------------------------------------------------------------

    document.addEventListener('DOMContentLoaded', function () {
        // Dashboard: start polling and bind volume slider
        if (document.getElementById('volume-slider')) {
            initVolumeSlider();
            fetchStatus();
            statusInterval = setInterval(fetchStatus, 3000);
        }

        // Settings: bind slider display updates
        if (document.getElementById('max-volume')) {
            initSettingsSliders();
        }
    });

})();
