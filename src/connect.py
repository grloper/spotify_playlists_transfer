"""PKCE read-only export. Tokens stay in memory; browser supplies consent."""
import argparse
import base64
import hashlib
import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
import requests
from .provider import SpotifyClient

REDIRECT = "http://127.0.0.1:4632/callback"

def pkce():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge

def connect(client_id, expected_account, output):
    verifier, challenge = pkce()
    state = secrets.token_urlsafe(32)
    result = {}
    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            valid = (self.headers.get("Host") == "127.0.0.1:4632" and url.path == "/callback"
                     and query.get("state") == [state])
            if not valid:
                self.send_error(400, "Invalid authorization response")
                return
            result["code"] = query.get("code", [None])[0]
            result["error"] = query.get("error", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b"Authorization received. You may close this tab.")
        def log_message(self, *args):
            pass  # Callback URLs contain a sensitive authorization code.
    server = HTTPServer(("127.0.0.1", 4632), Callback)
    server.timeout = 1
    params = {"client_id": client_id, "response_type": "code", "redirect_uri": REDIRECT,
              "scope": "playlist-read-private playlist-read-collaborative",
              "state": state, "code_challenge_method": "S256", "code_challenge": challenge,
              "show_dialog": "true"}
    try:
        webbrowser.open("https://accounts.spotify.com/authorize?" + urlencode(params))
        import time
        deadline = time.monotonic() + 180
        while not result and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if not result.get("code") or result.get("error"):
        raise RuntimeError("Consent was denied or timed out; nothing exported")
    response = requests.post("https://accounts.spotify.com/api/token", timeout=20,
                             data={"grant_type": "authorization_code", "code": result["code"],
                                   "redirect_uri": REDIRECT, "client_id": client_id,
                                   "code_verifier": verifier})
    response.raise_for_status()
    token = response.json()["access_token"]
    session = requests.Session()
    session.headers["Authorization"] = "Bearer " + token
    client = SpotifyClient(session)
    try:
        account = client.me()["id"]
        if account != expected_account:
            raise RuntimeError("Wrong account authorized; nothing exported")
        playlists, offset = [], 0
        while True:
            page = client.request("GET", "me/playlists", params={"limit": 50, "offset": offset})
            for playlist in page["items"]:
                # Development Mode allows items only for owned/collaborative playlists.
                if playlist.get("owner", {}).get("id") != account and not playlist.get("collaborative"):
                    continue
                tracks = client.playlist_items(playlist["id"])
                playlists.append({"id": playlist["id"], "name": playlist["name"],
                                  "tracks": [(item.get("item") or item.get("track") or {}).get("uri") for item in tracks]})
            if not page.get("next"):
                break
            if not page["items"]:
                raise RuntimeError("Incomplete playlist pagination; nothing exported")
            offset += len(page["items"])
        data = {"source_account": account, "playlists": playlists, "liked_songs": []}
        # Exclusive creation prevents accidentally overwriting a previous backup.
        with Path(output).open("x", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
        return len(playlists)
    finally:
        session.headers.pop("Authorization", None)
        session.close()

def main():
    parser = argparse.ArgumentParser(description="Read-only Spotify PKCE export")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--account", required=True, help="Exact Spotify account ID; refuse mismatches")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        count = connect(args.client_id, args.account, args.output)
        print(str(count) + " playlists exported. No account changes made.")
    except Exception:
        # No provider response bodies, callback URLs or tokens in console output.
        raise SystemExit("Export failed. Check consent, account ID, allowlist, redirect URI and API access. No account changes made.")
if __name__ == "__main__":
    main()
