"""
Draft Strategy Presets & Macro Strategy Engine.
Provides dynamic positional weight modifiers and strategy heuristics
for Hero RB, Zero RB, Robust RB, Elite TE Anchor, and Pure VORP strategies.
"""

from typing import Dict, List

STRATEGY_PRESETS = {
    "AUTO": {
        "name": "Auto VORP (Dynamic)",
        "description": "Dynamically selects optimal strategy based on draft position and available player tiers."
    },
    "PURE_VORP": {
        "name": "Pure Math VORP",
        "description": "Unmodified 4-week Knapsack lineup optimization score."
    },
    "HERO_RB": {
        "name": "Hero RB",
        "description": "Anchor 1 elite RB in Rounds 1-2, then load WRs & QBs before securing RB2."
    },
    "ZERO_RB": {
        "name": "Zero RB",
        "description": "Pass on RBs in Rounds 1-4. Maximize WR, QB, & TE elite volume, targeting late-round RB value."
    },
    "ROBUST_RB": {
        "name": "Robust Dual RB",
        "description": "Lock in 2 workhorse bellcow RBs in Rounds 1-3 to maximize UFL 0.20 pt/yd rushing multiplier."
    },
    "ELITE_TE": {
        "name": "Elite TE Anchor",
        "description": "Prioritize a top-tier TE1 in Rounds 3-4 to gain a massive positional advantage over opponents."
    }
}

class StrategyPresetManager:
    @staticmethod
    def get_positional_multiplier(
        strategy: str,
        position: str,
        current_roster: List[Dict],
        round_no: int,
        undrafted_df=None,
        roster_requirements: Dict = None
    ) -> float:
        """
        Returns a scaling multiplier (e.g. 0.8 to 1.35) for candidate VORP calculations
        based on the active macro strategy, position, roster state, and round number.
        
        For AUTO strategy, dynamically adapts based on available player tiers,
        positional scarcity, and roster construction needs.
        """
        rb_count = len([p for p in current_roster if p.get("position") == "RB"])
        wr_count = len([p for p in current_roster if p.get("position") == "WR"])
        qb_count = len([p for p in current_roster if p.get("position") == "QB"])
        te_count = len([p for p in current_roster if p.get("position") == "TE"])

        if strategy == "PURE_VORP":
            return 1.0

        if strategy == "AUTO":
            return StrategyPresetManager._auto_dynamic_multiplier(
                position, current_roster, round_no,
                qb_count, rb_count, wr_count, te_count,
                undrafted_df, roster_requirements
            )

        if strategy == "HERO_RB":
            if round_no <= 2:
                if position == "RB" and rb_count == 0:
                    return 1.25 # Boost first RB
                elif position == "RB" and rb_count >= 1:
                    return 0.80 # Deprioritize RB2 early
            elif round_no in [3, 4, 5]:
                if position == "RB" and rb_count == 1:
                    return 0.85 # Hold off on RB2 until mid rounds
                elif position in ["WR", "QB"]:
                    return 1.15

        elif strategy == "ZERO_RB":
            if round_no <= 4:
                if position == "RB":
                    return 0.70 # Heavy penalty on early RBs
                elif position in ["WR", "QB", "TE"]:
                    return 1.20 # Boost early pass-catchers and QBs
            elif round_no >= 5:
                if position == "RB" and rb_count < 2:
                    return 1.25 # Boost high-upside RBs in mid rounds

        elif strategy == "ROBUST_RB":
            if round_no <= 3:
                if position == "RB" and rb_count < 2:
                    return 1.30 # Heavily prioritize early dual RBs
            elif round_no in [4, 5, 6]:
                if position in ["WR", "QB"]:
                    return 1.15

        elif strategy == "ELITE_TE":
            if round_no in [3, 4] and te_count == 0:
                if position == "TE":
                    return 1.35 # Heavy push for elite TE anchor in rounds 3-4

        return 1.0

    @staticmethod
    def _auto_dynamic_multiplier(
        position: str,
        current_roster: List[Dict],
        round_no: int,
        qb_count: int,
        rb_count: int,
        wr_count: int,
        te_count: int,
        undrafted_df=None,
        roster_requirements: Dict = None
    ) -> float:
        """
        Implements the AUTO strategy with 5 adaptive triggers:
        1. QB Squeeze Detection
        2. RB Cliff Urgency
        3. Elite TE Window
        4. Late-Round Roster Compliance
        5. WR Volume Loading
        
        All triggers are evaluated independently; the highest applicable
        multiplier wins (max-of-all, not first-match).
        """
        mult = 1.0

        # Default roster requirements (no-waiver league)
        req = roster_requirements or {"QB": 3, "RB": 3, "WR": 3, "TE": 2}

        # --- Trigger 1: QB Squeeze Detection ---
        # If ≤3 top-tier QBs (≥35 UFL pts) remain and user has <2 QBs, boost QB
        if position == "QB" and qb_count < 2 and undrafted_df is not None:
            top_tier_qbs = undrafted_df[
                (undrafted_df["position"] == "QB") & (undrafted_df["ufl_pts"] >= 35.0)
            ]
            if len(top_tier_qbs) <= 3:
                mult = max(mult, 1.25)

        # --- Trigger 2: RB Cliff Urgency ---
        # If #1 available RB is ≥20 pts above #2 in Rounds 1-3 and user has 0 RBs
        if position == "RB" and rb_count == 0 and round_no <= 3 and undrafted_df is not None:
            avail_rbs = undrafted_df[undrafted_df["position"] == "RB"].sort_values(
                by="ufl_pts", ascending=False
            )
            if len(avail_rbs) >= 2:
                gap = avail_rbs.iloc[0]["ufl_pts"] - avail_rbs.iloc[1]["ufl_pts"]
                if gap >= 20.0:
                    mult = max(mult, 1.20)

        # --- Trigger 3: Elite TE Window ---
        # If only 1 elite TE (≥50 UFL pts) remains and user has 0 TEs in Rounds 3-5
        if position == "TE" and te_count == 0 and 3 <= round_no <= 5 and undrafted_df is not None:
            elite_tes = undrafted_df[
                (undrafted_df["position"] == "TE") & (undrafted_df["ufl_pts"] >= 50.0)
            ]
            if len(elite_tes) == 1:
                mult = max(mult, 1.30)

        # --- Trigger 4: Late-Round Roster Compliance ---
        # In Rounds 9+, boost positions where user is short of roster minimums
        if round_no >= 9:
            shortfall = {
                "QB": max(0, req.get("QB", 3) - qb_count),
                "RB": max(0, req.get("RB", 3) - rb_count),
                "WR": max(0, req.get("WR", 3) - wr_count),
                "TE": max(0, req.get("TE", 2) - te_count),
            }
            if shortfall.get(position, 0) > 0:
                mult = max(mult, 1.20)

        # --- Trigger 5: WR Volume Loading ---
        # In Rounds 3-6, if user has ≤1 WR, boost WR to ensure FLEX depth
        if position == "WR" and wr_count <= 1 and 3 <= round_no <= 6:
            mult = max(mult, 1.15)

        return mult

