"""Current Spotify endpoints; explicit caller-supplied OAuth session.
Requests sessions must have an Authorization header. Never persist tokens here.
"""
import time
import requests

class SpotifyClient:
    def __init__(self, session, sleep=time.sleep):
        self.session, self.sleep = session, sleep
    def request(self, method, path, **kwargs):
        for attempt in range(4):
            response = self.session.request(method, "https://api.spotify.com/v1/" + path,
                                            timeout=20, **kwargs)
            if response.status_code == 429:
                try:
                    reason = response.json().get("error", {}).get("reason")
                except (ValueError, AttributeError):
                    reason = None
                if reason == "QUOTA_EXCEEDED":
                    raise RuntimeError("Developer account quota exhausted; retry later")
            if response.status_code == 429 and attempt < 3:
                try:
                    delay = float(response.headers.get("Retry-After", "1"))
                except ValueError:
                    raise RuntimeError("Invalid rate-limit response") from None
                if not 0 <= delay <= 120:
                    raise RuntimeError("Rate limit requires a later retry")
                self.sleep(delay)
                continue
            response.raise_for_status()
            return response.json() if response.content else {}
        raise RuntimeError("Rate limit retry budget exhausted")
    def me(self):
        return self.request("GET", "me")
    def create_playlist(self, name, public=False):
        return self.request("POST", "me/playlists", json={"name": name, "public": public})
    def add_items(self, key, uris):
        return self.request("POST", "playlists/" + key + "/items", json={"uris": uris})
    def playlist_items(self, key):
        items, offset = [], 0
        while True:
            page = self.request("GET", "playlists/" + key + "/items",
                                params={"limit": 50, "offset": offset})
            items.extend(page["items"])
            if not page.get("next"):
                return items
            if not page["items"]:
                raise RuntimeError("Invalid pagination; export incomplete")
            offset += len(page["items"])
