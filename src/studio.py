"""Loopback-only synthetic review studio. No live writes or token input."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .passage import build_plan, execute, SyntheticClient

DEMO = {"playlists": [
    {"id": "morning", "name": "Morning in motion", "tracks": ["spotify:track:" + "A" * 22, "spotify:track:" + "B" * 22, "spotify:local:demo"]},
    {"id": "night", "name": "After hours", "tracks": ["spotify:track:" + "C" * 22] * 3},
    {"id": "focus", "name": "Deep focus", "tracks": ["spotify:track:" + "D" * 22]}]}

class Handler(BaseHTTPRequestHandler):
    def reply(self, status, payload, content_type="application/json"):
        encoded = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(encoded)
    def do_GET(self):
        if self.headers.get("Host") != "127.0.0.1:" + str(self.server.server_port):
            return self.reply(403, {"error": "Use the loopback address"})
        if self.path == "/api/demo":
            return self.reply(200, DEMO)
        files = {"/": ("index.html", "text/html; charset=utf-8"),
                 "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
        if self.path not in files:
            return self.reply(404, {"error": "Not found"})
        name, content_type = files[self.path]
        return self.reply(200, (Path(__file__).parent / "web" / name).read_text(encoding="utf-8"), content_type)
    def do_POST(self):
        origin = "http://127.0.0.1:" + str(self.server.server_port)
        if self.headers.get("Origin") != origin or self.headers.get("Host") != origin[7:]:
            return self.reply(403, {"error": "Only same-origin requests are allowed"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2_000_000:
                return self.reply(413, {"error": "Export must be under 2 MB"})
            body = json.loads(self.rfile.read(length))
            plan = build_plan(body["data"], body["destination"], body.get("selected"))
            if self.path == "/api/review":
                return self.reply(200, plan.to_dict())
            if self.path == "/api/simulate":
                report = execute(plan, SyntheticClient(plan.destination), body.get("digest"))
                report["mode"] = "synthetic; no Spotify changes"
                return self.reply(200, report)
            return self.reply(404, {"error": "Not found"})
        except (ValueError, KeyError, TypeError):
            return self.reply(400, {"error": "Invalid export or stale review. Check the playlist format and review again."})
    def log_message(self, *args):
        pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4631)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("Playlist Passage: http://127.0.0.1:" + str(args.port), flush=True)
    server.serve_forever()
if __name__ == "__main__":
    main()
