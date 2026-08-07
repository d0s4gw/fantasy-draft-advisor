"""
UFL 12-Round (72 Pick) Full Mock Draft Simulator.
Simulates smart 6-Governor drafting from Pick #1 to Pick #72,
testing roster-aware VORP calculations, position fills, and final standings.
"""

import os
import pandas as pd
from engine.projection_synth import ProjectionSynthesizer
from engine.draft_state import DraftState
from engine.vorp_calculator import VORPCalculator

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
STATE_PATH = os.path.join(DATA_DIR, "draft_state.json")

def run_simulation():
    print("=" * 70)
    print("🏈 STARTING FULL 12-ROUND (72 PICK) UFL MOCK DRAFT SIMULATION")
    print("=" * 70)

    # Initialize engines
    synth = ProjectionSynthesizer(DATA_DIR)
    projections_df = synth.synthesize()
    draft_state = DraftState(CONFIG_PATH, STATE_PATH)
    draft_state.reset_draft()
    vorp_calc = VORPCalculator(draft_state.roster_limits)

    # Execute 72 picks in order
    for pick_no in range(1, 73):
        curr_pick = draft_state.current_pick_info()
        gov = curr_pick["governor"]
        round_no = curr_pick["round"]

        # Compute recommendations for current governor
        vorp_df = vorp_calc.compute_vorp(projections_df, draft_state, governor=gov)

        if vorp_df.empty:
            print(f"Pick #{pick_no}: No players remaining!")
            break

        # Pick top recommended player
        top_player = vorp_df.iloc[0]
        p_name = top_player["name"]
        p_pos = top_player["position"]
        p_team = top_player["team"]
        p_pts = top_player["ufl_pts"]
        need = top_player.get("roster_need", "BENCH")

        # Record pick
        draft_state.record_pick(p_name, p_pos, p_team, p_pts, governor=gov)

        print(f"Pick #{pick_no:02d} (R{round_no:02d}) [{gov:<15}]: {p_name:<22} ({p_pos:<2}, {p_team:<3}) — UFL Pts: {p_pts:>5.1f} | {need}")

    print("\n" + "=" * 70)
    print("🏆 FINAL PROJECTED Q1 STANDINGS & POINTS")
    print("=" * 70)

    from engine.joint_optimizer import JointOptimizer
    standings_optimizer = JointOptimizer(draft_state.roster_limits)
    standings = []
    for gov in draft_state.governors:
        r_list = draft_state.rosters.get(gov, [])
        starter_pts = standings_optimizer.solve_weekly_starting_lineup(r_list)
        total_pts = sum(p["ufl_pts"] for p in r_list)
        pos_counts = draft_state.get_governor_roster_breakdown(gov)
        standings.append({
            "Governor": gov,
            "Starter Pts": round(starter_pts, 1),
            "Starter PPG": round(starter_pts / 4.0, 1),
            "Total Roster Pts": round(total_pts, 1),
            "Roster": f"QBs: {pos_counts['QB']}, RBs: {pos_counts['RB']}, WRs: {pos_counts['WR']}, TEs: {pos_counts['TE']}"
        })

    standings_df = pd.DataFrame(standings).sort_values(by="Starter Pts", ascending=False).reset_index(drop=True)
    print(standings_df.to_string(index=False))

    print("\n" + "=" * 70)
    print(f"📋 GOVERNOR ROSTERS DETAIL ({draft_state.my_team.upper()} - MY TEAM)")
    print("=" * 70)
    my_roster = draft_state.rosters.get(draft_state.my_team, [])
    my_df = pd.DataFrame(my_roster)[["pick_no", "round", "player_name", "position", "team", "ufl_pts"]]
    print(my_df.to_string(index=False))

if __name__ == "__main__":
    run_simulation()
