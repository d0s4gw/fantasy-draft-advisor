"""
Sidebar Controls UI Module.
Strategy settings, record pick / Sleeper sync, undo/reset buttons.
"""

import streamlit as st
from engine.projection_fetchers import normalize_player_name
from engine.strategy_presets import STRATEGY_PRESETS


def render_sidebar(draft_state, synth, sleeper_sync, health_matrix, projections_df, fuzzy_searcher):
    """Renders the complete sidebar with popovers and control buttons."""
    with st.sidebar:
        st.title("Draft Command Center")
        tq = draft_state.config.get('target_quarter', 'Q2')
        weeks = draft_state.config.get('weeks', [5, 6, 7, 8])
        w_str = f"Weeks {weeks[0]}–{weeks[-1]}" if weeks else "Weeks 5–8"

        with st.container(border=True):
            st.markdown(f"🎯 **Target Quarter**: :green-background[**{tq} ({w_str})**]")
            st.caption(f"👤 Target Team: **`{draft_state.my_team}`**  \n🛠️ Bye weeks active in scoring window")


        # EXPANDER: LIVE DATA SOURCES & PUBLISHED DATES LOGGING
        with st.popover("📡 Data sources status", icon=":material/dataset:", width="stretch"):
            st.markdown("#### Live Ingestion & Published Dates")
            for src_key, info in health_matrix.items():
                s_name = info.get("name", src_key.title())
                s_status = info.get("status", "UNKNOWN")
                s_count = info.get("players", 0)
                s_date = info.get("published_date", "Today")
                if s_status in ["HEALTHY", "CACHED"]:
                    st.markdown(f"✅ **{s_name}**  \n`{s_count}` players collected • **Published/Updated**: `{s_date}`")
                else:
                    st.markdown(f"⚠️ **{s_name}**: `{s_status}` (`{s_count}` players)")
            st.caption(f"Total Combined Synthesis: **{len(projections_df)}** players")

        # POPOVER 1: STRATEGY SETTINGS
        with st.popover("⚙️ Strategy settings", icon=":material/tune:", width="stretch"):
            st.markdown("#### Strategy controls")
            preset_keys = list(STRATEGY_PRESETS.keys())
            selected_strategy_key = st.selectbox(
                "Strategy preset",
                preset_keys,
                key="selected_strategy_key",
                format_func=lambda k: f"{STRATEGY_PRESETS[k]['name']} — {STRATEGY_PRESETS[k]['description']}"
            )

            selected_vorp_mode = st.radio(
                "Risk / Volatility mode",
                ["BALANCED", "CEILING", "FLOOR"],
                key="selected_vorp_mode",
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

            # Spacer at bottom of popover 1
            st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)

        # POPOVER 2: RECORD PICK / SLEEPER SYNC
        with st.popover("✏️ Record pick / Sleeper sync", icon=":material/sync:", width="stretch"):
            st.markdown("#### Manual logger & Sleeper sync")
            curr_pick = draft_state.current_pick_info()
            default_gov = curr_pick["governor"] if curr_pick else draft_state.governors[0]
            sel_gov = st.selectbox("Governor", draft_state.governors, index=draft_state.governors.index(default_gov))

            search_query = st.text_input("Player search / shorthand ('cmc', 'jj')", "")
            search_results = fuzzy_searcher.search(search_query, limit=15) if search_query else []
            all_undrafted = projections_df[~projections_df["name"].str.lower().isin(draft_state.drafted_players)]["name"].tolist() if not projections_df.empty else []
            sel_player = st.selectbox("Select player", search_results if search_results else all_undrafted)

            if st.button("➕ Log draft pick", width="stretch"):
                if sel_player and not draft_state.is_drafted(sel_player):
                    p_row = projections_df[projections_df["name"] == sel_player].iloc[0]
                    draft_state.record_pick(p_row["name"], p_row["position"], p_row["team"], p_row["ufl_pts"], governor=sel_gov)
                    st.success(f"Logged {sel_player} to {sel_gov}!")
                    st.rerun()

            st.markdown("---")
            st.markdown("##### Sleeper live draft auto-sync")

            @st.fragment(run_every=1.5)
            def sync_sleeper_picks_fragment():
                sleeper_draft_id = st.text_input(
                    "Sleeper draft ID or URL",
                    value=st.session_state.get("sleeper_draft_id_val", ""),
                    key="sleeper_draft_id_input",
                    help="Paste 18-digit Sleeper Draft ID, League ID, or full draft URL"
                )
                st.session_state.sleeper_draft_id_val = sleeper_draft_id
                
                auto_sync = st.checkbox("Enable live polling (1.5s)", value=st.session_state.get("auto_sync_val", False), key="auto_sync_check")
                st.session_state.auto_sync_val = auto_sync

                # Only hit the Sleeper API when auto_sync is enabled AND a draft ID is provided
                if sleeper_draft_id and auto_sync:
                    info = sleeper_sync.get_draft_info(sleeper_draft_id)
                    if info:
                        d_status = info.get("status", "unknown").upper()
                        d_type = info.get("type", "snake").upper()
                        actual_id = info.get("draft_id", sleeper_draft_id)
                        
                        # Pass resolved info to avoid redundant get_draft_info HTTP call
                        picks = sleeper_sync.fetch_draft_picks(actual_id, resolved_info=info)
                        st.caption(f"🟢 **Sleeper Room Connected**: {len(picks)} picks recorded • Status: `{d_status}` ({d_type})")
                        
                        if len(picks) > len(draft_state.picks_history):
                            new_picks = picks[len(draft_state.picks_history):]
                            synced_count = 0
                            for p in new_picks:
                                raw_pname = p["player_name"]
                                norm_pname = normalize_player_name(raw_pname).lower()
                                
                                # Match against pre-computed normalized name column
                                matched = projections_df[projections_df["_norm_name"] == norm_pname]
                                if matched.empty:
                                    fuzzy_res = fuzzy_searcher.search(raw_pname, limit=1)
                                    if fuzzy_res:
                                        matched = projections_df[projections_df["name"] == fuzzy_res[0]]

                                if not matched.empty:
                                    pname = matched.iloc[0]["name"]
                                    pos = matched.iloc[0]["position"]
                                    tm = matched.iloc[0]["team"]
                                    pts = matched.iloc[0]["ufl_pts"]
                                else:
                                    pname = raw_pname
                                    pos = p.get("position", "FLEX")
                                    tm = p.get("team", "NFL")
                                    pts = 0.0

                                # Map Sleeper pick_no to correct governor via snake order
                                pick_no = p.get("pick_no")
                                if pick_no and pick_no <= len(draft_state.snake_order):
                                    governor = draft_state.snake_order[pick_no - 1]["governor"]
                                else:
                                    governor = None  # fallback to current_pick_info default

                                draft_state.record_pick(pname, pos, tm, pts, governor=governor)
                                synced_count += 1
                            
                            st.toast(f"Synced {synced_count} new pick(s) from Sleeper!")
                            st.rerun()
                        elif len(picks) < len(draft_state.picks_history):
                            st.caption("ℹ️ Local draft state has more picks than Sleeper (manual picks logged).")
                    else:
                        st.warning(f"⚠️ Could not resolve Sleeper Draft/League ID for '{sleeper_draft_id}'. Verify URL/ID.")
                elif sleeper_draft_id and not auto_sync:
                    st.caption("ℹ️ Toggle **Enable live polling** above to start auto-syncing picks from Sleeper.")
                else:
                    st.caption("ℹ️ Paste your 18-digit Sleeper Draft ID, League ID, or full draft URL above to auto-sync picks.")

            sync_sleeper_picks_fragment()

            # Extra bottom padding buffer so content below Sleeper text input is never cut off
            st.markdown("<div style='height: 40px;'></div>", unsafe_allow_html=True)

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
                # Only clear draft-related session state keys
                draft_keys = ["draft_state", "synth", "sleeper_sync", "skipped_this_pick", "last_seen_pick_no"]
                for key in draft_keys:
                    if key in st.session_state:
                        del st.session_state[key]
                st.toast("Draft reset completely!")
                st.rerun()

        return selected_strategy_key, selected_vorp_mode
