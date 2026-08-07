"""
UFL Fantasy Football Draft Advisor - Streamlit Web Dashboard.
Simplified, high-speed 'Draft Command Center' UI optimized for 90-second draft clock decisions.
"""

import os
import tempfile
import pandas as pd
import streamlit as st
from typing import Dict, List

from engine.projection_synth import ProjectionSynthesizer
from engine.draft_state import DraftState
from engine.vorp_calculator import VORPCalculator
from engine.opponent_predictor import OpponentPredictor
from engine.fuzzy_search import FuzzySearcher
from engine.sleeper_sync import SleeperSync
from engine.live_math_engine import LiveMathEngine
from engine.strategy_presets import STRATEGY_PRESETS

# Page Configuration
st.set_page_config(
    page_title="UFL Draft Advisor 2026",
    page_icon=":material/sports_football:",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
STATE_PATH = os.path.join(DATA_DIR, "draft_state.json")

# Initialize Session State Engines
if "draft_state" not in st.session_state:
    st.session_state.draft_state = DraftState(CONFIG_PATH, STATE_PATH)

if "synth" not in st.session_state:
    st.session_state.synth = ProjectionSynthesizer(DATA_DIR)

if "sleeper_sync" not in st.session_state:
    st.session_state.sleeper_sync = SleeperSync(DATA_DIR)

draft_state = st.session_state.draft_state
synth = st.session_state.synth
sleeper_sync = st.session_state.sleeper_sync

@st.cache_data
def load_projections(_synth, _data_dir: str):
    return _synth.synthesize()

projections_df = load_projections(synth, DATA_DIR)

# -------------------------------------------------------------
# SIDEBAR CONTROLS & POPOVERS
# -------------------------------------------------------------
with st.sidebar:
    st.title("Draft Command Center")
    st.caption(f"Target: {draft_state.config.get('target_quarter', 'Q1')} (Weeks 1–4) • User: `{draft_state.my_team}`")

    # POPOVER 1: STRATEGY SETTINGS
    with st.popover("⚙️ Strategy settings", icon=":material/tune:", width="stretch"):
        st.markdown("#### Strategy controls")
        preset_keys = list(STRATEGY_PRESETS.keys())
        selected_strategy_key = st.selectbox(
            "Strategy preset",
            preset_keys,
            format_func=lambda k: f"{STRATEGY_PRESETS[k]['name']} — {STRATEGY_PRESETS[k]['description']}"
        )

        selected_vorp_mode = st.radio(
            "Risk / Volatility mode",
            ["BALANCED", "CEILING", "FLOOR"],
            help="BALANCED uses base projections; CEILING rewards spike weeks; FLOOR targets baseline security."
        )

        st.markdown("---")
        st.markdown("#### Projection Source Weighting")
        for idx, source in enumerate(synth.config.get("sources", [])):
            c_en, c_wt = st.columns([1, 2])
            enabled = c_en.checkbox("Enable source", value=source.get("enabled", True), label_visibility="collapsed", key=f"en_{idx}")
            weight = c_wt.number_input(source["name"], min_value=0.0, max_value=5.0, value=float(source.get("weight", 1.0)), step=0.1, key=f"wt_{idx}")
            synth.config["sources"][idx]["enabled"] = enabled
            synth.config["sources"][idx]["weight"] = weight
        if st.button("Save & re-calculate"):
            synth.save_config()
            st.cache_data.clear()
            st.toast("Projections re-calculated!")
            st.rerun()

    # POPOVER 2: RECORD PICK / SLEEPER SYNC
    with st.popover("✏️ Record pick / Sleeper sync", icon=":material/sync:", width="stretch"):
        st.markdown("#### Manual logger & Sleeper sync")
        curr_pick = draft_state.current_pick_info()
        default_gov = curr_pick["governor"] if curr_pick else draft_state.governors[0]
        sel_gov = st.selectbox("Governor", draft_state.governors, index=draft_state.governors.index(default_gov))

        fuzzy_searcher = FuzzySearcher(projections_df["name"].tolist() if not projections_df.empty else [])
        search_query = st.text_input("Player search / shorthand ('cmc', 'jj')", "")
        search_results = fuzzy_searcher.search(search_query, limit=15) if search_query else []
        all_undrafted = projections_df[~projections_df["name"].apply(draft_state.is_drafted)]["name"].tolist() if not projections_df.empty else []
        sel_player = st.selectbox("Select player", search_results if search_results else all_undrafted)

        if st.button("➕ Log draft pick", width="stretch"):
            if sel_player and not draft_state.is_drafted(sel_player):
                p_row = projections_df[projections_df["name"] == sel_player].iloc[0]
                draft_state.record_pick(p_row["name"], p_row["position"], p_row["team"], p_row["ufl_pts"], governor=sel_gov)
                st.success(f"Logged {sel_player} to {sel_gov}!")
                st.rerun()

        st.markdown("---")
        st.markdown("##### Sleeper live draft auto-sync")
        sleeper_draft_id = st.text_input("Sleeper draft ID", value="")
        auto_sync = st.checkbox("Enable live polling (1.5s)", value=False)
        if auto_sync and sleeper_draft_id:
            picks = sleeper_sync.fetch_draft_picks(sleeper_draft_id)
            if picks and len(picks) > len(draft_state.picks_history):
                new_picks = picks[len(draft_state.picks_history):]
                for p in new_picks:
                    pname = p["player_name"]
                    matched = projections_df[projections_df["name"].str.lower() == pname.lower()]
                    if not matched.empty:
                        pos = matched.iloc[0]["position"]
                        tm = matched.iloc[0]["team"]
                        pts = matched.iloc[0]["ufl_pts"]
                    else:
                        pos, tm, pts = "FLEX", "NFL", 0.0
                    draft_state.record_pick(pname, pos, tm, pts)
                st.rerun()

    # QUICK CONTROL BUTTONS
    c_btn1, c_btn2 = st.columns(2)
    with c_btn1:
        if st.button("↩️ Undo", help="Undo last recorded pick", width="stretch"):
            undone = draft_state.undo_last_pick()
            if undone:
                st.toast(f"Undone pick: {undone['player_name']}")
                st.rerun()
    with c_btn2:
        if st.button("🚨 Reset", help="Reset draft to pick 1", width="stretch"):
            draft_state.reset_draft()
            st.cache_data.clear()
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.toast("Draft reset completely!")
            st.rerun()

# Compute VORP & Threat Matrix
vorp_calc = VORPCalculator(draft_state.roster_limits)
vorp_df = vorp_calc.compute_vorp(projections_df, draft_state, macro_strategy=selected_strategy_key, mode=selected_vorp_mode)
opponent_predictor = OpponentPredictor(draft_state)
vorp_df = opponent_predictor.flag_at_risk_players(vorp_df)

active_engine = LiveMathEngine(draft_state.roster_limits)
rec_result = active_engine.recommend_from_vorp(vorp_df, draft_state)

# -------------------------------------------------------------
# MAIN CONTENT TABS
# -------------------------------------------------------------
tab_cmd, tab_grid_standings, tab_db_mock = st.tabs([
    "⚡ Draft command center",
    "📊 Draft matrix & standings",
    "🛠️ Database & mock simulator"
])

# -------------------------------------------------------------
# TAB 1: DRAFT COMMAND CENTER
# -------------------------------------------------------------
with tab_cmd:
    curr_pick_i = draft_state.current_pick_info()
    if not curr_pick_i:
        st.success("🎉 **DRAFT COMPLETE!** All 72 picks have been recorded.")
        on_clock_gov = draft_state.my_team
    else:
        on_clock_gov = curr_pick_i["governor"]
        is_my_turn = (on_clock_gov == draft_state.my_team)
        if is_my_turn:
            st.error(f"🚨 **ON THE CLOCK**: Pick #{curr_pick_i['pick_no']} (Round {curr_pick_i['round']}) — YOUR TURN (`{draft_state.my_team}`)")
        else:
            wait_picks = draft_state.picks_until_my_turn()
            st.info(f"⏳ **Draft Progress**: Pick #{curr_pick_i['pick_no']} (Round {curr_pick_i['round']}) • On clock: `{on_clock_gov}` • **{wait_picks} picks until your turn**")

    # QB SQUEEZE ALERT
    squeeze_active, squeeze_msg = vorp_calc.check_qb_squeeze(projections_df, draft_state)
    if squeeze_active:
        st.warning(f"⚠️ **QB SQUEEZE WARNING**: {squeeze_msg}")

    st.markdown("---")

    # TOP RECOMMENDATION CARD
    best_candidate = rec_result.get("best_decision")
    if best_candidate:
        c_rec1, c_rec2 = st.columns([3, 1])
        with c_rec1:
            st.markdown(f"### 🎯 Recommended Pick: **{best_candidate['name']}** ({best_candidate['position']} • {best_candidate['team']})")
            st.markdown(rec_result.get("advice_text", ""))
        with c_rec2:
            if st.button("⚡ SLAM PICK", type="primary", width="stretch", help=f"Record {best_candidate['name']} to {on_clock_gov}"):
                p_info = projections_df[projections_df["name"] == best_candidate['name']].iloc[0]
                draft_state.record_pick(p_info["name"], p_info["position"], p_info["team"], p_info["ufl_pts"], governor=on_clock_gov)
                st.toast(f"Slammed {best_candidate['name']} to {on_clock_gov}!")
                st.rerun()

    st.markdown("---")

    # -------------------------------------------------------------
    # TURN STRATEGY WAR ROOM (DECISION MATRIX)
    # -------------------------------------------------------------
    with st.expander("⚔️ **Turn Strategy War Room — Decision Matrix & Survival Odds**", expanded=(curr_pick_i is not None and on_clock_gov == draft_state.my_team)):
        c_war1, c_war2 = st.columns([4, 1])
        with c_war1:
            st.markdown("#### Real-Time Candidate Decision Matrix & Survival Simulations")
        with c_war2:
            if st.button("🔄 Recalculate Matrix", key="btn_recalc_war_room", width="stretch"):
                st.cache_data.clear()
                st.rerun()

        war_room_data = active_engine.generate_war_room_matrix(projections_df, draft_state, macro_strategy=selected_strategy_key)
        candidates_list = war_room_data.get("candidates", [])

        if not candidates_list:
            st.caption("No candidates available for War Room simulation.")
        else:
            st.info(f"💡 {war_room_data.get('executive_dilemma', '')}")
            if war_room_data.get("top_pair_recommendation"):
                st.caption(f"🤝 {war_room_data.get('top_pair_recommendation')}")

            st.markdown("##### 📊 Candidate Comparison Matrix")
            matrix_display = []
            for c in candidates_list:
                matrix_display.append({
                    "Action Badge": f"{c['badge']}",
                    "Player": f"{c['name']} ({c['position']} • {c['team']})",
                    "UFL Pts": f"{c['ufl_pts']:.1f}",
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

            with col_exp1:
                p1_name = st.selectbox("Option A", c_names, index=0, key="sel_opt_a")
            with col_exp2:
                p2_name = st.selectbox("Option B", c_names, index=min(1, len(c_names)-1), key="sel_opt_b")

            if p1_name and p2_name and p1_name != p2_name:
                p1_c = next(c for c in candidates_list if c["name"] == p1_name)
                p2_c = next(c for c in candidates_list if c["name"] == p2_name)

                gain_diff = round(p1_c["marginal_gain"] - p2_c["marginal_gain"], 1)
                surv_diff = round(p1_c["survival_pct"] - p2_c["survival_pct"], 1)
                cliff_diff = round(p1_c["regret_cliff"] - p2_c["regret_cliff"], 1)

                st.markdown(f"""
                **Head-to-Head Comparison ({p1_name} vs {p2_name})**:
                - 📈 **Net Portfolio Gain Delta**: `{'+' if gain_diff >= 0 else ''}{gain_diff} Pts`
                - 🎯 **Survival Odds Delta**: `{'+' if surv_diff >= 0 else ''}{surv_diff}%` ({p1_name}: {p1_c['survival_pct']}% vs {p2_name}: {p2_c['survival_pct']}%)
                - 🛡️ **Positional Regret Cliff Delta**: `{'+' if cliff_diff >= 0 else ''}{cliff_diff} Pts` (Drop-off if position is passed on)
                """)

    st.markdown("---")


    # POSITIONAL TOP 5 COLUMNS
    col_qb, col_rb, col_wr, col_te = st.columns(4)

    def render_position_column(col_obj, title: str, players: List[Dict]):
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
                
                st.markdown(f"**{p_name}** ({p['team']}){risk_badge}")
                st.caption(f"Q1 Pts: **{p['ufl_pts']:.1f}** ({p['ppg']:.1f}/g) | VORP: +{gain_val:.1f}")

                if st.button(f"Draft {p['position']}", key=f"draft_btn_{title}_{p_name}", width="stretch"):
                    p_info = projections_df[projections_df["name"] == p_name].iloc[0]
                    draft_state.record_pick(p_info["name"], p_info["position"], p_info["team"], p_info["ufl_pts"], governor=on_clock_gov)
                    st.toast(f"Drafted {p_name} to {on_clock_gov}!")
                    st.rerun()
                st.markdown("<hr style='margin: 8px 0;'>", unsafe_allow_html=True)

    render_position_column(col_qb, "🏈 Top QBs", rec_result.get("top_qbs", []))
    render_position_column(col_rb, "🏃 Top RBs", rec_result.get("top_rbs", []))
    render_position_column(col_wr, "⚡ Top WRs", rec_result.get("top_wrs", []))
    render_position_column(col_te, "🛡️ Top TEs", rec_result.get("top_tes", []))

# -------------------------------------------------------------
# TAB 2: DRAFT MATRIX & STANDINGS
# -------------------------------------------------------------
with tab_grid_standings:
    st.subheader("Visual 6 Governors x 12 Rounds Draft Board", anchor=False)
    matrix_data = {r: ["" for _ in draft_state.governors] for r in range(1, 13)}
    for pick in draft_state.picks_history:
        r = pick["round"]
        gov = pick["governor"]
        gov_idx = draft_state.governors.index(gov) if gov in draft_state.governors else 0
        matrix_data[r][gov_idx] = f"{pick['player_name']} ({pick['position']})"
        
    grid_df = pd.DataFrame(matrix_data, index=draft_state.governors).T
    st.dataframe(grid_df, width="stretch")

    st.divider()
    st.subheader("Live Projected Q1 Standings & Rosters", anchor=False)
    from engine.joint_optimizer import JointOptimizer
    standings_optimizer = JointOptimizer(draft_state.roster_limits)
    standings = []
    for gov in draft_state.governors:
        r_list = draft_state.rosters.get(gov, [])
        starter_pts = standings_optimizer.solve_weekly_starting_lineup(r_list)
        total_roster_pts = sum(p["ufl_pts"] for p in r_list)
        standings.append({
            "Governor": gov,
            "Players Drafted": len(r_list),
            "Starter Q1 Pts": round(starter_pts, 2),
            "Starter PPG": round(starter_pts / 4.0, 1),
            "Total Roster Pts": round(total_roster_pts, 2)
        })
    standings_df = pd.DataFrame(standings).sort_values(by="Starter Q1 Pts", ascending=False).reset_index(drop=True)
    st.dataframe(standings_df, width="stretch", hide_index=True)

# -------------------------------------------------------------
# TAB 3: DATABASE & MOCK SIMULATOR
# -------------------------------------------------------------
with tab_db_mock:
    col_db1, col_db2 = st.columns([1, 1])

    with col_db1:
        st.subheader("All Players Database", anchor=False)
        only_avail = st.checkbox("Show only available players", value=True)
        display_df = vorp_df.copy()
        if only_avail:
            display_df = display_df[~display_df["name"].apply(draft_state.is_drafted)]
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
                sim_ds = DraftState(CONFIG_PATH, sim_state_path)
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
                    top_p = v_df.iloc[0]
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
            finally:
                if os.path.exists(sim_state_path):
                    os.unlink(sim_state_path)
