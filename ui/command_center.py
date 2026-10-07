"""
Draft Command Center UI Module (Tab 1).
On-clock status, recommendations, cliff alerts, QB squeeze, war room, positional columns.
"""

import pandas as pd
import streamlit as st
from typing import Dict, List


def render_command_center(
    draft_state, projections_df, rec_projections_df, vorp_df, vorp_calc,
    rec_result, active_engine, selected_strategy_key, selected_vorp_mode
):
    """Renders the Draft Command Center tab."""
    curr_pick_i = draft_state.current_pick_info()
    tq = draft_state.config.get("target_quarter", "Q2")
    if not curr_pick_i:
        st.success(f"🎉 **{tq} DRAFT COMPLETE!** All 72 picks have been recorded.")
        on_clock_gov = draft_state.my_team
    else:
        on_clock_gov = curr_pick_i["governor"]
        is_my_turn = (on_clock_gov == draft_state.my_team)
        if is_my_turn:
            st.error(f"🚨 **ON THE CLOCK ({tq})**: Pick #{curr_pick_i['pick_no']} (Round {curr_pick_i['round']}) — YOUR TURN (`{draft_state.my_team}`)")
        else:
            wait_picks = draft_state.picks_until_my_turn()
            st.info(f"⏳ **Draft Progress ({tq})**: Pick #{curr_pick_i['pick_no']} (Round {curr_pick_i['round']}) • On clock: `{on_clock_gov}` • **{wait_picks} picks until your turn**")

    # QB SQUEEZE ALERT
    squeeze_active, squeeze_msg = vorp_calc.check_qb_squeeze(projections_df, draft_state)
    if squeeze_active:
        st.warning(f"⚠️ **QB SQUEEZE WARNING**: {squeeze_msg}")

    # POSITIONAL CLIFF ALERTS
    cliffs = vorp_calc.detect_positional_cliffs(projections_df, draft_state)
    if cliffs:
        for cliff in cliffs:
            if cliff.get("severity") == "CRITICAL":
                st.warning(cliff["message"])
            else:
                st.info(cliff["message"])

    st.markdown("---")

    # TOP RECOMMENDATION CARD
    best_candidate = rec_result.get("best_decision")
    if best_candidate:
        c_rec1, c_rec2 = st.columns([3, 1])
        with c_rec1:
            best_pts = best_candidate.get('ufl_pts', 0.0)
            best_q1 = best_candidate.get('q1_pts', 0.0)
            q1_label = f" | Actual Q1: **{best_q1:.1f}** Pts" if best_q1 and best_q1 > 0 else ""
            st.markdown(f"### 🎯 Recommended Pick: **{best_candidate['name']}** ({best_candidate['position']} • {best_candidate['team']}) — Proj {tq}: **{best_pts:.1f}** Pts{q1_label}")
            st.markdown(rec_result.get("advice_text", ""))
        with c_rec2:
            if st.button("⚡ SLAM PICK", type="primary", width="stretch", help=f"Record {best_candidate['name']} to {on_clock_gov}"):
                p_info = projections_df[projections_df["name"] == best_candidate['name']].iloc[0]
                draft_state.record_pick(p_info["name"], p_info["position"], p_info["team"], p_info["ufl_pts"], governor=on_clock_gov)
                st.session_state.skipped_this_pick.clear()
                st.toast(f"Slammed {best_candidate['name']} to {on_clock_gov}!")
                st.rerun()

            if curr_pick_i and st.button("⏳ Not yet", width="stretch", help=f"Skip {best_candidate['name']} for Pick #{curr_pick_i['pick_no']}"):
                st.session_state.skipped_this_pick.add(best_candidate['name'])
                st.toast(f"Skipped {best_candidate['name']} for current pick!")
                st.rerun()

    # SKIPPED PLAYERS BANNER FOR ACTIVE PICK
    if st.session_state.skipped_this_pick:
        c_skip1, c_skip2 = st.columns([4, 1])
        with c_skip1:
            skipped_names = ", ".join(sorted(st.session_state.skipped_this_pick))
            st.caption(f"⏳ **Skipped for Pick #{curr_pick_i['pick_no'] if curr_pick_i else ''}**: `{skipped_names}`")
        with c_skip2:
            if st.button("↩️ Reset Skips", key="btn_reset_skips", width="stretch", help="Restore all skipped players for this pick"):
                st.session_state.skipped_this_pick.clear()
                st.toast("Restored all skipped players!")
                st.rerun()

    st.markdown("---")

    # TURN STRATEGY WAR ROOM (DECISION MATRIX)
    _render_war_room(draft_state, rec_projections_df, active_engine, selected_strategy_key, on_clock_gov, curr_pick_i)

    st.markdown("---")

    # POSITIONAL TOP 5 COLUMNS
    col_qb, col_rb, col_wr, col_te = st.columns(4)

    _render_position_column(col_qb, "🏈 Top QBs", rec_result.get("top_qbs", []), vorp_df, projections_df, draft_state, on_clock_gov)
    _render_position_column(col_rb, "🏃 Top RBs", rec_result.get("top_rbs", []), vorp_df, projections_df, draft_state, on_clock_gov)
    _render_position_column(col_wr, "⚡ Top WRs", rec_result.get("top_wrs", []), vorp_df, projections_df, draft_state, on_clock_gov)
    _render_position_column(col_te, "🛡️ Top TEs", rec_result.get("top_tes", []), vorp_df, projections_df, draft_state, on_clock_gov)


