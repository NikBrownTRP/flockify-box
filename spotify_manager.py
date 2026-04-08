import time

import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth


SCOPES = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "playlist-read-private "
    "user-read-currently-playing"
)

TOKEN_CACHE_PATH = ".spotify_token_cache"


class SpotifyManager:
    """Spotify Web API integration using spotipy."""

    def __init__(self, config_manager):
        self.config = config_manager
        self.sp = None
        self._device_id = None

        if self.is_configured():
            try:
                self._init_client()
            except Exception as e:
                print(f"[SpotifyManager] Failed to initialize client: {e}")

    def is_configured(self):
        """Return True if client_id, client_secret, and refresh_token are all set."""
        spotify = self.config.get("spotify", {})
        return bool(
            spotify.get("client_id")
            and spotify.get("client_secret")
            and spotify.get("refresh_token")
        )

    def has_credentials(self):
        """Return True if client_id and client_secret are saved (refresh token may be absent)."""
        spotify = self.config.get("spotify", {})
        return bool(spotify.get("client_id") and spotify.get("client_secret"))

    def logout(self):
        """Clear refresh token + token cache. Keeps client_id/secret for re-auth."""
        import os
        spotify = self.config.get("spotify", {})
        client_id = spotify.get("client_id", "")
        client_secret = spotify.get("client_secret", "")
        # Overwrite with empty refresh_token
        spotify["refresh_token"] = ""
        self.config.set("spotify", spotify)
        # Delete token cache file
        try:
            if os.path.exists(TOKEN_CACHE_PATH):
                os.remove(TOKEN_CACHE_PATH)
        except OSError as e:
            print(f"[SpotifyManager] Could not delete token cache: {e}")
        self.sp = None
        self._device_id = None

    def clear_credentials(self):
        """Fully clear Spotify credentials (client_id, secret, refresh_token)."""
        import os
        self.config.update_spotify_credentials("", "", refresh_token="")
        # update_spotify_credentials doesn't clear refresh_token if empty, so force-set it
        spotify = self.config.get("spotify", {})
        spotify["refresh_token"] = ""
        self.config.set("spotify", spotify)
        try:
            if os.path.exists(TOKEN_CACHE_PATH):
                os.remove(TOKEN_CACHE_PATH)
        except OSError as e:
            print(f"[SpotifyManager] Could not delete token cache: {e}")
        self.sp = None
        self._device_id = None

    def reauth_url(self):
        """Return a fresh Spotify authorization URL using saved credentials."""
        spotify = self.config.get("spotify", {})
        client_id = spotify.get("client_id", "")
        client_secret = spotify.get("client_secret", "")
        if not (client_id and client_secret):
            return None
        auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=spotify.get("redirect_uri", "http://127.0.0.1:5000/callback"),
            scope=SCOPES,
            open_browser=False,
            cache_path=TOKEN_CACHE_PATH,
        )
        return auth_manager.get_authorize_url()

    def _init_client(self):
        """Create spotipy.Spotify client using SpotifyOAuth with cached token."""
        spotify = self.config.get("spotify", {})
        auth_manager = SpotifyOAuth(
            client_id=spotify["client_id"],
            client_secret=spotify["client_secret"],
            redirect_uri=spotify.get("redirect_uri", "http://flockifybox.local:5000/callback"),
            scope=SCOPES,
            open_browser=False,
            cache_path=TOKEN_CACHE_PATH,
        )
        self.sp = spotipy.Spotify(auth_manager=auth_manager)

    def get_auth_url(self, client_id, client_secret):
        """Return the Spotify authorization URL for OAuth flow.

        Saves client_id and client_secret to config for later use.
        """
        self.config.update_spotify_credentials(client_id, client_secret)
        spotify = self.config.get("spotify", {})
        auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=spotify.get("redirect_uri", "http://flockifybox.local:5000/callback"),
            scope=SCOPES,
            open_browser=False,
            cache_path=TOKEN_CACHE_PATH,
        )
        return auth_manager.get_authorize_url()

    def handle_callback(self, code):
        """Exchange authorization code for tokens, save refresh_token, init client.

        Returns True on success, False on failure.
        """
        try:
            spotify = self.config.get("spotify", {})
            auth_manager = SpotifyOAuth(
                client_id=spotify["client_id"],
                client_secret=spotify["client_secret"],
                redirect_uri=spotify.get("redirect_uri", "http://flockifybox.local:5000/callback"),
                scope=SCOPES,
                open_browser=False,
                cache_path=TOKEN_CACHE_PATH,
            )
            token_info = auth_manager.get_access_token(code, as_dict=True)
            refresh_token = token_info.get("refresh_token", "")
            if refresh_token:
                self.config.update_spotify_credentials(
                    spotify["client_id"],
                    spotify["client_secret"],
                    refresh_token=refresh_token,
                )
            self._init_client()
            return True
        except Exception as e:
            print(f"[SpotifyManager] OAuth callback failed: {e}")
            return False

    def find_device(self, retries=10, delay=2):
        """Discover Raspotify device by name from config.

        Raspotify typically takes 10-20 seconds after starting before it
        publishes itself to the Spotify API, so we retry generously to
        handle the startup race at boot.

        Returns device_id or None.
        """
        if not self.sp:
            return None

        device_name = self.config.get("spotify", {}).get("device_name", "flockifybox")

        for attempt in range(retries):
            try:
                result = self.sp.devices()
                devices = result.get("devices", [])
                for device in devices:
                    if device.get("name", "").lower() == device_name.lower():
                        self._device_id = device["id"]
                        return self._device_id
            except spotipy.exceptions.SpotifyException as e:
                print(f"[SpotifyManager] Spotify API error finding device: {e}")
            except requests.exceptions.ConnectionError as e:
                print(f"[SpotifyManager] Connection error finding device: {e}")

            if attempt < retries - 1:
                time.sleep(delay)

        return None

    def play_playlist(self, uri):
        """Start playlist on Raspotify device. Returns True/False."""
        if not self.sp:
            return False
        try:
            device_id = self.find_device()
            if not device_id:
                print("[SpotifyManager] No device found for playback")
                return False
            self.sp.start_playback(device_id=device_id, context_uri=uri)
            return True
        except spotipy.exceptions.SpotifyException as e:
            print(f"[SpotifyManager] Error starting playlist: {e}")
            return False
        except requests.exceptions.ConnectionError as e:
            print(f"[SpotifyManager] Connection error starting playlist: {e}")
            return False

    def next_track(self):
        """Skip to next track. Returns True/False."""
        if not self.sp:
            return False
        try:
            device_id = self._device_id or self.find_device()
            if not device_id:
                return False
            self.sp.next_track(device_id=device_id)
            return True
        except spotipy.exceptions.SpotifyException as e:
            print(f"[SpotifyManager] Error skipping track: {e}")
            return False
        except requests.exceptions.ConnectionError as e:
            print(f"[SpotifyManager] Connection error skipping track: {e}")
            return False

    def previous_track(self):
        """Go to previous track. Returns True/False."""
        if not self.sp:
            return False
        try:
            device_id = self._device_id or self.find_device()
            if not device_id:
                return False
            self.sp.previous_track(device_id=device_id)
            return True
        except spotipy.exceptions.SpotifyException as e:
            print(f"[SpotifyManager] Error going to previous track: {e}")
            return False
        except requests.exceptions.ConnectionError as e:
            print(f"[SpotifyManager] Connection error going to previous track: {e}")
            return False

    def pause(self):
        """Pause playback. Returns True/False."""
        if not self.sp:
            return False
        try:
            device_id = self._device_id or self.find_device()
            if not device_id:
                return False
            self.sp.pause_playback(device_id=device_id)
            return True
        except spotipy.exceptions.SpotifyException as e:
            print(f"[SpotifyManager] Error pausing: {e}")
            return False
        except requests.exceptions.ConnectionError as e:
            print(f"[SpotifyManager] Connection error pausing: {e}")
            return False

    def resume(self):
        """Resume playback. Returns True/False."""
        if not self.sp:
            return False
        try:
            device_id = self._device_id or self.find_device()
            if not device_id:
                return False
            self.sp.start_playback(device_id=device_id)
            return True
        except spotipy.exceptions.SpotifyException as e:
            print(f"[SpotifyManager] Error resuming: {e}")
            return False
        except requests.exceptions.ConnectionError as e:
            print(f"[SpotifyManager] Connection error resuming: {e}")
            return False

    def set_volume(self, level):
        """Set volume (0-100). Returns True/False."""
        if not self.sp:
            return False
        try:
            device_id = self._device_id or self.find_device()
            if not device_id:
                return False
            level = max(0, min(100, int(level)))
            self.sp.volume(level, device_id=device_id)
            return True
        except spotipy.exceptions.SpotifyException as e:
            print(f"[SpotifyManager] Error setting volume: {e}")
            return False
        except requests.exceptions.ConnectionError as e:
            print(f"[SpotifyManager] Connection error setting volume: {e}")
            return False

    def get_current_track(self):
        """Return dict with current track info or None if nothing playing.

        Keys: name, artist, album, album_art_url, is_playing
        """
        if not self.sp:
            return None
        try:
            playback = self.sp.current_playback()
            if not playback or not playback.get("item"):
                return None
            item = playback["item"]
            artists = ", ".join(a["name"] for a in item.get("artists", []))
            images = item.get("album", {}).get("images", [])
            album_art_url = images[0]["url"] if images else ""
            return {
                "name": item.get("name", ""),
                "artist": artists,
                "album": item.get("album", {}).get("name", ""),
                "album_art_url": album_art_url,
                "is_playing": playback.get("is_playing", False),
            }
        except spotipy.exceptions.SpotifyException as e:
            print(f"[SpotifyManager] Error getting current track: {e}")
            return None
        except requests.exceptions.ConnectionError as e:
            print(f"[SpotifyManager] Connection error getting current track: {e}")
            return None

    def get_playlist_info(self, uri):
        """Return dict with name, cover_url, track_count or None.

        URI can be 'spotify:playlist:ID', 'spotify:album:ID', or a bare ID
        (assumed playlist for backwards compatibility).
        """
        if not self.sp:
            return None
        try:
            # Detect type from URI
            kind = "playlist"
            item_id = uri
            if uri.startswith("spotify:playlist:"):
                kind = "playlist"
                item_id = uri.split(":")[-1]
            elif uri.startswith("spotify:album:"):
                kind = "album"
                item_id = uri.split(":")[-1]

            if kind == "album":
                item = self.sp.album(item_id)
                track_count = item.get("tracks", {}).get("total", 0)
            else:
                item = self.sp.playlist(item_id)
                track_count = item.get("tracks", {}).get("total", 0)

            images = item.get("images", [])
            cover_url = images[0]["url"] if images else ""
            return {
                "name": item.get("name", ""),
                "cover_url": cover_url,
                "track_count": track_count,
            }
        except spotipy.exceptions.SpotifyException as e:
            print(f"[SpotifyManager] Error getting item info: {e}")
            return None
        except requests.exceptions.ConnectionError as e:
            print(f"[SpotifyManager] Connection error getting item info: {e}")
            return None

    def is_connected(self):
        """Check if Raspotify device is available. Returns True/False."""
        if not self.sp:
            return False
        try:
            result = self.sp.devices()
            device_name = self.config.get("spotify", {}).get("device_name", "flockifybox")
            devices = result.get("devices", [])
            for device in devices:
                if device.get("name", "").lower() == device_name.lower():
                    return True
            return False
        except spotipy.exceptions.SpotifyException as e:
            print(f"[SpotifyManager] Error checking connection: {e}")
            return False
        except requests.exceptions.ConnectionError as e:
            print(f"[SpotifyManager] Connection error checking device: {e}")
            return False
