"""
UFL Fantasy Football Draft Advisor - Streamlit Web Dashboard.
Simplified, high-speed 'Draft Command Center' UI optimized for 90-second draft clock decisions.
"""

import os
import pandas as pd
import streamlit as st

from engine.projection_synth import ProjectionSynthesizer
from engine.projection_fetchers import FetcherManager, normalize_player_name
from engine.draft_state import DraftState
from engine.vorp_calculator import VORPCalculator
from engine.opponent_predictor import OpponentPredictor
from engine.fuzzy_search import FuzzySearcher
from engine.sleeper_sync import SleeperSync
from engine.live_math_engine import LiveMathEngine

from ui.sidebar import render_sidebar
from ui.command_center import render_command_center
from ui.draft_results import render_draft_results
from ui.mock_simulator import render_mock_simulator

# Page Configuration
st.set_page_config(
    page_title="Draft Advisor 2026",
    page_icon=":material/sports_football:",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Inject Custom CSS for Popover Scrolling & Viewport Fitting
st.markdown("""
<style>
/* Sidebar scrolling and smooth scrollbars */
section[data-testid="stSidebar"] {
    overflow-y: auto !important;
}

div[data-testid="stSidebarContent"] {
    overflow-y: auto !important;
    scrollbar-width: thin;
}

/* Fix popover body scrolling for popovers in sidebar & main area */
div[data-testid="stPopoverBody"],
div[data-baseweb="popover"] > div,
div[data-baseweb="popover"] {
    max-height: min(48vh, 420px) !important;
    overflow-y: auto !important;
    overscroll-behavior: contain;
    padding-bottom: 1.5rem !important;
    scrollbar-width: thin;
}

/* Ensure popover internal container doesn't cut off status messages */
div[data-testid="stPopoverBody"] > div {
    padding-bottom: 1rem !important;
}

/* Smooth scrollbar styling for webkit browsers */
div[data-testid="stPopoverBody"]::-webkit-scrollbar,
div[data-testid="stSidebarContent"]::-webkit-scrollbar {
    width: 6px;
}

div[data-testid="stPopoverBody"]::-webkit-scrollbar-track,
div[data-testid="stSidebarContent"]::-webkit-scrollbar-track {
    background: transparent;
}

div[data-testid="stPopoverBody"]::-webkit-scrollbar-thumb,
div[data-testid="stSidebarContent"]::-webkit-scrollbar-thumb {
    background-color: rgba(150, 150, 150, 0.4);
    border-radius: 4px;
}

div[data-testid="stPopoverBody"]::-webkit-scrollbar-thumb:hover,
div[data-testid="stSidebarContent"]::-webkit-scrollbar-thumb:hover {
    background-color: rgba(150, 150, 150, 0.7);
}
</style>
""", unsafe_allow_html=True)

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

if "skipped_this_pick" not in st.session_state:
    st.session_state.skipped_this_pick = set()

draft_state = st.session_state.draft_state
synth = st.session_state.synth
sleeper_sync = st.session_state.sleeper_sync

# Auto-clear skipped_this_pick when pick number changes
curr_pick_i_init = draft_state.current_pick_info()
curr_pick_no_init = curr_pick_i_init["pick_no"] if curr_pick_i_init else 73
if st.session_state.get("last_seen_pick_no") != curr_pick_no_init:
    st.session_state.skipped_this_pick = set()
    st.session_state.last_seen_pick_no = curr_pick_no_init

@st.cache_data
def load_projections(_synth, _data_dir: str):
    manager = FetcherManager(_data_dir)
    health_matrix = manager.run_pipeline()
    df = _synth.synthesize()
    return df, health_matrix

projections_df, health_matrix = load_projections(synth, DATA_DIR)

if projections_df.empty:
    st.error("⚠️ **No projection data available.** Check that CSV source files exist in `data/sources/` and at least one source is enabled in `data/sources.json`.")
    st.stop()

# Pre-compute normalized player names for efficient Sleeper sync matching
projections_df["_norm_name"] = projections_df["name"].apply(normalize_player_name).str.lower()

# Module-scoped fuzzy searcher (used by both manual pick logger and Sleeper sync)
fuzzy_searcher = FuzzySearcher(projections_df["name"].tolist())

# -------------------------------------------------------------
# SIDEBAR CONTROLS & POPOVERS
# -------------------------------------------------------------
selected_strategy_key, selected_vorp_mode = render_sidebar(
    draft_state, synth, sleeper_sync, health_matrix, projections_df, fuzzy_searcher
)

# Compute VORP & Threat Matrix
if st.session_state.skipped_this_pick:
    rec_projections_df = projections_df[~projections_df["name"].isin(st.session_state.skipped_this_pick)].copy()
else:
    rec_projections_df = projections_df

vorp_calc = VORPCalculator(draft_state.roster_limits)
vorp_df = vorp_calc.compute_vorp(rec_projections_df, draft_state, macro_strategy=selected_strategy_key, mode=selected_vorp_mode)
opponent_predictor = OpponentPredictor(draft_state)
vorp_df = opponent_predictor.flag_at_risk_players(vorp_df)

active_engine = LiveMathEngine(draft_state.roster_limits)
rec_result = active_engine.recommend_from_vorp(vorp_df, draft_state)

# -------------------------------------------------------------
# MAIN CONTENT HEADER & TABS
# -------------------------------------------------------------
tq = draft_state.config.get("target_quarter", "Q2")
weeks = draft_state.config.get("weeks", [5, 6, 7, 8])
w_str = f"Weeks {weeks[0]}–{weeks[-1]}" if weeks else "Weeks 5–8"

# Prominent Quarter & Target Banner
col_hdr_title, col_hdr_info = st.columns([3, 2], vertical_alignment="center")
with col_hdr_title:
    st.markdown(
        f"### 🏈 Draft Command Center — :green-background[**{tq} Target ({w_str})**]"
    )
with col_hdr_info:
    st.info(
        f"🎯 **Scoring Window: {tq} ({w_str})** • 14 teams have byes • Lineups solved weekly",
        icon=":material/calendar_month:"
    )

tab_cmd, tab_grid_standings, tab_db_mock = st.tabs([
    "⚡ Draft command center",
    f"📊 Draft results & {tq} standings",
    "🛠️ Database & mock simulator"
])

with tab_cmd:
    render_command_center(
        draft_state, projections_df, rec_projections_df, vorp_df, vorp_calc,
        rec_result, active_engine, selected_strategy_key, selected_vorp_mode
    )

with tab_grid_standings:
    render_draft_results(draft_state, projections_df)

with tab_db_mock:
    render_mock_simulator(draft_state, projections_df, vorp_df, selected_strategy_key, CONFIG_PATH)

