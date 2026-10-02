"""
Database & Mock Simulator UI Module (Tab 3).
All-players database and interactive 72-pick mock draft with final standings.
"""

import os
import tempfile
import pandas as pd
import streamlit as st

from engine.draft_state import DraftState
from engine.vorp_calculator import VORPCalculator
from engine.joint_optimizer import JointOptimizer


def render_mock_simulator(draft_state, projections_df, vorp_df, selected_strategy_key, config_path):
    """Renders the Database & Mock Simulator tab."""
    col_db1, col_db2 = st.columns([1, 1])

    with col_db1:
        st.subheader("All Players Database", anchor=False)
        only_avail = st.checkbox("Show only available players", value=True)
        display_df = vorp_df.copy()
        if only_avail:
            display_df = display_df[~display_df["name"].str.lower().isin(draft_state.drafted_players)]
        cols_show = ["name", "position", "team", "vorp", "ceiling_pts", "floor_pts", "ufl_pts"]
        avail_cols = [c for c in cols_show if c in display_df.columns]
        st.dataframe(display_df[avail_cols], width="stretch", hide_index=True)

    with col_db2:
        st.subheader("🎲 Interactive Mock Draft Simulator", anchor=False)
        st.caption(f"Test strategy (`{selected_strategy_key}`) across 72 picks.")
        
        if st.button("🚀 Run 72-Pick Simulation", type="primary", width="stretch"):
            sim_state_fd, sim_state_path = tempfile.mkstemp(suffix=".json", prefix="sim_draft_")
            os.close(sim_state_fd)
            try:
                sim_ds = DraftState(config_path, sim_state_path)
                sim_ds.reset_draft()
                sim_calc = VORPCalculator(sim_ds.roster_limits)
                
                sim_logs = []
                for pick_no in range(1, 73):
                    curr_pick_i = sim_ds.current_pick_info()
                    if not curr_pick_i:
                        break
                    gov = curr_pick_i["governor"]
                    eval_strat = selected_strategy_key if gov == draft_state.my_team else "AUTO"
                    v_df = sim_calc.compute_vorp(projections_df, sim_ds, macro_strategy=eval_strat, governor=gov)
                    if v_df.empty:
                        break
                    valid_df = v_df[v_df["marginal_gain"] > -900.0].copy()
                    top_p = valid_df.iloc[0] if not valid_df.empty else v_df.iloc[0]
                    sim_ds.record_pick(top_p["name"], top_p["position"], top_p["team"], top_p["ufl_pts"], governor=gov)
                    sim_logs.append({
                        "Pick #": pick_no,
                        "Round": curr_pick_i["round"],
                        "Governor": gov,
                        "Player": top_p["name"],
                        "Pos": top_p["position"],
                        "UFL Pts": top_p["ufl_pts"]
                    })
                st.success("✅ Simulation Completed!")
                st.dataframe(pd.DataFrame(sim_logs), width="stretch", hide_index=True)

                # NEW: Show final standings after simulation
                st.markdown("---")
                tq = draft_state.config.get("target_quarter", "Q2")
                st.markdown(f"##### 🏆 Simulated Final {tq} Standings")
                standings_optimizer = JointOptimizer(sim_ds.roster_limits)
                sim_standings = []
                for gov in sim_ds.governors:
                    r_list = sim_ds.rosters.get(gov, [])
                    details = standings_optimizer.get_optimal_lineup_details(r_list, projections_df=projections_df)
                    is_user = " ⭐" if gov == draft_state.my_team else ""
                    starter_pts = details.get("starter_q2_pts", details.get("starter_q1_pts", 0.0))
                    total_pts = details.get("total_roster_q2_pts", details.get("total_roster_q1_pts", 0.0))
                    sim_standings.append({
                        "Governor": f"{gov}{is_user}",
                        "Drafted": len(r_list),
                        "Starter PPG": round(details["starter_weekly_ppg"], 1),
                        f"Starter {tq} Pts": round(starter_pts, 1),
                        f"Total Roster {tq} Pts": round(total_pts, 1),
                        "Efficiency": f"{details['starter_efficiency_pct']:.1f}%",
                    })
                sim_standings_df = pd.DataFrame(sim_standings).sort_values(by=f"Starter {tq} Pts", ascending=False).reset_index(drop=True)
                st.dataframe(sim_standings_df, width="stretch", hide_index=True)

                # Highlight user team result
                user_row = next((s for s in sim_standings if draft_state.my_team in s["Governor"]), None)
                if user_row:
                    rank = sim_standings_df[sim_standings_df["Governor"].str.contains(draft_state.my_team)].index[0] + 1
                    st.info(f"📊 **Your team (`{draft_state.my_team}`)** finished **#{rank} of 6** with **{user_row[f'Starter {tq} Pts']} {tq} Pts** ({user_row['Starter PPG']} PPG)")

            finally:
                if os.path.exists(sim_state_path):
                    os.unlink(sim_state_path)
