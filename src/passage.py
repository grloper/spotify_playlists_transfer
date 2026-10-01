"""Review-first transfer engine. No network or credentials required."""
import hashlib
import json
import re
from dataclasses import dataclass, asdict

URI = re.compile(r"spotify:(track|episode):[A-Za-z0-9]{22}\Z")

@dataclass(frozen=True)
class Plan:
    destination: str
    playlists: tuple
    skipped: tuple
    digest: str
    def to_dict(self):
        return asdict(self)

def build_plan(data, destination, selected=None):
    if not isinstance(data, dict) or not isinstance(data.get("playlists"), list):
        raise ValueError("Export must contain a playlists array")
    if not isinstance(destination, str) or not destination.strip():
        raise ValueError("Choose a destination account")
    playlists, skipped = [], []
    ids = set()
    for index, source in enumerate(data["playlists"]):
        if not isinstance(source, dict):
            raise ValueError("Each playlist must be an object")
        key = str(source.get("id", index))
        if key in ids:
            raise ValueError("Duplicate playlist identifiers")
        ids.add(key)
        if selected is not None and key not in selected:
            continue
        name = source.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError("Playlist name must have 1 to 100 characters")
        tracks = source.get("tracks", source.get("track_uris", []))
        if not isinstance(tracks, list):
            raise ValueError("Playlist tracks must be an array")
        accepted = []
        for position, item in enumerate(tracks):
            uri = item.get("uri") if isinstance(item, dict) else item
            if isinstance(uri, str) and URI.fullmatch(uri):
                accepted.append(uri)  # Preserve order AND intentional duplicates.
            else:
                skipped.append({"playlist": name, "position": position + 1,
                                "reason": "Local, unavailable or invalid item"})
        playlists.append({"source_id": key, "name": name, "uris": accepted,
                          "public": False})
    if not playlists:
        raise ValueError("Select at least one playlist")
    payload = {"destination": destination.strip(), "playlists": playlists, "skipped": skipped}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return Plan(destination.strip(), tuple(playlists), tuple(skipped), digest)

def execute(plan, client, confirmed_digest):
    """Create private copies. Stop on ambiguous writes; never blind-retry."""
    payload = {"destination": plan.destination, "playlists": list(plan.playlists), "skipped": list(plan.skipped)}
    current_digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    if confirmed_digest != plan.digest or current_digest != plan.digest:
        raise ValueError("Review changed; confirm this exact plan again")
    if client.me()["id"] != plan.destination:
        raise ValueError("Authenticated destination does not match reviewed account")
    report = {"plan": plan.digest, "destination": plan.destination,
              "status": "complete", "playlists": [], "skipped": list(plan.skipped)}
    for playlist in plan.playlists:
        row = {"name": playlist["name"], "id": None, "added": 0,
               "total": len(playlist["uris"]), "status": "pending"}
        report["playlists"].append(row)
        try:
            created = client.create_playlist(playlist["name"], public=False)
            row["id"] = created["id"]
            for offset in range(0, len(playlist["uris"]), 100):
                client.add_items(row["id"], playlist["uris"][offset:offset + 100])
                row["added"] += len(playlist["uris"][offset:offset + 100])
            row["status"] = "complete"
        except Exception:
            row["status"] = "needs_reconciliation"
            report["status"] = "stopped"
            # Do not leak provider errors/tokens or continue creating more copies.
            break
    return report

class SyntheticClient:
    """In-memory demo backend. IDs/contents are not Spotify observations."""
    def __init__(self, account):
        self.account, self.playlists = account, {}
    def me(self):
        return {"id": self.account}
    def create_playlist(self, name, public=False):
        key = "demo-" + str(len(self.playlists) + 1)
        self.playlists[key] = {"name": name, "public": public, "items": []}
        return {"id": key}
    def add_items(self, key, uris):
        self.playlists[key]["items"].extend(uris)
        return {"snapshot_id": "synthetic"}
