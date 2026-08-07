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
    def get_positional_multiplier(strategy: str, position: str, current_roster: List[Dict], round_no: int) -> float:
        """
        Returns a scaling multiplier (e.g. 0.8 to 1.3) for candidate VORP calculations
        based on the active macro strategy, position, roster state, and round number.
        """
        rb_count = len([p for p in current_roster if p.get("position") == "RB"])
        te_count = len([p for p in current_roster if p.get("position") == "TE"])

        if strategy == "PURE_VORP" or strategy == "AUTO":
            return 1.0

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
