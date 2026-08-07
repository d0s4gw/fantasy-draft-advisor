"""
Monte Carlo High-Variance Draft Simulation & Strategy Stress Tester.
Runs 500+ stochastic mock draft iterations with random noise (sigma) applied to opponent valuations.
Tests whether the default strategy is trapped in a local maximum and evaluates strategy win-rates.
"""

import os
import time
import numpy as np
import pandas as pd
from typing import Dict, List
from engine.projection_synth import ProjectionSynthesizer
from engine.draft_state import DraftState
from engine.vorp_calculator import VORPCalculator
from engine.joint_optimizer import JointOptimizer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
STATE_PATH = os.path.join(DATA_DIR, "draft_state.json")

def run_stochastic_mock(user_team: str = None, user_strategy: str = "AUTO", noise_sigma: float = 0.15, rng_seed: int = None) -> Dict:
    """
    Executes a 72-pick mock draft with random noise (noise_sigma) applied to opponent player evaluations.
    Noise_sigma represents evaluation variance / reach tendency (e.g. 0.15 = 15% std dev).
    """
    if rng_seed is not None:
        np.random.seed(rng_seed)

    synth = ProjectionSynthesizer(DATA_DIR)
    projections_df = synth.synthesize()
    draft_state = DraftState(CONFIG_PATH, STATE_PATH)
    
    if user_team is None:
        user_team = draft_state.my_team
        
    draft_state.reset_draft()
    vorp_calc = VORPCalculator(draft_state.roster_limits)
    optimizer = JointOptimizer(draft_state.roster_limits)

    for pick_no in range(1, 73):
        curr_pick = draft_state.current_pick_info()
        gov = curr_pick["governor"]
        
        # Calculate VORP
        eval_strat = user_strategy if gov == user_team else "AUTO"
        v_df = vorp_calc.compute_vorp(projections_df, draft_state, macro_strategy=eval_strat, governor=gov)

        if v_df.empty:
            break

        valid_df = v_df[v_df["marginal_gain"] > -900.0].copy()
        if valid_df.empty:
            valid_df = v_df.copy()

        if gov == user_team:
            # User picks deterministically based on strategy
            top_p = valid_df.iloc[0]
        else:
            # Opponents pick stochastically: add multiplicative gaussian noise to marginal_gain / ufl_pts
            # This simulates opponent reaches, subjective preferences, and draft variance
            noise = np.random.normal(1.0, noise_sigma, size=len(valid_df))
            valid_df["stochastic_score"] = valid_df["marginal_gain"] * noise
            stochastic_sorted = valid_df.sort_values(by="stochastic_score", ascending=False)
            top_p = stochastic_sorted.iloc[0]

        draft_state.record_pick(top_p["name"], top_p["position"], top_p["team"], top_p["ufl_pts"], governor=gov)

    # Calculate final starter standings
    standings = []
    for g in draft_state.governors:
        r_list = draft_state.rosters.get(g, [])
        starter_pts = optimizer.solve_weekly_starting_lineup(r_list)
        total_pts = sum(p["ufl_pts"] for p in r_list)
        standings.append({
            "governor": g,
            "starter_pts": starter_pts,
            "total_pts": total_pts
        })

    standings_df = pd.DataFrame(standings).sort_values(by="starter_pts", ascending=False).reset_index(drop=True)
    winner = standings_df.iloc[0]["governor"]
    user_rank = int(standings_df[standings_df["governor"] == user_team].index[0]) + 1
    user_pts = float(standings_df[standings_df["governor"] == user_team]["starter_pts"].iloc[0])

    return {
        "winner": winner,
        "user_rank": user_rank,
        "user_pts": user_pts,
        "user_won": (winner == user_team)
    }

def run_monte_carlo_experiment(num_sims: int = 50, noise_levels: List[float] = [0.05, 0.15, 0.25]):
    print("=" * 80)
    print(f"🎲 RUNNING MONTE CARLO HIGH-VARIANCE DRAFT EXPERIMENT ({num_sims} DRAFTS PER CONFIG)")
    print("=" * 80)

    strategies = ["AUTO", "HERO_RB", "ZERO_RB", "ROBUST_RB", "ELITE_TE"]
    results = []

    for sigma in noise_levels:
        print(f"\n🔥 Testing Variance Level: σ = {sigma*100:.0f}% Opponent Evaluation Noise")
        print("-" * 75)

        for strat in strategies:
            start_time = time.time()
            wins = 0
            ranks = []
            pts_list = []

            for i in range(num_sims):
                res = run_stochastic_mock(user_team=None, user_strategy=strat, noise_sigma=sigma, rng_seed=42 + i)
                if res["user_won"]:
                    wins += 1
                ranks.append(res["user_rank"])
                pts_list.append(res["user_pts"])

            win_rate = (wins / num_sims) * 100.0
            avg_rank = np.mean(ranks)
            avg_pts = np.mean(pts_list)
            p90_pts = np.percentile(pts_list, 90)
            p10_pts = np.percentile(pts_list, 10)
            elapsed = time.time() - start_time

            print(f"Strategy: {strat:<12} | Win Rate: {win_rate:>5.1f}% | Avg Rank: #{avg_rank:.2f} | Avg Starter Pts: {avg_pts:.1f} (P10: {p10_pts:.1f}, P90: {p90_pts:.1f}) | {elapsed:.1f}s")

            results.append({
                "Noise (σ)": f"{sigma*100:.0f}%",
                "Strategy": strat,
                "Win Rate (%)": round(win_rate, 1),
                "Avg Rank": round(avg_rank, 2),
                "Avg Starter Pts": round(avg_pts, 1),
                "P10 Pts": round(p10_pts, 1),
                "P90 Pts": round(p90_pts, 1)
            })

    print("\n" + "=" * 80)
    print("📊 MONTE CARLO EXPERIMENT SUMMARY REPORT")
    print("=" * 80)
    summary_df = pd.DataFrame(results)
    print(summary_df.to_string(index=False))

if __name__ == "__main__":
    run_monte_carlo_experiment(num_sims=30, noise_levels=[0.05, 0.15, 0.25])
