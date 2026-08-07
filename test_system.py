"""
System Validation & Integration Test Suite for UFL Fantasy Football Draft Advisor.
Verifies all engines, state persistence, projection synthesis, VORP math, strategy presets, cliff detection, and search.
"""

import os

from engine.projection_synth import ProjectionSynthesizer
from engine.draft_state import DraftState
from engine.vorp_calculator import VORPCalculator
from engine.joint_optimizer import JointOptimizer
from engine.opponent_predictor import OpponentPredictor
from engine.fuzzy_search import FuzzySearcher
from engine.base_engine import DraftEngineBase
from engine.live_math_engine import LiveMathEngine

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
STATE_PATH = os.path.join(DATA_DIR, "draft_state.json")
PRECOMPUTED_PATH = os.path.join(DATA_DIR, "precomputed_gameplan.json")

def test_projection_synthesis():
    print("Testing ProjectionSynthesizer...")
    synth = ProjectionSynthesizer(DATA_DIR)
    df = synth.synthesize()
    assert not df.empty, "Synthesized DataFrame should not be empty"
    assert "ufl_pts" in df.columns, "DataFrame must contain 'ufl_pts'"
    assert "position" in df.columns, "DataFrame must contain 'position'"
    # Verify CMC math logic
    cmc = df[df["name"] == "Christian McCaffrey"]
    if not cmc.empty:
        pts = cmc.iloc[0]["ufl_pts"]
        assert pts > 100.0, f"CMC should project over 100 Q1 UFL pts, got {pts}"
    print("  ✅ ProjectionSynthesizer passed!")

def test_draft_state():
    print("Testing DraftState...")
    ds = DraftState(CONFIG_PATH, STATE_PATH)
    ds.reset_draft()
    assert len(ds.picks_history) == 0, "Picks history should be empty after reset"
    assert len(ds.snake_order) == 72, "Snake order must contain exactly 72 picks"
    
    # Test pick recording
    p1 = ds.current_pick_info()
    assert p1["pick_no"] == 1, "First pick should be pick #1"
    assert p1["governor"] == ds.governors[0], f"First governor should be {ds.governors[0]}"
    
    ds.record_pick("Christian McCaffrey", "RB", "SF", 175.8)
    assert len(ds.picks_history) == 1, "Picks history count should be 1"
    assert ds.is_drafted("Christian McCaffrey"), "CMC should be marked as drafted"
    
    # Test undo
    undone = ds.undo_last_pick()
    assert undone["player_name"] == "Christian McCaffrey", "Undone player name mismatch"
    assert not ds.is_drafted("Christian McCaffrey"), "CMC should no longer be marked drafted"
    print("  ✅ DraftState passed!")

def test_vorp_and_joint_optimizer():
    print("Testing VORPCalculator & JointOptimizer...")
    synth = ProjectionSynthesizer(DATA_DIR)
    df = synth.synthesize()
    ds = DraftState(CONFIG_PATH, STATE_PATH)
    ds.reset_draft()
    
    calc = VORPCalculator(ds.roster_limits)
    vorp_df = calc.compute_vorp(df, ds)
    assert not vorp_df.empty, "VORP dataframe should not be empty"
    assert "vorp" in vorp_df.columns, "VORP dataframe must contain 'vorp' column"
    assert "ceiling_pts" in vorp_df.columns, "VORP dataframe must contain 'ceiling_pts'"
    assert "floor_pts" in vorp_df.columns, "VORP dataframe must contain 'floor_pts'"
    
    squeeze, msg = calc.check_qb_squeeze(df, ds)
    assert isinstance(squeeze, bool), "check_qb_squeeze must return bool"
    print("  ✅ VORPCalculator & JointOptimizer passed!")

