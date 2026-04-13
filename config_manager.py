import json
import os
import shutil


class ConfigManager:
    """Manages configuration for Flockify Box."""

    MAX_PLAYLISTS = 10

    def __init__(self, config_path='config.json', default_path='config_default.json'):
        self.config_path = config_path
        self.default_path = default_path
        self.config = {}
        self.load()

    def load(self):
        """Load config.json. If missing, copy config_default.json first."""
        if not os.path.exists(self.config_path):
            shutil.copy2(self.default_path, self.config_path)
        with open(self.config_path, 'r') as f:
            self.config = json.load(f)
        return self.config

    def save(self):
        """Write config atomically via temp file + os.replace."""
        tmp_path = '.config.json.tmp'
        with open(tmp_path, 'w') as f:
            json.dump(self.config, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, self.config_path)

    def get(self, key, default=None):
        """Get a top-level config value."""
        return self.config.get(key, default)

    def set(self, key, value):
        """Set a top-level config value and auto-save."""
        self.config[key] = value
        self.save()

    def add_playlist(self, name, uri, cover_url, cover_cached='', allowed_periods=None):
        """Add a playlist entry (max 10)."""
        playlists = self.config.setdefault('playlists', [])
        if len(playlists) >= self.MAX_PLAYLISTS:
            raise ValueError(f"Maximum of {self.MAX_PLAYLISTS} playlists reached")
        playlists.append({
            'name': name,
            'uri': uri,
            'cover_url': cover_url,
            'cover_cached': cover_cached,
            'allowed_periods': allowed_periods if allowed_periods is not None else ['day', 'quiet'],
        })
        self.save()

    def update_playlist(self, index, updates):
        """Update fields on a playlist by index. Only updates provided keys."""
        playlists = self.get('playlists', [])
        if 0 <= index < len(playlists):
            for key in ('allowed_periods',):
                if key in updates:
                    playlists[index][key] = updates[key]
            self.set('playlists', playlists)

    def remove_playlist(self, index):
        """Remove a playlist by index."""
        del self.config['playlists'][index]
        self.save()

    def reorder_playlists(self, new_order):
        """Reorder playlists given a list of indices."""
        playlists = self.config['playlists']
        self.config['playlists'] = [playlists[i] for i in new_order]
        self.save()

    def update_webradio(self, name, url, image_path):
        """Update webradio config."""
        self.config['webradio'] = {
            'name': name,
            'url': url,
            'image_path': image_path,
        }
        self.save()

    def update_spotify_credentials(self, client_id, client_secret, refresh_token=''):
        """Update spotify credentials."""
        spotify = self.config.setdefault('spotify', {})
        spotify['client_id'] = client_id
        spotify['client_secret'] = client_secret
        if refresh_token:
            spotify['refresh_token'] = refresh_token
        self.save()

    def save_state(self, mode_index, volume):
        """Update current playback state and save.

        Re-reads the latest config from disk before writing so that
        external modifications to other fields (e.g. a migration script
        or an admin command) are not clobbered. Only the 'state' field
        is overwritten; everything else is preserved as it is on disk.
        """
        new_state = {
            'mode_index': mode_index,
            'volume': volume,
        }
        # Try to merge with the latest disk version first
        try:
            with open(self.config_path, 'r') as f:
                disk_config = json.load(f)
            disk_config['state'] = new_state
            self.config = disk_config  # adopt the freshest view
        except Exception:
            # Disk read failed for some reason; fall back to in-memory
            self.config['state'] = new_state
        self.save()

    def get_state(self):
        """Return current state dict."""
        return self.config.get('state', {'mode_index': 0, 'volume': 50})
