import unittest
from unittest.mock import Mock, patch
from src.spotify_manager import SpotifyManager
from src import config

class AccountSafetyTests(unittest.TestCase):
    def test_rejects_wrong_account_even_after_clean_authentication(self):
        manager = SpotifyManager('synthetic-user', 'fake-id', 'fake-secret', 'http://127.0.0.1:8080', '')
        client = Mock()
        client.me.return_value = {'id': 'different-synthetic-user'}
        with patch('src.spotify_manager.SpotifyOAuth'), patch('src.spotify_manager.spotipy.Spotify', return_value=client):
            self.assertFalse(manager.authenticate(clean_cache=True))
        self.assertIsNone(manager.sp)
        self.assertIsNone(manager.user_id)
        client.user_playlist_create.assert_not_called()

    def test_reports_all_missing_configuration(self):
        with patch.multiple(config, CLIENT_ID=None, CLIENT_SECRET=None, REDIRECT_URI=None, SPOTIFY_USERNAME=None), patch.object(config.logger, 'error') as log:
            self.assertFalse(config.validate_config())
            message = log.call_args_list[0].args[0]
            for name in ['CLIENT_ID', 'CLIENT_SECRET', 'REDIRECT_URI', 'SPOTIFY_USERNAME']:
                self.assertIn(name, message)
