"""
Engine 2: Live Joint Math Optimizer Engine.
Uses JointOptimizer to evaluate real-time marginal portfolio gains on the fly.
"""

import pandas as pd
from typing import Dict, Any, List
from engine.base_engine import DraftEngineBase
from engine.joint_optimizer import JointOptimizer

class LiveMathEngine(DraftEngineBase):
    def __init__(self, roster_settings: dict):
        self.optimizer = JointOptimizer(roster_settings)

    def recommend_from_vorp(self, res_df: pd.DataFrame, draft_state) -> Dict[str, Any]:
        if res_df.empty:
            return {
                "top_qbs": [], "top_rbs": [], "top_wrs": [], "top_tes": [],
                "best_decision": None, "advice_text": "No players remaining.", "engine_name": "Engine 2: Live Joint Math Optimizer"
            }

        gain_col = "marginal_gain" if "marginal_gain" in res_df.columns else "vorp"
        valid_res = res_df[res_df[gain_col] > -900.0] if gain_col in res_df.columns else res_df

        def extract_top_5(pos: str) -> List[Dict]:
            pos_df = valid_res[valid_res["position"] == pos].head(5)
            res = []
            for _, r in pos_df.iterrows():
                res.append({
                    "name": r["name"],
                    "position": r["position"],
                    "team": r["team"],
                    "ufl_pts": r["ufl_pts"],
                    "q1_pts": float(r.get("q1_pts", 0.0)),
                    "ppg": round(r["ufl_pts"] / 4.0, 1),
                    "marginal_gain": r.get("marginal_gain", r.get("vorp", 0.0)),
                    "adp": r.get("adp", 99.0),
                    "ai_insight": r.get("roster_need", "FLEX / BENCH")
                })
            return res

        top_qbs = extract_top_5("QB")
        top_rbs = extract_top_5("RB")
        top_wrs = extract_top_5("WR")
        top_tes = extract_top_5("TE")
        top_player = valid_res.iloc[0] if not valid_res.empty else res_df.iloc[0]
        m_gain = top_player.get(gain_col, 0.0)
        best_candidate = {
            "name": top_player["name"],
            "position": top_player["position"],
            "team": top_player["team"],
            "ufl_pts": top_player["ufl_pts"],
            "q1_pts": float(top_player.get("q1_pts", 0.0)),
            "ppg": round(top_player["ufl_pts"] / 4.0, 1),
            "marginal_gain": m_gain
        }

        advice = f"**Primary Math Decision**: **{best_candidate['name']}** ({best_candidate['position']}, {best_candidate['team']}) — Adds **+{best_candidate['marginal_gain']:.1f} Net Portfolio Points** across 4 weeks."

        return {
            "top_qbs": top_qbs,
            "top_rbs": top_rbs,
            "top_wrs": top_wrs,
            "top_tes": top_tes,
            "best_decision": best_candidate,
            "advice_text": advice,
            "engine_name": "Engine 2: Live Joint Math Optimizer"
        }

    def recommend(self, projections_df: pd.DataFrame, draft_state) -> Dict[str, Any]:
        res_df = self.optimizer.evaluate_candidate_picks(projections_df, draft_state)
        return self.recommend_from_vorp(res_df, draft_state)

    def generate_war_room_matrix(self, projections_df: pd.DataFrame, draft_state, macro_strategy: str = "AUTO", seed: int = None) -> Dict[str, Any]:
        return self.optimizer.compute_turn_decision_matrix(draft_state, projections_df, macro_strategy=macro_strategy, seed=seed)

