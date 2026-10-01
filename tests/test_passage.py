import unittest
from unittest.mock import Mock
import requests
from src.passage import build_plan, execute, SyntheticClient
from src.provider import SpotifyClient
from src.connect import pkce

A = "spotify:track:" + "A" * 22
B = "spotify:episode:" + "B" * 22

def data(tracks=None):
    return {"playlists": [{"id": "one", "name": "Fixture", "tracks": tracks if tracks is not None else [A, B]}]}

class TransferTests(unittest.TestCase):
    def test_order_duplicates_and_skips(self):
        plan = build_plan(data([A, None, "spotify:local:x", B, A]), "dest")
        self.assertEqual(plan.playlists[0]["uris"], [A, B, A])
        self.assertEqual([x["position"] for x in plan.skipped], [2, 3])
    def test_stale_confirmation_and_wrong_account_never_write(self):
        plan = build_plan(data(), "dest")
        client = Mock()
        with self.assertRaises(ValueError): execute(plan, client, "stale")
        client.me.assert_not_called()
        client.me.return_value = {"id": "wrong"}
        with self.assertRaises(ValueError): execute(plan, client, plan.digest)
        client.create_playlist.assert_not_called()
    def test_chunking_and_private_copy(self):
        plan = build_plan(data([A] * 205), "dest")
        client = SyntheticClient("dest")
        report = execute(plan, client, plan.digest)
        self.assertEqual(report["playlists"][0]["added"], 205)
        self.assertEqual(client.playlists["demo-1"]["items"], [A] * 205)
        self.assertFalse(client.playlists["demo-1"]["public"])
    def test_timeout_stops_without_retry_or_more_creation(self):
        fixture = data([A] * 101)
        fixture["playlists"].append({"id": "two", "name": "Later", "tracks": [B]})
        plan = build_plan(fixture, "dest")
        client = Mock()
        client.me.return_value = {"id": "dest"}
        client.create_playlist.return_value = {"id": "created"}
        client.add_items.side_effect = [{"snapshot_id": "ok"}, requests.Timeout()]
        report = execute(plan, client, plan.digest)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["playlists"][0]["added"], 100)
        self.assertEqual(client.add_items.call_count, 2)
        self.assertEqual(client.create_playlist.call_count, 1)
    def test_validation_and_selection(self):
        for fixture in [{}, data("bad"), {"playlists": [{"name": ""}]}]:
            with self.assertRaises(ValueError): build_plan(fixture, "dest")
        with self.assertRaises(ValueError): build_plan(data(), "dest", [])
    def test_current_endpoints_and_rate_limit(self):
        session = Mock()
        limited = Mock(status_code=429, headers={"Retry-After": "2"})
        ok = Mock(status_code=200, content=b"{}")
        ok.json.return_value = {"id": "copy"}
        session.request.side_effect = [limited, ok, ok]
        sleep = Mock()
        client = SpotifyClient(session, sleep)
        client.create_playlist("Fixture")
        sleep.assert_called_once_with(2.0)
        client.add_items("copy", [A])
        self.assertTrue(session.request.call_args_list[0].args[1].endswith("/me/playlists"))
        self.assertTrue(session.request.call_args_list[-1].args[1].endswith("/playlists/copy/items"))
    def test_failed_second_page_never_returns_partial_export(self):
        client = SpotifyClient(Mock())
        client.request = Mock(side_effect=[{"items": [{"item": {"uri": A}}], "next": "more"}, requests.Timeout()])
        with self.assertRaises(requests.Timeout): client.playlist_items("one")
    def test_pkce_entropy_and_challenge(self):
        import base64, hashlib
        verifier, challenge = pkce()
        self.assertGreaterEqual(len(verifier), 43)
        self.assertEqual(challenge, base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("="))

    def test_mutated_plan_rejected_before_account_access(self):
        plan = build_plan(data(), "dest")
        plan.playlists[0]["uris"].append(A)
        client = Mock()
        with self.assertRaises(ValueError): execute(plan, client, plan.digest)
        client.me.assert_not_called()
    def test_quota_is_not_blindly_retried(self):
        session = Mock()
        response = Mock(status_code=429)
        response.json.return_value = {"error": {"reason": "QUOTA_EXCEEDED"}}
        session.request.return_value = response
        with self.assertRaises(RuntimeError): SpotifyClient(session).me()
        self.assertEqual(session.request.call_count, 1)