def _render_war_room(draft_state, rec_projections_df, active_engine, selected_strategy_key, on_clock_gov, curr_pick_i):
    """Renders the Turn Strategy War Room decision matrix."""
    tq = draft_state.config.get("target_quarter", "Q2")
    with st.expander(f"⚔️ **Turn Strategy War Room — {tq} Decision Matrix & Survival Odds**", expanded=(curr_pick_i is not None and on_clock_gov == draft_state.my_team)):
        c_war1, c_war2 = st.columns([4, 1])
        with c_war1:
            st.markdown(f"#### Real-Time Candidate Decision Matrix & Survival Simulations ({tq})")
        with c_war2:
            if st.button("🔄 Recalculate Matrix", key="btn_recalc_war_room", width="stretch"):
                st.cache_data.clear()
                st.rerun()

        war_room_data = active_engine.generate_war_room_matrix(rec_projections_df, draft_state, macro_strategy=selected_strategy_key)
        candidates_list = war_room_data.get("candidates", [])

        if not candidates_list:
            st.caption("No candidates available for War Room simulation.")
        else:
            st.info(f"💡 {war_room_data.get('executive_dilemma', '')}")
            if war_room_data.get("top_pair_recommendation"):
                st.caption(f"🤝 {war_room_data.get('top_pair_recommendation')}")

            st.markdown(f"##### 📊 {tq} Candidate Comparison Matrix")
            matrix_display = []
            for c in candidates_list:
                q1_pts_val = c.get("q1_pts", 0.0)
                q1_display = f"{q1_pts_val:.1f}" if q1_pts_val > 0 else "—"
                matrix_display.append({
                    "Action Badge": f"{c['badge']}",
                    "Bye Status": f"{c.get('bye_badge', '')}",
                    "Player": f"{c['name']} ({c['position']} • {c['team']})",
                    "Actual Q1 Pts": q1_display,
                    f"Proj {tq} Pts": f"{c['ufl_pts']:.1f}",
                    "Net Gain": f"+{c['marginal_gain']:.1f}",
                    "Survival Odds": f"{c['survival_pct']:.1f}%",
                    "Regret Cliff": f"-{c['regret_cliff']:.1f} Pts" if c['regret_cliff'] > 0 else "0.0 Pts",
                    "Sim Starter Range": f"{c['floor_10']:.0f} – {c['ceiling_90']:.0f} Pts",
                    "Recommended Follow-Up": c['recommended_pair']
                })

            st.dataframe(pd.DataFrame(matrix_display), width="stretch", hide_index=True)

            st.markdown("---")
            st.markdown("##### 🔬 Pairwise Delta Explorer")
            col_exp1, col_exp2 = st.columns(2)
            c_names = [c["name"] for c in candidates_list]

            if "sel_opt_a" in st.session_state and st.session_state["sel_opt_a"] not in c_names:
                del st.session_state["sel_opt_a"]
            if "sel_opt_b" in st.session_state and st.session_state["sel_opt_b"] not in c_names:
                del st.session_state["sel_opt_b"]

            kwargs_a = {"index": 0} if "sel_opt_a" not in st.session_state else {}
            kwargs_b = {"index": min(1, len(c_names)-1)} if "sel_opt_b" not in st.session_state else {}

            with col_exp1:
                p1_name = st.selectbox("Option A", c_names, key="sel_opt_a", **kwargs_a)
            with col_exp2:
                p2_name = st.selectbox("Option B", c_names, key="sel_opt_b", **kwargs_b)

            if p1_name and p2_name and p1_name != p2_name:
                p1_c = next(c for c in candidates_list if c["name"] == p1_name)
                p2_c = next(c for c in candidates_list if c["name"] == p2_name)

                gain_diff = round(p1_c["marginal_gain"] - p2_c["marginal_gain"], 1)
                surv_diff = round(p1_c["survival_pct"] - p2_c["survival_pct"], 1)
                cliff_diff = round(p1_c["regret_cliff"] - p2_c["regret_cliff"], 1)
                p1_q1 = p1_c.get("q1_pts", 0.0)
                p2_q1 = p2_c.get("q1_pts", 0.0)
                q1_diff = round(p1_q1 - p2_q1, 1)

                st.markdown(f"""
                **Head-to-Head Comparison ({p1_name} vs {p2_name})**:
                - 📈 **Net Portfolio Gain Delta**: `{'+' if gain_diff >= 0 else ''}{gain_diff} Pts`
                - 🎯 **Survival Odds Delta**: `{'+' if surv_diff >= 0 else ''}{surv_diff}%` ({p1_name}: {p1_c['survival_pct']}% vs {p2_name}: {p2_c['survival_pct']}%)
                - 🛡️ **Positional Regret Cliff Delta**: `{'+' if cliff_diff >= 0 else ''}{cliff_diff} Pts` (Drop-off if position is passed on)
                - 📊 **Actual Q1 Performance Delta**: `{'+' if q1_diff >= 0 else ''}{q1_diff} Pts` ({p1_name}: {p1_q1:.1f} Pts vs {p2_name}: {p2_q1:.1f} Pts)
                """)


