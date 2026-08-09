"""
Sleeper API Live Draft Sync & Player Database Mapper.
Polls public Sleeper API (GET https://api.sleeper.app/v1/draft/<draft_id>/picks)
and auto-registers live draft picks.
"""

import os
import json
import requests
from typing import List, Dict, Optional

SLEEPER_BASE_URL = "https://api.sleeper.app/v1"

class SleeperSync:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.player_map_file = os.path.join(data_dir, "sleeper_players.json")
        self.player_map: Dict[str, str] = {} # player_id -> full_name
        self.name_to_id: Dict[str, str] = {}
        self._load_player_map()

    def _load_player_map(self):
        """Loads cached Sleeper NFL players map. Handles both structured and raw API formats."""
        if os.path.exists(self.player_map_file):
            try:
                with open(self.player_map_file, "r") as f:
                    data = json.load(f)

                # Structured format: {"id_to_name": {...}, "name_to_id": {...}}
                if "id_to_name" in data:
                    self.player_map = data.get("id_to_name", {})
                    self.name_to_id = data.get("name_to_id", {})
                    return

                # Raw Sleeper API format: {"player_id": {"first_name": ..., "last_name": ...}, ...}
                # Convert to structured format on the fly
                id_to_name = {}
                name_to_id = {}
                for pid, pinfo in data.items():
                    if not isinstance(pinfo, dict):
                        continue
                    first = pinfo.get("first_name", "")
                    last = pinfo.get("last_name", "")
                    full = f"{first} {last}".strip()
                    if full:
                        id_to_name[pid] = full
                        name_to_id[full.lower()] = pid
                self.player_map = id_to_name
                self.name_to_id = name_to_id
                return
            except Exception as e:
                print(f"Error reading cached sleeper map: {e}")

        # If not cached, attempt to fetch from API
        self.fetch_and_cache_nfl_players()

    def fetch_and_cache_nfl_players(self):
        """Fetches full NFL player database from Sleeper API."""
        url = f"{SLEEPER_BASE_URL}/players/nfl"
        try:
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                players_data = res.json()
                id_to_name = {}
                name_to_id = {}
                for pid, pinfo in players_data.items():
                    first = pinfo.get("first_name", "")
                    last = pinfo.get("last_name", "")
                    full = f"{first} {last}".strip()
                    if full:
                        id_to_name[pid] = full
                        name_to_id[full.lower()] = pid

                self.player_map = id_to_name
                self.name_to_id = name_to_id

                with open(self.player_map_file, "w") as f:
                    json.dump({"id_to_name": id_to_name, "name_to_id": name_to_id}, f)
        except Exception as e:
            print(f"Error fetching Sleeper player database: {e}")

    def get_draft_info(self, draft_id: str) -> Optional[Dict]:
        """
        Fetches draft metadata (status, type, settings, team count) for a draft ID,
        League ID, or full Sleeper URL. Automatically resolves League IDs to Draft IDs.
        """
        if not draft_id or str(draft_id).strip() == "":
            return None

        import re
        match = re.search(r'\d{17,20}', str(draft_id))
        clean_id = match.group(0) if match else str(draft_id).strip()

        # 1. Try directly as draft_id
        url = f"{SLEEPER_BASE_URL}/draft/{clean_id}"
        try:
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict) and "draft_id" in data:
                    return data
        except Exception:
            pass

        # 2. Try as league_id fallback
        league_url = f"{SLEEPER_BASE_URL}/league/{clean_id}/drafts"
        try:
            res = requests.get(league_url, timeout=5)
            if res.status_code == 200:
                drafts = res.json()
                if drafts and isinstance(drafts, list) and len(drafts) > 0:
                    return drafts[0]
        except Exception:
            pass

        return None

    def fetch_draft_picks(self, draft_id: str, resolved_info: Optional[Dict] = None) -> List[Dict]:
        """
        Polls current picks for a specific Sleeper draft ID, League ID, or URL.
        Returns list of pick objects with resolved player names, position, and team.
        
        If resolved_info is provided (from a prior get_draft_info call), the
        redundant resolution HTTP request is skipped.
        """
        if not draft_id or str(draft_id).strip() == "":
            return []

        info = resolved_info or self.get_draft_info(draft_id)
        if not info or "draft_id" not in info:
            return []

        actual_draft_id = info["draft_id"]
        url = f"{SLEEPER_BASE_URL}/draft/{actual_draft_id}/picks"
        try:
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                raw_picks = res.json()
                parsed_picks = []
                for p in raw_picks:
                    pid = p.get("player_id")
                    meta = p.get("metadata", {}) or {}
                    fname = meta.get("first_name", "").strip()
                    lname = meta.get("last_name", "").strip()
                    meta_name = f"{fname} {lname}".strip()
                    
                    player_name = meta_name or self.player_map.get(pid) or (f"Player_{pid}" if pid else "Unknown Player")
                    pos = meta.get("position") or "FLEX"
                    team = meta.get("team") or "NFL"

                    parsed_picks.append({
                        "pick_no": p.get("pick_no"),
                        "round": p.get("round"),
                        "draft_slot": p.get("draft_slot"),
                        "player_id": pid,
                        "player_name": player_name,
                        "position": pos,
                        "team": team,
                        "picked_by": p.get("picked_by"),
                        "roster_id": p.get("roster_id")
                    })
                return parsed_picks
        except Exception as e:
            print(f"Error polling Sleeper draft picks for ID '{actual_draft_id}': {e}")

        return []
