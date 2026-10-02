"""
UFL Custom Scoring Calculator Engine.
Calculates custom fantasy points based on 0.2 pts/yd rushing & receiving multipliers.
Applies to all quarters (Q1, Q2, etc.) — the quarter context is managed by the synthesizer.
"""



def calculate_ufl_points(stats: dict, rules: dict) -> float:
    """
    Calculates total UFL fantasy points for a given set of stats.
    
    Rules dict must contain scoring coefficients (loaded from config.json):
    - Rushing: 1 pt / 5 yds (0.2 pts/yd) + 6 pt TD
    - Receiving: 0.3 PPR + 1 pt / 5 yds (0.2 pts/yd) + 6 pt TD
    - Passing: 1 pt / 25 yds (0.04 pts/yd) + 4 pt TD - 2 pt INT
    - 2-pt Conversions: 2 pts
    """

    pass_yds = stats.get("pass_yds", 0.0)
    pass_tds = stats.get("pass_tds", 0.0)
    pass_ints = stats.get("pass_ints", 0.0)
    
    rush_yds = stats.get("rush_yds", 0.0)
    rush_tds = stats.get("rush_tds", 0.0)
    
    receptions = stats.get("receptions", 0.0)
    rec_yds = stats.get("rec_yds", 0.0)
    rec_tds = stats.get("rec_tds", 0.0)
    
    two_pts = stats.get("two_pts", 0.0)

    # Passing
    pts_pass_yds = pass_yds / rules["pass_yds_per_pt"]
    pts_pass_tds = pass_tds * rules["pass_td_pts"]
    pts_pass_ints = pass_ints * rules["pass_int_pts"]

    # Rushing (0.2 pts/yd)
    pts_rush_yds = rush_yds / rules["rush_yds_per_pt"]
    pts_rush_tds = rush_tds * rules["rush_td_pts"]

    # Receiving (0.3 PPR + 0.2 pts/yd)
    pts_rec = receptions * rules["rec_pts"]
    pts_rec_yds = rec_yds / rules["rec_yds_per_pt"]
    pts_rec_tds = rec_tds * rules["rec_td_pts"]

    # 2-pt
    pts_two_pts = two_pts * rules["two_pt_pts"]

    total = (
        pts_pass_yds + pts_pass_tds + pts_pass_ints +
        pts_rush_yds + pts_rush_tds +
        pts_rec + pts_rec_yds + pts_rec_tds +
        pts_two_pts
    )
    return round(total, 2)

def calculate_ceiling_pts(base_pts: float, position: str) -> float:
    """
    Estimates 4-week maximum spike-week ceiling potential.
    WRs and RBs under 0.20 pt/yd rules have ~25-30% ceiling volatility,
    while QBs operate at ~15% ceiling volatility.
    """
    multipliers = {
        "WR": 1.28,
        "RB": 1.24,
        "TE": 1.20,
        "QB": 1.15,
        "FLEX": 1.25
    }
    mult = multipliers.get(position, 1.20)
    return round(base_pts * mult, 1)

def calculate_floor_pts(base_pts: float, position: str) -> float:
    """
    Estimates 4-week minimum safe floor potential.
    QBs have highest volume floor (~85%), followed by bellcow RBs.
    """
    multipliers = {
        "QB": 0.88,
        "RB": 0.82,
        "WR": 0.78,
        "TE": 0.75,
        "FLEX": 0.80
    }
    mult = multipliers.get(position, 0.80)
    return round(base_pts * mult, 1)

