"""
Sleeper API Live Draft Sync & Player Database Mapper.
Polls public Sleeper API (GET https://api.sleeper.app/v1/draft/<draft_id>/picks)
and auto-registers live draft picks.
"""

import os
import json
import requests
from typing import List, Dict

SLEEPER_BASE_URL = "https://api.sleeper.app/v1"

class SleeperSync:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.player_map_file = os.path.join(data_dir, "sleeper_players.json")
        self.player_map: Dict[str, str] = {} # player_id -> full_name
        self.name_to_id: Dict[str, str] = {}
        self._load_player_map()

    def _load_player_map(self):
        """Loads cached Sleeper NFL players map or fetches it."""
        if os.path.exists(self.player_map_file):
            try:
                with open(self.player_map_file, "r") as f:
                    data = json.load(f)
                    self.player_map = data.get("id_to_name", {})
                    self.name_to_id = data.get("name_to_id", {})
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

    def fetch_draft_picks(self, draft_id: str) -> List[Dict]:
        """
        Polls current picks for a specific Sleeper draft ID.
        Returns list of pick objects with resolved player names.
        """
        if not draft_id or draft_id.strip() == "":
            return []

        url = f"{SLEEPER_BASE_URL}/draft/{draft_id.strip()}/picks"
        try:
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                raw_picks = res.json()
                parsed_picks = []
                for p in raw_picks:
                    pid = p.get("player_id")
                    player_name = self.player_map.get(pid, f"Player_{pid}")
                    parsed_picks.append({
                        "pick_no": p.get("pick_no"),
                        "round": p.get("round"),
                        "draft_slot": p.get("draft_slot"),
                        "player_id": pid,
                        "player_name": player_name,
                        "picked_by": p.get("picked_by"),
                        "roster_id": p.get("roster_id")
                    })
                return parsed_picks
        except Exception as e:
            print(f"Error polling Sleeper draft picks: {e}")

        return []