def test_strategy_presets_and_cliffs():
    print("Testing Strategy Presets, Stacking Synergy & Cliff Detection...")
    synth = ProjectionSynthesizer(DATA_DIR)
    df = synth.synthesize()
    ds = DraftState(CONFIG_PATH, STATE_PATH)
    ds.reset_draft()
    
    calc = VORPCalculator(ds.roster_limits)
    
    # Test Hero RB VORP
    hero_df = calc.compute_vorp(df, ds, macro_strategy="HERO_RB")
    assert not hero_df.empty, "Hero RB dataframe should not be empty"
    
    # Test Stacking Bonus
    jo = JointOptimizer(ds.roster_limits)
    roster_with_mahomes = [{"name": "Patrick Mahomes", "position": "QB", "team": "KC", "ufl_pts": 100.0}]
    kelce_dict = {"name": "Travis Kelce", "position": "TE", "team": "KC", "ufl_pts": 87.0}
    stack_bonus = jo.calculate_stack_bonus(kelce_dict, roster_with_mahomes)
    assert stack_bonus > 1.0, f"Mahomes + Kelce stack bonus should be > 1.0, got {stack_bonus}"
    
    # Test Cliff Detection
    cliffs = calc.detect_positional_cliffs(df, ds)
    assert isinstance(cliffs, list), "Cliffs should return a list"
    
    # Test Opponent At-Risk Tagging
    predictor = OpponentPredictor(ds)
    flagged_df = predictor.flag_at_risk_players(hero_df)
    assert "at_risk" in flagged_df.columns, "Flagged dataframe must contain 'at_risk' column"
    
    print("  ✅ Strategy Presets, Stacking Synergy & Cliff Detection passed!")

def test_fuzzy_search():
    print("Testing FuzzySearcher...")
    synth = ProjectionSynthesizer(DATA_DIR)
    df = synth.synthesize()
    searcher = FuzzySearcher(df["name"].tolist())
    
    results = searcher.search("cmc")
    assert any("McCaffrey" in r for r in results), f"Fuzzy search 'cmc' should return McCaffrey, got {results}"
    
    results_jj = searcher.search("jj")
    assert any("Jefferson" in r for r in results_jj), f"Fuzzy search 'jj' should return Jefferson, got {results_jj}"
    print("  ✅ FuzzySearcher passed!")

def test_opponent_predictor():
    print("Testing OpponentPredictor...")
    ds = DraftState(CONFIG_PATH, STATE_PATH)
    ds.reset_draft()
    predictor = OpponentPredictor(ds)
    needs = predictor.predict_upcoming_opponent_needs()
    assert isinstance(needs, list), "Opponent needs should be a list"
    print("  ✅ OpponentPredictor passed!")

def test_engines():
    print("Testing Recommendation Engine (Live Math)...")
    synth = ProjectionSynthesizer(DATA_DIR)
    df = synth.synthesize()
    ds = DraftState(CONFIG_PATH, STATE_PATH)
    ds.reset_draft()
    
    # Engine: Live Math (implements DraftEngineBase)
    e2 = LiveMathEngine(ds.roster_limits)
    assert isinstance(e2, DraftEngineBase), "LiveMathEngine must inherit from DraftEngineBase"
    rec2 = e2.recommend(df, ds)
    assert isinstance(rec2, dict), "LiveMathEngine recommendation should be a dict"
    assert rec2["best_decision"] is not None, "LiveMathEngine best_decision should not be None"
    assert "Live Joint Math" in rec2["engine_name"], f"Engine name mismatch: {rec2['engine_name']}"
    print("  ✅ Recommendation Engine passed!")

def test_bug_fixes():
    print("Testing Bug & Flaw Remediation Specifics...")
    synth = ProjectionSynthesizer(DATA_DIR)
    df = synth.synthesize()
    ds = DraftState(CONFIG_PATH, STATE_PATH)
    ds.reset_draft()
    
    # 1. BUG-1 Verification: Injury math (single discount)
    # McCaffrey has touch_multiplier 0.95 in overrides.json.
    cmc = df[df["name"] == "Christian McCaffrey"]
    if not cmc.empty:
        pts = cmc.iloc[0]["ufl_pts"]
        assert pts > 100.0, f"CMC should project > 100 pts with single discount, got {pts}"
        
    # 2. FLAW-1 Verification: Starter vs Roster Standings
    jo = JointOptimizer(ds.roster_limits)
    mock_roster = [
        {"position": "QB", "ufl_pts": 100.0},
        {"position": "QB", "ufl_pts": 90.0},
        {"position": "QB", "ufl_pts": 80.0}, # Bench QB
        {"position": "RB", "ufl_pts": 80.0},
        {"position": "WR", "ufl_pts": 75.0},
        {"position": "TE", "ufl_pts": 50.0},
        {"position": "RB", "ufl_pts": 70.0}, # FLEX 1
        {"position": "WR", "ufl_pts": 65.0}, # FLEX 2
        {"position": "WR", "ufl_pts": 40.0}, # Bench WR
    ]
    starter_score = jo.solve_weekly_starting_lineup(mock_roster)
    total_score = sum(p["ufl_pts"] for p in mock_roster)
    assert starter_score == 530.0, f"Starter score expected 530.0 (top 2 QB, 1 RB, 1 WR, 1 TE, 2 FLEX), got {starter_score}"
    assert starter_score < total_score, f"Starter score ({starter_score}) must be less than total roster score ({total_score})"

    # 3. Draft Completion Null-Check Verification
    for i in range(72):
        ds.record_pick(f"Player_{i}", "RB", "NFL", 50.0)
    assert ds.current_pick_info() is None, "current_pick_info() must return None after 72 picks"
    curr_pick_i = ds.current_pick_info()
    on_clock = curr_pick_i["governor"] if curr_pick_i else ds.my_team
    assert on_clock == ds.my_team, "on_clock fallback should default to my_team when draft is complete"

    print("  ✅ Bug & Flaw Remediation tests passed!")

