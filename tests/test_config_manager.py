import json
import os
import pytest

from config_manager import ConfigManager


class TestConfigManagerLoad:
    def test_load_creates_from_default(self, config_manager, tmp_dir):
        """When config.json doesn't exist, load() copies from default."""
        config_path = os.path.join(tmp_dir, 'config2.json')
        default_path = os.path.join(tmp_dir, 'config_default.json')

        assert not os.path.exists(config_path)
        cm = ConfigManager(config_path=config_path, default_path=default_path)
        assert os.path.exists(config_path)

        with open(default_path, 'r') as f:
            expected = json.load(f)
        assert cm.config == expected


class TestConfigManagerGetSet:
    def test_get_set_roundtrip(self, config_manager):
        """set() a value, then get() it back."""
        config_manager.set('test_key', 'test_value')
        assert config_manager.get('test_key') == 'test_value'


class TestConfigManagerPlaylists:
    def test_add_playlist(self, config_manager):
        """Adding a playlist stores it correctly."""
        config_manager.add_playlist('My Playlist', 'spotify:playlist:abc', 'http://img/1')
        playlists = config_manager.get('playlists')
        assert len(playlists) == 1
        assert playlists[0]['name'] == 'My Playlist'
        assert playlists[0]['uri'] == 'spotify:playlist:abc'
        assert playlists[0]['cover_url'] == 'http://img/1'

    def test_add_playlist_max_limit(self, config_manager):
        """Adding more than MAX_PLAYLISTS raises ValueError."""
        for i in range(10):
            config_manager.add_playlist(f'P{i}', f'uri:{i}', f'http://img/{i}')
        with pytest.raises(ValueError, match="Maximum"):
            config_manager.add_playlist('P10', 'uri:10', 'http://img/10')

    def test_remove_playlist(self, config_manager):
        """Remove index 0, the second playlist remains."""
        config_manager.add_playlist('First', 'uri:0', 'http://img/0')
        config_manager.add_playlist('Second', 'uri:1', 'http://img/1')
        config_manager.remove_playlist(0)
        playlists = config_manager.get('playlists')
        assert len(playlists) == 1
        assert playlists[0]['name'] == 'Second'

    def test_remove_playlist_invalid_index(self, config_manager):
        """Removing an out-of-range index raises IndexError."""
        with pytest.raises(IndexError):
            config_manager.remove_playlist(99)

    def test_reorder_playlists(self, config_manager):
        """Reorder [2,0,1] rearranges playlists correctly."""
        for i in range(3):
            config_manager.add_playlist(f'P{i}', f'uri:{i}', f'http://img/{i}')
        config_manager.reorder_playlists([2, 0, 1])
        names = [p['name'] for p in config_manager.get('playlists')]
        assert names == ['P2', 'P0', 'P1']


class TestConfigManagerWebradioAndSpotify:
    def test_update_webradio(self, config_manager):
        """update_webradio stores all fields."""
        config_manager.update_webradio('Jazz FM', 'http://jazz.fm/stream', 'images/jazz.png')
        wr = config_manager.get('webradio')
        assert wr['name'] == 'Jazz FM'
        assert wr['url'] == 'http://jazz.fm/stream'
        assert wr['image_path'] == 'images/jazz.png'

    def test_update_spotify_credentials(self, config_manager):
        """update_spotify_credentials stores id, secret, and refresh_token."""
        config_manager.update_spotify_credentials('cid', 'csecret', 'rtoken')
        spotify = config_manager.get('spotify')
        assert spotify['client_id'] == 'cid'
        assert spotify['client_secret'] == 'csecret'
        assert spotify['refresh_token'] == 'rtoken'


class TestConfigManagerState:
    def test_save_state_get_state(self, config_manager):
        """save_state then get_state returns the saved values."""
        config_manager.save_state(mode_index=2, volume=75)
        state = config_manager.get_state()
        assert state['mode_index'] == 2
        assert state['volume'] == 75

    def test_get_state_defaults(self, tmp_dir):
        """get_state returns defaults when no state key exists."""
        default_path = os.path.join(tmp_dir, 'no_state_default.json')
        config_path = os.path.join(tmp_dir, 'no_state_config.json')
        cfg = {"spotify": {}, "playlists": []}
        with open(default_path, 'w') as f:
            json.dump(cfg, f)

        orig_cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            cm = ConfigManager(config_path=config_path, default_path=default_path)
            state = cm.get_state()
            assert state == {'mode_index': 0, 'volume': 50}
        finally:
            os.chdir(orig_cwd)

    def test_save_state_does_not_clobber_external_changes(self, config_manager):
        """If another process modifies config.json, save_state must
        merge — only updating the 'state' field — instead of writing the
        whole stale in-memory config back."""
        # Simulate flockify having stale playlist data in memory
        config_manager.config['playlists'] = [{'name': 'STALE', 'uri': 'x', 'cover_url': '', 'cover_cached': ''}]

        # Simulate an external process (e.g. migration script) writing
        # a fresh config to disk with different playlists
        with open(config_manager.config_path, 'r') as f:
            disk_cfg = json.load(f)
        disk_cfg['playlists'] = [{'name': 'FRESH', 'uri': 'y', 'cover_url': '', 'cover_cached': '/new/path.jpg'}]
        disk_cfg['some_external_field'] = 'preserve_me'
        with open(config_manager.config_path, 'w') as f:
            json.dump(disk_cfg, f)

        # Now flockify saves state — this used to clobber the external change
        config_manager.save_state(mode_index=3, volume=88)

        # Re-read disk and verify both updates landed
        with open(config_manager.config_path, 'r') as f:
            final = json.load(f)

        # state was updated
        assert final['state']['mode_index'] == 3
        assert final['state']['volume'] == 88
        # external changes preserved (NOT clobbered by stale in-memory data)
        assert final['playlists'][0]['name'] == 'FRESH'
        assert final['some_external_field'] == 'preserve_me'


class TestConfigManagerAtomicSave:
    def test_atomic_save(self, config_manager, tmp_dir):
        """After save(), config.json exists and contains the latest data."""
        config_manager.set('proof', 42)
        config_path = config_manager.config_path
        assert os.path.exists(config_path)
        with open(config_path, 'r') as f:
            data = json.load(f)
        assert data['proof'] == 42
