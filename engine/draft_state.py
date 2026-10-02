"""
Draft State Manager.
Manages 6-Governor 12-round snake draft matrix, roster allocations,
undo history stack, and real-time state persistence.
"""

import os
import json
from typing import List, Dict, Optional

class DraftState:
    def __init__(self, config_path: str, state_path: str):
        self.config_path = config_path
        self.state_path = state_path
        
        with open(config_path, "r") as f:
            self.config = json.load(f)
            
        # Optional local config override (e.g. data/config.local.json for private governor names)
        local_config_path = os.path.join(os.path.dirname(config_path), "config.local.json")
        if os.path.exists(local_config_path):
            try:
                with open(local_config_path, "r") as lf:
                    self.config.update(json.load(lf))
            except Exception as e:
                print(f"Warning: Could not load local config override: {e}")
            
        self.governors: List[str] = self.config["governors"]
        self.num_teams = len(self.governors)
        self.num_rounds = self.config["num_rounds"]
        self.my_team = self.config["my_team_name"]
        self.my_index = self.governors.index(self.my_team) if self.my_team in self.governors else 0
        
        self.roster_limits = self.config["roster_settings"]
        
        # Load bye weeks map
        bye_file = self.config.get("bye_weeks_file", "bye_weeks.json")
        bye_path = os.path.join(os.path.dirname(config_path), bye_file)
        self.bye_weeks_map: Dict[str, int] = {}
        if os.path.exists(bye_path):
            try:
                with open(bye_path, "r") as bf:
                    b_data = json.load(bf)
                    self.bye_weeks_map = {k: int(v) for k, v in b_data.items() if not k.startswith("_")}
                    aliases = b_data.get("_aliases", {})
                    for alias, canonical in aliases.items():
                        if canonical in self.bye_weeks_map:
                            self.bye_weeks_map[alias] = self.bye_weeks_map[canonical]
            except Exception as e:
                print(f"Warning: Could not load bye weeks map: {e}")

        # Internal state
        self.picks_history: List[Dict] = [] # list of pick dicts
        self.drafted_players: set = set()
        self.rosters: Dict[str, List[Dict]] = {gov: [] for gov in self.governors}
        
        # Generate 72-pick snake order matrix
        self.snake_order = self._generate_snake_order()
        self.load_state()

    def _generate_snake_order(self) -> List[Dict]:
        """Generates 72-pick snake order mapping pick_no to Governor."""
        snake = []
        pick_no = 1
        for r in range(1, self.num_rounds + 1):
            if r % 2 != 0: # Odd rounds: 1 to 6
                order = list(range(self.num_teams))
            else: # Even rounds: 6 to 1
                order = list(range(self.num_teams - 1, -1, -1))
                
            for slot_idx in order:
                gov = self.governors[slot_idx]
                snake.append({
                    "pick_no": pick_no,
                    "round": r,
                    "slot_idx": slot_idx,
                    "governor": gov
                })
                pick_no += 1
        return snake

    def current_pick_info(self) -> Optional[Dict]:
        """Returns info on the upcoming pick in the snake draft."""
        curr_idx = len(self.picks_history)
        if curr_idx < len(self.snake_order):
            return self.snake_order[curr_idx]
        return None

    def picks_until_my_turn(self) -> int:
        """Returns number of picks remaining before your next pick turn."""
        curr_idx = len(self.picks_history)
        for i in range(curr_idx, len(self.snake_order)):
            if self.snake_order[i]["governor"] == self.my_team:
                return i - curr_idx
        return 999 # No more picks left for user

    def record_pick(self, player_name: str, position: str, team: str, ufl_pts: float, governor: Optional[str] = None) -> Dict:
        """Records a draft pick for the current or specified Governor."""
        curr_info = self.current_pick_info()
        if not curr_info:
            return {}

        assigned_gov = governor if governor else curr_info["governor"]
        clean_name = player_name.strip()
        pick_data = {
            "pick_no": len(self.picks_history) + 1,
            "round": curr_info["round"],
            "governor": assigned_gov,
            "player_name": clean_name,
            "position": position,
            "team": team,
            "ufl_pts": ufl_pts
        }
        
        self.picks_history.append(pick_data)
        self.drafted_players.add(clean_name.lower())
        self.rosters[assigned_gov].append(pick_data)
        self.save_state()
        return pick_data

    def undo_last_pick(self) -> Optional[Dict]:
        """Undoes the most recent pick."""
        if not self.picks_history:
            return None
            
        last_pick = self.picks_history.pop()
        player_name = last_pick["player_name"].strip()
        assigned_gov = last_pick["governor"]
        
        if player_name.lower() in self.drafted_players:
            self.drafted_players.remove(player_name.lower())
            
        if assigned_gov in self.rosters:
            # Remove only the last matching entry (by pick_no), not all entries with the same name
            gov_roster = self.rosters[assigned_gov]
            for i in range(len(gov_roster) - 1, -1, -1):
                if gov_roster[i].get("player_name", "").lower() == player_name.lower():
                    gov_roster.pop(i)
                    break
            
        self.save_state()
        return last_pick

    def reset_draft(self):
        """Resets all draft state."""
        self.picks_history = []
        self.drafted_players = set()
        self.rosters = {gov: [] for gov in self.governors}
        self.save_state()

    def is_drafted(self, player_name: str) -> bool:
        if not player_name:
            return False
        return player_name.strip().lower() in self.drafted_players

    def get_governor_roster_breakdown(self, governor: str) -> Dict[str, int]:
        """Returns count of drafted positions for a specific Governor."""
        roster = self.rosters.get(governor, [])
        counts = {"QB": 0, "RB": 0, "WR": 0, "TE": 0}
        for p in roster:
            pos = p["position"]
            if pos in counts:
                counts[pos] += 1
        return counts

    def save_state(self):
        """Persists current state to JSON."""
        data = {
            "picks_history": self.picks_history
        }
        with open(self.state_path, "w") as f:
            json.dump(data, f, indent=2)

    def load_state(self):
        """Loads state from JSON."""
        if os.path.exists(self.state_path) and os.path.getsize(self.state_path) > 0:
            try:
                with open(self.state_path, "r") as f:
                    data = json.load(f)
                    self.picks_history = data.get("picks_history", [])
                    self.drafted_players = {p["player_name"].lower() for p in self.picks_history}
                    self.rosters = {gov: [] for gov in self.governors}
                    for p in self.picks_history:
                        gov = p["governor"]
                        if gov in self.rosters:
                            self.rosters[gov].append(p)
            except Exception as e:
                print(f"Error loading state: {e}")
