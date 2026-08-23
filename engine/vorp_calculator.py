"""
UFL 4-Week Joint Optimization, Positional Cliff & Squeeze Calculator Engine.
Uses Joint Lineup Optimization (Knapsack Lineup Solver) to evaluate exact
Marginal Portfolio Gains for candidate picks, detects positional cliffs,
and evaluates floor/ceiling spike-week volatility splits.
"""

import pandas as pd
from typing import Dict, List, Tuple, Optional
from engine.joint_optimizer import JointOptimizer
from engine.scoring import calculate_ceiling_pts, calculate_floor_pts

class VORPCalculator:
    def __init__(self, roster_settings: dict):
        self.roster_settings = roster_settings
        self.joint_optimizer = JointOptimizer(roster_settings)

    def compute_vorp(
        self,
        df: pd.DataFrame,
        draft_state=None,
        macro_strategy: str = "AUTO",
        mode: str = "BALANCED",
        governor: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Calculates exact Joint Portfolio Gains for all un-drafted players.
        Applies strategy presets, stacking bonuses, and floor/ceiling splits.
        """
        if df.empty:
            return df

        if draft_state:
            undrafted_df = df[~df["name"].str.lower().isin(draft_state.drafted_players)].copy()
        else:
            undrafted_df = df.copy()

        if undrafted_df.empty:
            return undrafted_df

        if draft_state:
            res_df = self.joint_optimizer.evaluate_candidate_picks(
                undrafted_df,
                draft_state,
                macro_strategy=macro_strategy,
                governor=governor
            )
        else:
            res_df = undrafted_df.copy()
            res_df["vorp"] = res_df["ufl_pts"]
            res_df["marginal_gain"] = res_df["ufl_pts"]
            res_df["roster_need"] = "OPENING"

        # Calculate Floor and Ceiling columns
        res_df["ceiling_pts"] = res_df.apply(lambda r: calculate_ceiling_pts(r["ufl_pts"], r["position"]), axis=1)
        res_df["floor_pts"] = res_df.apply(lambda r: calculate_floor_pts(r["ufl_pts"], r["position"]), axis=1)

        if mode == "CEILING":
            res_df["vorp"] = res_df.apply(lambda r: round(r["vorp"] * 1.15 if r["position"] in ["WR", "RB"] and r["vorp"] > 0 else r["vorp"], 2), axis=1)
            res_df["marginal_gain"] = res_df["vorp"]
        elif mode == "FLOOR":
            res_df["vorp"] = res_df.apply(lambda r: round(r["vorp"] * 1.10 if r["position"] == "QB" and r["vorp"] > 0 else (r["vorp"] * 0.90 if r["position"] in ["WR", "TE"] and r["vorp"] > 0 else r["vorp"]), 2), axis=1)
            res_df["marginal_gain"] = res_df["vorp"]

        res_df = res_df.sort_values(by="vorp", ascending=False).reset_index(drop=True)
        return res_df

    def detect_positional_cliffs(self, df: pd.DataFrame, draft_state) -> List[Dict]:
        """
        Detects imminent positional cliffs where remaining available talent drops off sharply.
        """
        if df.empty or not draft_state:
            return []

        undrafted_df = df[~df["name"].str.lower().isin(draft_state.drafted_players)].copy()
        cliffs = []

        for pos in ["RB", "WR", "QB", "TE"]:
            pos_df = undrafted_df[undrafted_df["position"] == pos].sort_values(by="ufl_pts", ascending=False)
            if len(pos_df) < 2:
                continue

            top_pts = pos_df.iloc[0]["ufl_pts"]
            second_pts = pos_df.iloc[1]["ufl_pts"]
            third_pts = pos_df.iloc[2]["ufl_pts"] if len(pos_df) >= 3 else second_pts * 0.8

            drop_1_to_2 = top_pts - second_pts
            drop_2_to_3 = second_pts - third_pts

            if drop_1_to_2 >= 15.0 or (top_pts >= 50.0 and len(pos_df) <= 3):
                cliffs.append({
                    "position": pos,
                    "top_player": pos_df.iloc[0]["name"],
                    "top_pts": top_pts,
                    "next_best_pts": second_pts,
                    "drop_off": round(drop_1_to_2, 1),
                    "remaining_in_tier": 1,
                    "severity": "CRITICAL" if drop_1_to_2 >= 20.0 else "WARNING",
                    "message": f"🚨 {pos} CLIFF ALERT: **{pos_df.iloc[0]['name']}** ({top_pts:.1f} pts) is the last Tier-1 {pos}. Drop to next best is -{drop_1_to_2:.1f} pts!"
                })
            elif drop_2_to_3 >= 12.0:
                cliffs.append({
                    "position": pos,
                    "top_player": pos_df.iloc[0]["name"],
                    "top_pts": top_pts,
                    "next_best_pts": third_pts,
                    "drop_off": round(drop_2_to_3, 1),
                    "remaining_in_tier": 2,
                    "severity": "NOTICE",
                    "message": f"⚠️ {pos} TIER BREAK: Only 2 high-tier {pos}s remain ({pos_df.iloc[0]['name']}, {pos_df.iloc[1]['name']}) before a -{drop_2_to_3:.1f} pt cliff."
                })

        return cliffs

    def check_qb_squeeze(self, df: pd.DataFrame, draft_state) -> Tuple[bool, str]:
        """
        Checks if opponents are hoarding QBs and triggering a QB supply squeeze.
        Calibrated for Q1 UFL 4-week scoring (top QBs score ~35–50 UFL pts).
        """
        if not draft_state or df.empty:
            return False, ""

        undrafted_qbs = df[(df["position"] == "QB") & (~df["name"].str.lower().isin(draft_state.drafted_players))]
        # Top-tier QBs for Q1 UFL scoring (>= 35.0 UFL pts for 4 weeks)
        top_tier_qbs = undrafted_qbs[undrafted_qbs["ufl_pts"] >= 35.0]

        my_qb_count = draft_state.get_governor_roster_breakdown(draft_state.my_team)["QB"]
        picks_remaining = draft_state.picks_until_my_turn()

        if my_qb_count < 2 and len(top_tier_qbs) <= 3 and picks_remaining > 2:
            return True, f"CRITICAL QB SQUEEZE: Only {len(top_tier_qbs)} top-tier QBs remain before your next pick in {picks_remaining} picks! Prioritize QB now."

        return False, ""
