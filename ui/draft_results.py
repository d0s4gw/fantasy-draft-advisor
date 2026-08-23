"""
Draft Results UI Module (Tab 2).
Visual draft board, standings, positional chart, and optimal lineup viewer.
"""

import pandas as pd
import streamlit as st
from engine.joint_optimizer import JointOptimizer


def render_draft_results(draft_state, projections_df):
    """Renders the Draft Results tab with standings, charts, and lineup viewer."""
    st.subheader("Visual 6 Governors × 12 Rounds Draft Board", anchor=False)
    matrix_data = {r: ["" for _ in draft_state.governors] for r in range(1, 13)}
    for pick in draft_state.picks_history:
        r = pick["round"]
        gov = pick["governor"]
        gov_idx = draft_state.governors.index(gov) if gov in draft_state.governors else 0
        matrix_data[r][gov_idx] = f"{pick['player_name']} ({pick['position']})"
        
    grid_df = pd.DataFrame(matrix_data, index=draft_state.governors).T
    st.dataframe(grid_df, width="stretch")

    st.divider()

    # HEADER & VIEW SCALE CONTROL
    c_hdr1, c_hdr2 = st.columns([2, 1])
    with c_hdr1:
        st.subheader("Live Projected Standings & Best Lineup Analysis", anchor=False)
    with c_hdr2:
        proj_scale = st.segmented_control(
            "Projections View Mode",
            ["Weekly Average (PPG)", "Quarter Total (Q1)"],
            default="Weekly Average (PPG)",
            key="segmented_proj_scale"
        )

    is_weekly = (proj_scale == "Weekly Average (PPG)")
    val_suffix = "PPG" if is_weekly else "Pts"

    standings_optimizer = JointOptimizer(draft_state.roster_limits)
    
    # Compute detailed optimal lineup data for all Governors
    gov_details_map = {}
    standings_list = []
    chart_rows = []

    for gov in draft_state.governors:
        r_list = draft_state.rosters.get(gov, [])
        details = standings_optimizer.get_optimal_lineup_details(r_list, projections_df=projections_df)
        gov_details_map[gov] = details

        starter_val = round(details["starter_weekly_ppg"] if is_weekly else details["starter_q1_pts"], 1)
        total_roster_val = round(details["total_roster_weekly_ppg"] if is_weekly else details["total_roster_q1_pts"], 1)
        pos_vals = details["positional_ppg"] if is_weekly else details["positional_breakdown"]

        standings_list.append({
            "Governor": gov,
            "Drafted": len(r_list),
            "Starters Filled": f"{details['starters_filled']}/7",
            f"Starter {val_suffix}": starter_val,
            f"QB {val_suffix}": round(pos_vals["QB"], 1),
            f"RB {val_suffix}": round(pos_vals["RB"], 1),
            f"WR {val_suffix}": round(pos_vals["WR"], 1),
            f"TE {val_suffix}": round(pos_vals["TE"], 1),
            f"FLEX {val_suffix}": round(pos_vals["FLEX"], 1),
            "Starter Efficiency": f"{details['starter_efficiency_pct']:.1f}%",
            f"Total Roster {val_suffix}": total_roster_val
        })

        for pos_grp, p_val in pos_vals.items():
            chart_rows.append({
                "Governor": gov,
                "Position": pos_grp,
                "Points": round(p_val, 1)
            })

    standings_df = pd.DataFrame(standings_list).sort_values(by=f"Starter {val_suffix}", ascending=False).reset_index(drop=True)
    
    st.markdown("##### 🏆 Roster Standings & Positional Output Matrix")
    st.dataframe(standings_df, width="stretch", hide_index=True)

    st.markdown("---")

    # STACKED POSITIONAL COMPARISON CHART
    st.markdown("##### 📊 Starter Power Rankings by Position Group")
    chart_df = pd.DataFrame(chart_rows)
    if not chart_df.empty:
        # Pivot for st.bar_chart stack
        pivoted_chart = chart_df.pivot(index="Governor", columns="Position", values="Points")[["QB", "RB", "WR", "TE", "FLEX"]].fillna(0.0)
        st.bar_chart(pivoted_chart, stack=True, height=300, width="stretch")

    st.markdown("---")

    # INTERACTIVE ROSTER BEST LINEUP VIEWER
    st.markdown("##### 🏈 Roster Best Lineup & Depth Chart Viewer")
    selected_gov = st.segmented_control(
        "Select Governor Roster",
        draft_state.governors,
        default=draft_state.my_team if draft_state.my_team in draft_state.governors else draft_state.governors[0],
        key="sel_gov_lineup_card"
    )

    if selected_gov and selected_gov in gov_details_map:
        sel_details = gov_details_map[selected_gov]
        
        # Metric Cards Banner
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        with m_col1:
            st.metric(
                "Optimal 7-Starter Score",
                f"{sel_details['starter_weekly_ppg']:.1f} PPG",
                delta=f"{sel_details['starter_q1_pts']:.1f} Q1 Pts"
            )
        with m_col2:
            st.metric(
                "Total Roster Score",
                f"{sel_details['total_roster_weekly_ppg']:.1f} PPG",
                delta=f"{sel_details['total_roster_q1_pts']:.1f} Q1 Pts"
            )
        with m_col3:
            st.metric(
                "Starter Efficiency Ratio",
                f"{sel_details['starter_efficiency_pct']:.1f}%",
                help="Ratio of starting lineup points to total roster points."
            )
        with m_col4:
            bench_top = sel_details["best_bench_player"]
            if bench_top:
                b_name = bench_top.get("name") or bench_top.get("player_name") or ""
                st.metric(
                    "Top Bench Backup",
                    f"{b_name} ({bench_top['position']})",
                    delta=f"{bench_top['ufl_pts'] / 4.0:.1f} PPG"
                )
            else:
                st.metric("Top Bench Backup", "None", delta="0.0 PPG")

        st.markdown("#### ⚡ Optimal 7-Player Starting Lineup")
        starter_slots = [
            ("QB 1 Slot", "QB1"),
            ("QB 2 Slot", "QB2"),
            ("RB Slot", "RB1"),
            ("WR Slot", "WR1"),
            ("TE Slot", "TE1"),
            ("FLEX 1 Slot", "FLEX1"),
            ("FLEX 2 Slot", "FLEX2")
        ]

        col_st1, col_st2 = st.columns(2)
        for idx, (label, slot_key) in enumerate(starter_slots):
            target_col = col_st1 if idx % 2 == 0 else col_st2
            p_obj = sel_details["starters"].get(slot_key)
            with target_col:
                with st.container(border=True):
                    if p_obj:
                        q1_p = p_obj["ufl_pts"]
                        ppg_p = q1_p / 4.0
                        p_name = p_obj.get("name") or p_obj.get("player_name") or ""
                        st.markdown(f"**{label}**: `{p_name}` ({p_obj['position']} • {p_obj['team']})")
                        st.caption(f"Q1 Projection: **{q1_p:.1f} pts** ({ppg_p:.1f} PPG)")
                    else:
                        st.markdown(f"**{label}**: ⚠️ *VACANT SLOT*")
                        st.caption("Projected output: **0.0 pts** (Need to draft player)")

        st.markdown("#### 🛡️ Bench Roster Depth")
        bench_list = sel_details.get("bench", [])
        if not bench_list:
            st.caption("No players on bench yet.")
        else:
            b_display = []
            for bp in bench_list:
                bp_name = bp.get("name") or bp.get("player_name") or ""
                b_display.append({
                    "Player": bp_name,
                    "Position": bp["position"],
                    "Team": bp["team"],
                    "Q1 Pts": f"{bp['ufl_pts']:.1f}",
                    "Weekly PPG": f"{bp['ufl_pts'] / 4.0:.1f}"
                })
            st.dataframe(pd.DataFrame(b_display), width="stretch", hide_index=True)
