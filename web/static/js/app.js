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

    window.reconnectSpotify = function () {
        api('POST', '/api/spotify/reauth').then(function (data) {
            if (data.auth_url) {
                window.location.href = data.auth_url;
            }
        }).catch(function (err) {
            showError('spotify-error', err.message);
        });
    };

    window.logoutSpotify = function () {
        if (!confirm('Disconnect from Spotify? Your Client ID and Secret will be kept so you can reconnect easily.')) return;
        api('POST', '/api/spotify/logout').then(function () {
            window.location.reload();
        }).catch(function (err) {
            showError('spotify-error', err.message);
        });
    };

    window.clearSpotify = function () {
        if (!confirm('Clear all Spotify credentials? You will need to enter Client ID and Secret again.')) return;
        api('POST', '/api/spotify/clear').then(function () {
            window.location.reload();
        }).catch(function (err) {
            showError('spotify-error', err.message);
        });
    };

    // ------------------------------------------------------------------
    // WiFi
    // ------------------------------------------------------------------

    window.scanWifi = function () {
        var btn = document.getElementById('btn-wifi-scan');
        var status = document.getElementById('wifi-scan-status');
        var results = document.getElementById('wifi-scan-results');
        if (btn) btn.disabled = true;
        if (status) status.style.display = '';
        if (results) results.style.display = 'none';

        api('POST', '/api/wifi/scan').then(function (data) {
            if (status) status.style.display = 'none';
            if (btn) btn.disabled = false;
            if (!data.networks || !data.networks.length) {
                if (results) {
                    results.innerHTML = '<p style="color:#888;">No networks found</p>';
                    results.style.display = '';
                }
                return;
            }
            var html = '';
            data.networks.forEach(function (net) {
                var bars = net.signal > 75 ? '▂▄▆█' : net.signal > 50 ? '▂▄▆_' : net.signal > 25 ? '▂▄__' : '▂___';
                var sec = net.security || 'Open';
                var inUse = net.in_use ? ' <span class="badge badge-green" style="font-size:0.75em;">Connected</span>' : '';
                html += '<div class="bt-device-row" style="flex-wrap:wrap;">' +
                    '<span class="bt-device-name">' + net.ssid + inUse + '</span>' +
                    '<span style="color:#888;font-size:0.85em;margin-right:8px;">' + bars + ' ' + sec + '</span>' +
                    '<button class="btn btn-primary btn-sm" onclick="showWifiPassword(\'' +
                        net.ssid.replace(/'/g, "\\'") + '\', this)">Connect</button>' +
                    '<div class="wifi-pw-form" style="display:none;width:100%;margin-top:8px;">' +
                        '<input type="password" class="input" placeholder="Password" style="margin-bottom:4px;">' +
                        '<button class="btn btn-primary btn-sm" onclick="connectWifi(\'' +
                            net.ssid.replace(/'/g, "\\'") + '\', this)">Join</button>' +
                    '</div>' +
                    '</div>';
            });
            if (results) {
                results.innerHTML = html;
                results.style.display = '';
            }
        }).catch(function (err) {
            if (status) status.style.display = 'none';
            if (btn) btn.disabled = false;
            showError('wifi-error', err.message);
        });
    };

    window.showWifiPassword = function (ssid, btn) {
        var row = btn.closest('.bt-device-row');
        var form = row.querySelector('.wifi-pw-form');
        if (form) {
            form.style.display = form.style.display === 'none' ? '' : 'none';
            var input = form.querySelector('input');
            if (input) input.focus();
        }
    };

    window.connectWifi = function (ssid, btn) {
        var form = btn.closest('.wifi-pw-form');
        var input = form.querySelector('input');
        var password = input ? input.value : '';

        // Show connecting message immediately — the HTTP connection may
        // drop if we're on the AP and it gets torn down.
        var results = document.getElementById('wifi-scan-results');
        if (results) {
            results.innerHTML = '<div style="padding:16px;text-align:center;">' +
                '<p><strong>Connecting to ' + ssid + '...</strong></p>' +
                '<p style="color:#888;margin-top:8px;">If successful, this page will stop responding.<br>' +
                'Connect your phone to <strong>' + ssid + '</strong> and visit<br>' +
                '<strong>http://flockifybox.local:5000</strong> to continue.</p>' +
                '</div>';
        }

        // Fire-and-forget — we may lose the connection.
        fetch('/api/wifi/connect', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ssid: ssid, password: password})
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (data.ok) {
                showSuccess('wifi-success', 'Connected to ' + ssid + '!');
                setTimeout(function () { window.location.reload(); }, 3000);
            } else {
                showError('wifi-error', data.error || 'Connection failed');
                scanWifi(); // refresh the list
            }
        }).catch(function () {
            // Expected when AP is torn down — connection lost is success.
        });
    };

    window.forgetWifi = function (name) {
        if (!confirm('Forget network "' + name + '"?')) return;
        api('DELETE', '/api/wifi/networks/' + encodeURIComponent(name)).then(function () {
            window.location.reload();
        }).catch(function (err) {
            showError('wifi-error', err.message);
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
    // Schedule
    // ------------------------------------------------------------------

    window.saveSchedule = function () {
        var data = {
            enabled: document.getElementById('schedule-enabled').checked,
            night_start: document.getElementById('night-start').value,
            night_end: document.getElementById('night-end').value,
            wakeup_start: document.getElementById('wakeup-start').value,
            wakeup_end: document.getElementById('wakeup-end').value,
            bedtime_start: document.getElementById('bedtime-start').value,
            bedtime_end: document.getElementById('bedtime-end').value,
            quiet_max_volume: parseInt(document.getElementById('quiet-max-volume').value, 10),
            quiet_backlight: parseInt(document.getElementById('quiet-backlight').value, 10),
            night_backlight: parseInt(document.getElementById('night-backlight').value, 10)
        };
        api('POST', '/api/schedule', data).then(function () {
            showSuccess('schedule-success', 'Schedule saved');
        }).catch(function (err) {
            showError('schedule-error', err.message);
        });
    };

    function initScheduleSliders() {
        var pairs = [
            ['quiet-max-volume', 'quiet-vol-value'],
            ['quiet-backlight', 'quiet-bl-value'],
            ['night-backlight', 'night-bl-value']
        ];
        pairs.forEach(function (p) {
            var slider = document.getElementById(p[0]);
            var display = document.getElementById(p[1]);
            if (slider && display) {
                slider.addEventListener('input', function () {
                    display.textContent = slider.value;
                });
            }
        });

        // Toggle schedule fields visibility
        var toggle = document.getElementById('schedule-enabled');
        var fields = document.getElementById('schedule-fields');
        if (toggle && fields) {
            fields.style.display = toggle.checked ? '' : 'none';
            toggle.addEventListener('change', function () {
                fields.style.display = toggle.checked ? '' : 'none';
            });
        }
    }

    // ------------------------------------------------------------------
    // Bluetooth
    // ------------------------------------------------------------------

    window.scanBluetooth = function () {
        var btn = document.getElementById('btn-bt-scan');
        var status = document.getElementById('bt-scan-status');
        var results = document.getElementById('bt-scan-results');

        btn.classList.add('loading');
        btn.textContent = 'Scanning...';
        status.style.display = 'block';
        results.style.display = 'none';

        api('POST', '/api/bluetooth/scan').then(function (devices) {
            btn.classList.remove('loading');
            btn.textContent = 'Scan for Devices';
            status.style.display = 'none';

            // Show results
            while (results.firstChild) results.removeChild(results.firstChild);

            var unpaired = devices.filter(function (d) { return !d.paired; });
            if (unpaired.length === 0) {
                var p = document.createElement('p');
                p.className = 'bt-no-device';
                p.textContent = 'No new devices found';
                results.appendChild(p);
            } else {
                unpaired.forEach(function (dev) {
                    var row = document.createElement('div');
                    row.className = 'bt-device-row';

                    var name = document.createElement('span');
                    name.className = 'bt-device-name';
                    name.textContent = dev.name;
                    row.appendChild(name);

                    var pairBtn = document.createElement('button');
                    pairBtn.className = 'btn btn-primary btn-sm';
                    pairBtn.textContent = 'Pair';
                    pairBtn.onclick = function () { pairBt(dev.address, pairBtn); };
                    row.appendChild(pairBtn);

                    results.appendChild(row);
                });
            }
            results.style.display = 'block';
        }).catch(function (err) {
            btn.classList.remove('loading');
            btn.textContent = 'Scan for Devices';
            status.style.display = 'none';
            showError('bt-error', err.message);
        });
    };

    function pairBt(address, btn) {
        btn.classList.add('loading');
        btn.textContent = 'Pairing...';

        api('POST', '/api/bluetooth/pair', { address: address }).then(function () {
            showSuccess('bt-success', 'Device paired and connected');
            setTimeout(function () { window.location.reload(); }, 1000);
        }).catch(function (err) {
            btn.classList.remove('loading');
            btn.textContent = 'Pair';
            showError('bt-error', err.message);
        });
    }

    window.connectBt = function (address) {
        api('POST', '/api/bluetooth/connect', { address: address }).then(function () {
            showSuccess('bt-success', 'Connected');
            setTimeout(function () { window.location.reload(); }, 1000);
        }).catch(function (err) {
            showError('bt-error', err.message);
        });
    };

    window.disconnectBt = function (address) {
        api('POST', '/api/bluetooth/disconnect', { address: address }).then(function () {
            showSuccess('bt-success', 'Disconnected');
            setTimeout(function () { window.location.reload(); }, 1000);
        }).catch(function (err) {
            showError('bt-error', err.message);
        });
    };

    window.forgetBt = function (address) {
        if (!confirm('Forget this device?')) return;
        api('DELETE', '/api/bluetooth/devices/' + encodeURIComponent(address)).then(function () {
            showSuccess('bt-success', 'Device removed');
            setTimeout(function () { window.location.reload(); }, 1000);
        }).catch(function (err) {
            showError('bt-error', err.message);
        });
    };

    // ------------------------------------------------------------------
    // Playlists — Update period restrictions
    // ------------------------------------------------------------------

    window.updatePlaylistPeriods = function (idx) {
        var row = document.querySelectorAll('.playlist-item')[idx];
        var checkboxes = row.querySelectorAll('.playlist-periods input[type="checkbox"]');
        var periods = [];
        if (checkboxes[0] && checkboxes[0].checked) periods.push('day');
        if (checkboxes[1] && checkboxes[1].checked) periods.push('quiet');

        api('PATCH', '/api/playlists/' + idx, { allowed_periods: periods })
            .catch(function (err) { alert('Failed to save: ' + err.message); });
    };

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

        // Schedule: bind sliders and toggle
        if (document.getElementById('schedule-enabled')) {
            initScheduleSliders();
        }
    });

})();