def _render_position_column(col_obj, title: str, players: List[Dict], vorp_df, projections_df, draft_state, on_clock_gov):
    """Renders a single positional column with top-5 players."""
    tq = draft_state.config.get("target_quarter", "Q2")
    weeks_in_q = draft_state.config.get("weeks", [5, 6, 7, 8])
    my_roster = draft_state.rosters.get(draft_state.my_team, [])
    with col_obj:
        st.subheader(title, anchor=False)
        if not players:
            st.caption("No players remaining.")
            return
        for p in players:
            p_name = p["name"]
            is_flagged = p.get("at_risk", False)
            risk_badge = " ⚠️" if is_flagged else ""
            
            # Check if player in vorp_df to get gain/vorp
            v_match = vorp_df[vorp_df["name"] == p_name]
            gain_val = v_match.iloc[0]["vorp"] if not v_match.empty and "vorp" in v_match.columns else p.get("marginal_gain", 0.0)
            
            if gain_val <= -900.0:
                vorp_str = "CAP REACHED"
            elif gain_val >= 0:
                vorp_str = f"+{gain_val:.1f}"
            else:
                vorp_str = f"{gain_val:.1f}"

            st.markdown(f"**{p_name}** ({p['team']}){risk_badge}")
            # Show bye week badge for Q2 — highlight byes inside the scoring window
            bye_wk = 0
            p_match = projections_df[projections_df["name"] == p_name]
            if not p_match.empty and "bye_week" in p_match.columns:
                bye_wk = int(p_match.iloc[0]["bye_week"])
            same_pos_clash = [
                r for r in my_roster
                if r.get("position") == p.get("position") and draft_state.bye_weeks_map.get(r.get("team", ""), 0) == bye_wk and bye_wk in weeks_in_q
            ] if hasattr(draft_state, "bye_weeks_map") else []

            if same_pos_clash:
                clash_with = same_pos_clash[0].get("player_name") or same_pos_clash[0].get("name", "starter")
                bye_str = f" ⚠️ **BYE CLASH W{bye_wk}** (w/ {clash_with})"
            elif bye_wk > 0 and bye_wk in weeks_in_q:
                bye_str = f" 🛠️ BYE W{bye_wk}"
            elif bye_wk > 0:
                bye_str = f" ✅ BYE W{bye_wk} (outside Q)"
            else:
                bye_str = ""

            q1_val = p.get("q1_pts", 0.0)
            if (not q1_val or q1_val == 0.0) and not p_match.empty and "q1_pts" in p_match.columns:
                q1_val = p_match.iloc[0]["q1_pts"]
            q1_badge = f"Actual Q1: **{float(q1_val):.1f}** | " if q1_val and float(q1_val) > 0 else "Actual Q1: **—** | "

            st.caption(f"{q1_badge}Proj {tq}: **{p['ufl_pts']:.1f}** ({p['ppg']:.1f}/g) | VORP: {vorp_str}{bye_str}")

            if st.button(f"Draft {p['position']}", key=f"draft_btn_{title}_{p_name}", width="stretch"):
                p_info = projections_df[projections_df["name"] == p_name].iloc[0]
                draft_state.record_pick(p_info["name"], p_info["position"], p_info["team"], p_info["ufl_pts"], governor=on_clock_gov)
                st.toast(f"Drafted {p_name} to {on_clock_gov}!")
                st.rerun()
            st.markdown("<hr style='margin: 8px 0;'>", unsafe_allow_html=True)