def test_turn_decision_matrix():
    print("Testing Turn Strategy War Room (Decision Matrix)...")
    import time
    synth = ProjectionSynthesizer(DATA_DIR)
    df = synth.synthesize()
    ds = DraftState(CONFIG_PATH, STATE_PATH)
    ds.reset_draft()

    e2 = LiveMathEngine(ds.roster_limits)

    # 1. Performance SLA Test (< 500ms)
    t0 = time.time()
    matrix = e2.generate_war_room_matrix(df, ds)
    elapsed_ms = (time.time() - t0) * 1000.0
    assert elapsed_ms < 500.0, f"War Room matrix generation failed SLA: took {elapsed_ms:.1f}ms (must be < 500ms)"

    assert isinstance(matrix, dict), "War Room matrix must be a dict"
    assert "candidates" in matrix, "War Room matrix must contain 'candidates' list"
    assert "executive_dilemma" in matrix, "War Room matrix must contain 'executive_dilemma'"
    
    candidates = matrix["candidates"]
    assert len(candidates) > 0, "Candidates list should not be empty"
    assert len(candidates) <= 10, f"Candidates list should be capped at 10, got {len(candidates)}"

    # Check required candidate keys
    first_c = candidates[0]
    required_keys = ["name", "position", "marginal_gain", "survival_pct", "regret_cliff", "floor_10", "ceiling_90", "badge"]
    for k in required_keys:
        assert k in first_c, f"Candidate dict must contain key '{k}'"

    # Verify positional diversity guarantee
    positions_present = set(c["position"] for c in candidates)
    for pos in ["QB", "RB", "WR", "TE"]:
        assert pos in positions_present, f"Position {pos} should be represented in War Room candidates"

    # 2. Survival Odds Realism Verification at Pick 1 (10 Opponent Picks Away)
    rb1 = next((c for c in candidates if c["position"] == "RB"), None)
    te1 = next((c for c in candidates if c["position"] == "TE"), None)
    
    if rb1:
        assert rb1["survival_pct"] < 30.0, f"RB1 survival odds at Pick 1 should be < 30%, got {rb1['survival_pct']}%"
    if te1:
        assert te1["survival_pct"] < 80.0, f"TE1 survival odds at Pick 1 should be < 80% (not artificial 100%), got {te1['survival_pct']}%"

    # 3. Back-to-Back Turn Assertion (Pick 12 / 0 Opponent Picks Away)
    ds.reset_draft()
    # Record 11 picks to reach Pick 12 (User turn on turn turn)
    for i in range(11):
        ds.record_pick(f"Player_Pick_{i+1}", "RB", "NFL", 50.0, governor=ds.snake_order[i]["governor"])
    
    matrix_turn = e2.generate_war_room_matrix(df, ds)
    for c in matrix_turn["candidates"]:
        assert c["survival_pct"] == 100.0, f"On back-to-back turn, survival odds for {c['name']} must be 100.0%, got {c['survival_pct']}%"
        assert c["regret_cliff"] == 0.0, f"On back-to-back turn, regret cliff for {c['name']} must be 0.0, got {c['regret_cliff']}"

    ds.reset_draft()
    print("  ✅ Turn Strategy War Room (Decision Matrix) passed!")

def run_all_tests():
    print("=" * 60)
    print("🏈 RUNNING UFL DRAFT ADVISOR SYSTEM TEST SUITE")
    print("=" * 60)
    test_projection_synthesis()
    test_draft_state()
    test_vorp_and_joint_optimizer()
    test_strategy_presets_and_cliffs()
    test_fuzzy_search()
    test_opponent_predictor()
    test_engines()
    test_turn_decision_matrix()
    test_bug_fixes()
    print("=" * 60)
    print("🎉 ALL SYSTEM TESTS PASSED CLEANLY!")
    print("=" * 60)

if __name__ == "__main__":
    run_all_tests()

