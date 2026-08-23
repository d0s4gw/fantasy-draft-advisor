"""
Opponent Pick Predictor Engine.
Analyzes draft matrix and opponent roster construction to predict steals,
at-risk player threats, and reach risks before your upcoming turn in the snake draft.
"""

import pandas as pd
from typing import List, Dict, Set, Optional

class OpponentPredictor:
    def __init__(self, draft_state):
        self.draft_state = draft_state

    def predict_upcoming_opponent_needs(self, target_governor: Optional[str] = None) -> List[Dict]:
        """
        Analyzes opponents who will pick between the current pick
        and the target governor's next pick turn.
        """
        curr_idx = len(self.draft_state.picks_history)
        snake = self.draft_state.snake_order
        curr_info = self.draft_state.current_pick_info()
        target_gov = target_governor if target_governor else (curr_info["governor"] if curr_info else self.draft_state.my_team)
        
        upcoming_opponents = []
        start_i = curr_idx + 1 if (curr_idx < len(snake) and snake[curr_idx]["governor"] == target_gov) else curr_idx
        for i in range(start_i, len(snake)):
            gov = snake[i]["governor"]
            if gov == target_gov:
                break # Reached target governor's next turn

            
            # Get opponent roster breakdown
            roster_counts = self.draft_state.get_governor_roster_breakdown(gov)
            round_no = snake[i]["round"]
            
            # Mandatory roster requirements (no-waiver league: QB>=3, RB>=3, WR>=3, TE>=2)
            picks_made = len(self.draft_state.rosters.get(gov, []))
            picks_remaining = 12 - picks_made

            req_qb = max(0, 3 - roster_counts["QB"])
            req_rb = max(0, 3 - roster_counts["RB"])
            req_wr = max(0, 3 - roster_counts["WR"])
            req_te = max(0, 2 - roster_counts["TE"])
            total_needed = req_qb + req_rb + req_wr + req_te

            needs = []
            # Starter needs (more urgent)
            if roster_counts["QB"] < 2:
                needs.append("QB")
            if roster_counts["RB"] < 1:
                needs.append("RB")
            if roster_counts["WR"] < 1:
                needs.append("WR")
            if roster_counts["TE"] < 1:
                needs.append("TE")

            # Roster depth needs (when running out of picks)
            if not needs and picks_remaining <= total_needed + 2:
                if req_qb > 0:
                    needs.append("QB")
                if req_rb > 0:
                    needs.append("RB")
                if req_wr > 0:
                    needs.append("WR")
                if req_te > 0:
                    needs.append("TE")
                
            upcoming_opponents.append({
                "pick_no": snake[i]["pick_no"],
                "round": round_no,
                "governor": gov,
                "current_qbs": roster_counts["QB"],
                "predicted_needs": needs if needs else ["FLEX / Best VORP"]
            })
            
        return upcoming_opponents

    def get_at_risk_positions(self) -> Set[str]:
        """
        Returns set of positions (e.g. {'QB', 'RB'}) that opponents before your next turn are likely to target.
        """
        opps = self.predict_upcoming_opponent_needs()
        at_risk = set()
        for opp in opps:
            for n in opp["predicted_needs"]:
                if n in ["QB", "RB", "WR", "TE"]:
                    at_risk.add(n)
        return at_risk

    def flag_at_risk_players(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds 'at_risk' boolean and 'steal_threat' text column to candidates.
        Top 1-2 players at an at-risk position are flagged as threat targets.
        """
        if df.empty:
            return df

        at_risk_pos = self.get_at_risk_positions()
        res = df.copy()
        
        at_risk_flags = []
        threat_notes = []

        # Count top players per position
        pos_rank = {}
        for pos in ["QB", "RB", "WR", "TE"]:
            p_names = res[res["position"] == pos].sort_values(by="ufl_pts", ascending=False)["name"].tolist()
            pos_rank[pos] = set(p_names[:2]) # Top 2 per position

        for _, row in res.iterrows():
            pos = row["position"]
            p_name = row["name"]
            
            if pos in at_risk_pos and p_name in pos_rank.get(pos, set()):
                at_risk_flags.append(True)
                threat_notes.append(f"⚠️ At Risk: Opponents before your turn are targeting {pos}")
            else:
                at_risk_flags.append(False)
                threat_notes.append("")

        res["at_risk"] = at_risk_flags
        res["steal_threat"] = threat_notes
        return res
