import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth

GO_LIBRESPOT_URL = "http://127.0.0.1:3678"

SCOPES = "playlist-read-private"

TOKEN_CACHE_PATH = ".spotify_token_cache"


class SpotifyManager:
    """Spotify integration: go-librespot for playback, spotipy for metadata."""

    def __init__(self, config_manager):
        self.config = config_manager
        self.sp = None

        if self.is_configured():
            try:
                self._init_client()
            except Exception as e:
                print(f"[SpotifyManager] Failed to initialize client: {e}")

    # ── Local API helper ───────────────────────────────────────────

    def _local_post(self, path, json=None):
        """POST to go-librespot local API. Returns True on success."""
        try:
            r = requests.post(f"{GO_LIBRESPOT_URL}{path}", json=json, timeout=5)
            return r.status_code < 300
        except Exception as e:
            print(f"[SpotifyManager] go-librespot API error: {e}")
            return False

    # ── Credential / config helpers (spotipy) ──────────────────────

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
        spotify["refresh_token"] = ""
        self.config.set("spotify", spotify)
        try:
            if os.path.exists(TOKEN_CACHE_PATH):
                os.remove(TOKEN_CACHE_PATH)
        except OSError as e:
            print(f"[SpotifyManager] Could not delete token cache: {e}")
        self.sp = None

    def clear_credentials(self):
        """Fully clear Spotify credentials (client_id, secret, refresh_token)."""
        import os
        self.config.update_spotify_credentials("", "", refresh_token="")
        spotify = self.config.get("spotify", {})
        spotify["refresh_token"] = ""
        self.config.set("spotify", spotify)
        try:
            if os.path.exists(TOKEN_CACHE_PATH):
                os.remove(TOKEN_CACHE_PATH)
        except OSError as e:
            print(f"[SpotifyManager] Could not delete token cache: {e}")
        self.sp = None

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
        self.sp = spotipy.Spotify(
            auth_manager=auth_manager,
            retries=0,
            status_forcelist=(),
        )

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

    # ── Playback control (go-librespot local API) ──────────────────

    def play_playlist(self, uri):
        """Start playlist/album on go-librespot. Returns True/False."""
        return self._local_post("/player/play", json={"uri": uri})

    def next_track(self):
        """Skip to next track. Returns True/False."""
        return self._local_post("/player/next")

    def previous_track(self):
        """Go to previous track. Returns True/False."""
        return self._local_post("/player/prev")

    def pause(self):
        """Pause playback. Returns True/False."""
        return self._local_post("/player/pause")

    def resume(self):
        """Resume playback. Returns True/False."""
        return self._local_post("/player/resume")

    def set_volume(self, level):
        """Set volume (0-100). Returns True/False."""
        level = max(0, min(100, int(level)))
        return self._local_post("/player/volume", json={"volume": level})

    def get_current_track(self):
        """Return dict with current track info or None if nothing playing.

        Keys: name, artist, album, album_art_url, is_playing
        """
        try:
            r = requests.get(f"{GO_LIBRESPOT_URL}/status", timeout=5)
            if r.status_code >= 300:
                return None
            data = r.json()
            track = data.get("track")
            if not track:
                return None
            return {
                "name": track.get("name", ""),
                "artist": ", ".join(track.get("artist_names", [])),
                "album": track.get("album_name", ""),
                "album_art_url": track.get("album_cover_url", ""),
                "is_playing": not data.get("paused", True),
            }
        except Exception as e:
            print(f"[SpotifyManager] Error getting current track: {e}")
            return None

    def is_connected(self):
        """Check if go-librespot is reachable. Returns True/False."""
        try:
            r = requests.get(f"{GO_LIBRESPOT_URL}/status", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    # ── Metadata (spotipy, read-only) ──────────────────────────────

    def get_playlist_info(self, uri):
        """Return dict with name, cover_url, track_count or None.

        URI can be 'spotify:playlist:ID', 'spotify:album:ID', or a bare ID
        (assumed playlist for backwards compatibility).
        """
        if not self.sp:
            return None
        try:
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
