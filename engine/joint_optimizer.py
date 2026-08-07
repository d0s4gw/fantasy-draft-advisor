"""
Feasible Joint Portfolio Draft Optimizer Engine.
Solves exact 4-week optimal weekly starting lineups:
  - 2 QBs
  - 1 RB
  - 1 WR
  - 1 TE
  - 2 FLEX (best remaining RB/WR/TE)
  - 5 Bench (0 pts)

Uses realistic future-pick replacement baselines for unfilled starter slots
to accurately evaluate the marginal cost of delaying a position.
"""

import pandas as pd
from typing import List, Dict, Optional, Any
from engine.strategy_presets import StrategyPresetManager


class JointOptimizer:
    def __init__(self, roster_limits: dict):
        self.roster_limits = roster_limits

    def solve_weekly_starting_lineup(self, roster: List[Dict]) -> float:
        """
        Solves the exact optimal weekly starting lineup score from a list of player dicts.
        Starters: 2 QB, 1 RB, 1 WR, 1 TE, 2 FLEX (RB/WR/TE).
        Vacant required starter slots score 0.0 pts!
        """
        if not roster:
            return 0.0

        qbs = sorted([p for p in roster if p["position"] == "QB"], key=lambda x: x["ufl_pts"], reverse=True)
        rbs = sorted([p for p in roster if p["position"] == "RB"], key=lambda x: x["ufl_pts"], reverse=True)
        wrs = sorted([p for p in roster if p["position"] == "WR"], key=lambda x: x["ufl_pts"], reverse=True)
        tes = sorted([p for p in roster if p["position"] == "TE"], key=lambda x: x["ufl_pts"], reverse=True)

        pts_qb1 = qbs[0]["ufl_pts"] if len(qbs) >= 1 else 0.0
        pts_qb2 = qbs[1]["ufl_pts"] if len(qbs) >= 2 else 0.0
        
        pts_rb1 = rbs[0]["ufl_pts"] if len(rbs) >= 1 else 0.0
        pts_wr1 = wrs[0]["ufl_pts"] if len(wrs) >= 1 else 0.0
        pts_te1 = tes[0]["ufl_pts"] if len(tes) >= 1 else 0.0

        flex_pool = rbs[1:] + wrs[1:] + tes[1:]
        flex_pool = sorted(flex_pool, key=lambda x: x["ufl_pts"], reverse=True)
        
        pts_flex1 = flex_pool[0]["ufl_pts"] if len(flex_pool) >= 1 else 0.0
        pts_flex2 = flex_pool[1]["ufl_pts"] if len(flex_pool) >= 2 else 0.0

        total_lineup = pts_qb1 + pts_qb2 + pts_rb1 + pts_wr1 + pts_te1 + pts_flex1 + pts_flex2
        return total_lineup

    def calculate_stack_bonus(self, player_dict: Dict, current_roster: List[Dict]) -> float:
        """
        Calculates stacking correlation bonus for QB + WR/TE from the same NFL team.
        Adds +3% to +7% gain multiplier as a tie-breaker for stack synergy.
        """
        p_pos = player_dict.get("position")
        p_team = player_dict.get("team")
        if not p_team or p_team == "NFL":
            return 1.0

        bonus = 1.0
        if p_pos in ["WR", "TE"]:
            has_matching_qb = any(p.get("position") == "QB" and p.get("team") == p_team for p in current_roster)
            if has_matching_qb:
                bonus += 0.05
        elif p_pos == "QB":
            matching_pass_catchers = len([p for p in current_roster if p.get("position") in ["WR", "TE"] and p.get("team") == p_team])
            if matching_pass_catchers > 0:
                bonus += min(0.08, 0.04 * matching_pass_catchers)

        return bonus

    def evaluate_candidate_picks(
        self,
        undrafted_df: pd.DataFrame,
        draft_state,
        num_candidates: int = 40,
        macro_strategy: str = "AUTO",
        governor: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Performs Feasible Joint Portfolio Optimization for candidate picks.
        Uses realistic future pick replacement baselines so delaying a position
        correctly reflects opponent drafting in intermediate rounds.
        """
        if undrafted_df.empty:
            return undrafted_df

        if draft_state:
            undrafted_df = undrafted_df[~undrafted_df["name"].apply(draft_state.is_drafted)].copy()

        if undrafted_df.empty:
            return undrafted_df

        target_gov = governor if governor else (draft_state.current_pick_info()["governor"] if draft_state and draft_state.current_pick_info() else draft_state.my_team)
        current_roster = draft_state.rosters.get(target_gov, [])
        base_portfolio_score = self.solve_weekly_starting_lineup(current_roster)
        
        picks_made = len(current_roster)
        picks_remaining_total = 12 - picks_made

        # Count current positions for target governor
        cur_qbs = len([p for p in current_roster if p["position"] == "QB"])
        cur_rbs = len([p for p in current_roster if p["position"] == "RB"])
        cur_wrs = len([p for p in current_roster if p["position"] == "WR"])
        cur_tes = len([p for p in current_roster if p["position"] == "TE"])

        req_qbs = max(0, 2 - cur_qbs)
        req_rbs = max(0, 1 - cur_rbs)
        req_wrs = max(0, 1 - cur_wrs)
        req_tes = max(0, 1 - cur_tes)
        total_starters_needed = req_qbs + req_rbs + req_wrs + req_tes

        # No-Waiver mandatory full roster requirements (3 QB, 2 TE, 3 RB, 3 WR)
        req_qbs_full = max(0, 3 - cur_qbs)
        req_tes_full = max(0, 2 - cur_tes)
        req_rbs_full = max(0, 3 - cur_rbs)
        req_wrs_full = max(0, 3 - cur_wrs)
        total_full_needed = req_qbs_full + req_tes_full + req_rbs_full + req_wrs_full

        # Calculate realistic positional replacement baselines at future draft picks
        pos_future_baselines = {}
        for pos, target_idx in [("QB", 10), ("RB", 10), ("WR", 12), ("TE", 6)]:
            pos_df = undrafted_df[undrafted_df["position"] == pos].sort_values(by="ufl_pts", ascending=False)
            if len(pos_df) >= target_idx:
                pos_future_baselines[pos] = pos_df.iloc[target_idx - 1]["ufl_pts"]
            elif not pos_df.empty:
                pos_future_baselines[pos] = pos_df.iloc[-1]["ufl_pts"] * 0.85
            else:
                pos_future_baselines[pos] = 0.0

        # Calculate base portfolio score with future replacement baselines filling remaining starter slots
        base_projected_full = list(current_roster)
        if cur_qbs < 2:
            qb_base = pos_future_baselines.get("QB", 75.0)
            for _ in range(2 - cur_qbs):
                base_projected_full.append({"position": "QB", "ufl_pts": qb_base})
        if cur_rbs < 1:
            rb_base = pos_future_baselines.get("RB", 105.0)
            base_projected_full.append({"position": "RB", "ufl_pts": rb_base})
        if cur_wrs < 1:
            wr_base = pos_future_baselines.get("WR", 90.0)
            base_projected_full.append({"position": "WR", "ufl_pts": wr_base})
        if cur_tes < 1:
            te_base = pos_future_baselines.get("TE", 60.0)
            base_projected_full.append({"position": "TE", "ufl_pts": te_base})

        base_portfolio_score = self.solve_weekly_starting_lineup(base_projected_full)

        candidates = undrafted_df.head(min(len(undrafted_df), 60)).copy()
        pos_candidates = []
        for p_pos in ["QB", "RB", "WR", "TE"]:
            pos_candidates.append(undrafted_df[undrafted_df["position"] == p_pos].head(10))
        candidates = pd.concat(pos_candidates + [candidates]).drop_duplicates(subset=["name"]).copy()

        marginal_gains = []
        projected_totals = []
        lineup_statuses = []

        for idx, row in candidates.iterrows():
            pos = row["position"]
            player_dict = {
                "name": row["name"],
                "position": pos,
                "team": row["team"],
                "ufl_pts": row["ufl_pts"]
            }
            
            # Check feasibility constraints & positional roster caps
            max_caps = {"QB": 3, "RB": 5, "WR": 5, "TE": 2}
            cur_pos_count = len([p for p in current_roster if p["position"] == pos])
            exceeds_cap = cur_pos_count >= max_caps.get(pos, 5)

            is_needed_starter = (
                (pos == "QB" and req_qbs > 0) or
                (pos == "RB" and req_rbs > 0) or
                (pos == "WR" and req_wrs > 0) or
                (pos == "TE" and req_tes > 0)
            )

            is_needed_full = (
                (pos == "QB" and req_qbs_full > 0) or
                (pos == "TE" and req_tes_full > 0) or
                (pos == "RB" and req_rbs_full > 0) or
                (pos == "WR" and req_wrs_full > 0)
            )

            if exceeds_cap:
                gain = -999.0
                sim_score = base_portfolio_score
                status = f"REJECTED (MAX {pos} ROSTER CAP REACHED)"
            elif picks_remaining_total <= total_full_needed and not is_needed_full:
                gain = -999.0
                sim_score = base_portfolio_score
                status = "REJECTED (MANDATORY NO-WAIVER ROSTER NEEDED)"
            elif picks_remaining_total <= total_starters_needed and not is_needed_starter:
                gain = -999.0
                sim_score = base_portfolio_score
                status = "REJECTED (MANDATORY STARTER NEEDED)"
            else:
                simulated_roster = current_roster + [player_dict]

                # Project filling remaining unfilled starter slots using realistic future replacement baselines
                sim_qbs = len([p for p in simulated_roster if p["position"] == "QB"])
                sim_rbs = len([p for p in simulated_roster if p["position"] == "RB"])
                sim_wrs = len([p for p in simulated_roster if p["position"] == "WR"])
                sim_tes = len([p for p in simulated_roster if p["position"] == "TE"])

                projected_full = list(simulated_roster)

                if sim_qbs < 2:
                    needed = 2 - sim_qbs
                    qb_base = pos_future_baselines.get("QB", 75.0)
                    for _ in range(needed):
                        projected_full.append({"position": "QB", "ufl_pts": qb_base})

                if sim_rbs < 1:
                    rb_base = pos_future_baselines.get("RB", 105.0)
                    projected_full.append({"position": "RB", "ufl_pts": rb_base})

                if sim_wrs < 1:
                    wr_base = pos_future_baselines.get("WR", 90.0)
                    projected_full.append({"position": "WR", "ufl_pts": wr_base})

                if sim_tes < 1:
                    te_base = pos_future_baselines.get("TE", 60.0)
                    projected_full.append({"position": "TE", "ufl_pts": te_base})

                # Solve optimal 4-week portfolio score
                sim_score = self.solve_weekly_starting_lineup(projected_full)
                raw_gain = round(sim_score - base_portfolio_score, 2)

                # If candidate fills a mandatory unfilled starter slot (e.g. TE1, QB2, WR1, RB1), give proportional priority boost
                if is_needed_starter:
                    replacement_base = pos_future_baselines.get(pos, 0.0)
                    starter_bonus = max(10.0, row["ufl_pts"] - replacement_base)
                    raw_gain += starter_bonus

                # For bench candidates (raw_gain == 0), calculate non-zero bench depth value
                if raw_gain == 0.0:
                    base_bench = row["ufl_pts"] / 100.0
                    if pos == "WR" and cur_wrs < 4:
                        bench_mult = 1.3
                    elif pos == "QB" and cur_qbs < 3:
                        bench_mult = 1.1
                    elif pos == "TE" and cur_tes < 2:
                        bench_mult = 1.15 # Strong TE2 insurance valuation for bench
                    elif pos == "RB":
                        if cur_rbs <= 3:
                            bench_mult = 0.8
                        else:
                            bench_mult = 0.3 # Encourage WR/TE/QB depth over 5th RB
                    else:
                        bench_mult = 0.5
                    raw_gain = round(base_bench * bench_mult, 2)

                # Apply Stacking Bonus & Macro Strategy Multiplier
                stack_bonus = self.calculate_stack_bonus(player_dict, current_roster)
                round_no = (len(current_roster)) + 1
                strat_mult = StrategyPresetManager.get_positional_multiplier(macro_strategy, pos, current_roster, round_no)
                
                gain = round(raw_gain * stack_bonus * strat_mult, 2)

                if pos == "QB" and sim_qbs <= 2:
                    status = "QB STARTER IMPACT"
                elif pos == "RB" and sim_rbs <= 1:
                    status = "RB STARTER IMPACT"
                elif pos == "WR" and sim_wrs <= 1:
                    status = "WR STARTER IMPACT"
                elif pos == "TE" and sim_tes <= 1:
                    status = "TE STARTER IMPACT"
                else:
                    status = "FLEX / BENCH IMPACT"

                if stack_bonus > 1.0:
                    status += " (⚡ STACK SYNERGY)"

            marginal_gains.append(gain)
            projected_totals.append(round(sim_score, 2))
            lineup_statuses.append(status)

        candidates["marginal_gain"] = marginal_gains
        candidates["vorp"] = marginal_gains
        candidates["projected_team_pts"] = projected_totals
        candidates["roster_need"] = lineup_statuses

        # Sort by Marginal Portfolio Gain
        candidates = candidates.sort_values(by="marginal_gain", ascending=False).reset_index(drop=True)
        return candidates

    def compute_turn_decision_matrix(
        self,
        draft_state,
        projections_df: pd.DataFrame,
        candidate_limit: int = 10,
        num_sims: int = 60,
        macro_strategy: str = "AUTO"
    ) -> Dict[str, Any]:
        """
        Computes the War Room Decision Matrix for candidate picks.
        Generates positional diversity candidates, survival probabilities,
        positional regret cliffs, back-to-back turn pairing recommendations,
        and floor/ceiling simulation score ranges.
        """
        if projections_df.empty or not draft_state:
            return {
                "picks_until_next": 0,
                "is_back_to_back": False,
                "executive_dilemma": "No draft active or projections empty.",
                "top_pair_recommendation": None,
                "candidates": []
            }

        import numpy as np
        from engine.opponent_predictor import OpponentPredictor

        eval_df = self.evaluate_candidate_picks(projections_df, draft_state, macro_strategy=macro_strategy)
        if eval_df.empty:
            return {
                "picks_until_next": 0,
                "is_back_to_back": False,
                "executive_dilemma": "No candidates remaining.",
                "top_pair_recommendation": None,
                "candidates": []
            }

        valid_df = eval_df[eval_df["marginal_gain"] > -900.0].copy()
        if valid_df.empty:
            valid_df = eval_df.copy()

        # Positional Diversity Candidate Selection
        selected_candidates = []
        for pos in ["QB", "RB", "WR", "TE"]:
            pos_sub = valid_df[valid_df["position"] == pos].head(2)
            if not pos_sub.empty:
                selected_candidates.append(pos_sub)

        top_gainers = valid_df.head(4)
        selected_candidates.append(top_gainers)

        candidates_df = pd.concat(selected_candidates).drop_duplicates(subset=["name"]).head(candidate_limit).copy()
        candidates_df = candidates_df.sort_values(by="marginal_gain", ascending=False).reset_index(drop=True)

        curr_pick_info = draft_state.current_pick_info()
        predictor = OpponentPredictor(draft_state)
        upcoming_opps = predictor.predict_upcoming_opponent_needs()
        num_opp_picks = len(upcoming_opps)
        picks_until_next = num_opp_picks
        is_back_to_back = (num_opp_picks == 0)

        undrafted_pool = projections_df[~projections_df["name"].apply(draft_state.is_drafted)].copy()
        target_gov = curr_pick_info["governor"] if curr_pick_info else draft_state.my_team
        current_roster = draft_state.rosters.get(target_gov, [])

        # Convert undrafted pool to lightweight list of dicts for ultra-fast simulation
        undrafted_records = undrafted_pool.to_dict("records")
        pos_records = {
            "QB": [p for p in undrafted_records if p["position"] == "QB"],
            "RB": [p for p in undrafted_records if p["position"] == "RB"],
            "WR": [p for p in undrafted_records if p["position"] == "WR"],
            "TE": [p for p in undrafted_records if p["position"] == "TE"],
        }

        # Calculate positional replacement baselines for normalized cross-position opponent choices
        pos_baselines = {
            "QB": projections_df[projections_df["position"] == "QB"].iloc[min(11, len(projections_df[projections_df["position"] == "QB"])-1)]["ufl_pts"] if not projections_df[projections_df["position"] == "QB"].empty else 50.0,
            "RB": projections_df[projections_df["position"] == "RB"].iloc[min(17, len(projections_df[projections_df["position"] == "RB"])-1)]["ufl_pts"] if not projections_df[projections_df["position"] == "RB"].empty else 40.0,
            "WR": projections_df[projections_df["position"] == "WR"].iloc[min(17, len(projections_df[projections_df["position"] == "WR"])-1)]["ufl_pts"] if not projections_df[projections_df["position"] == "WR"].empty else 35.0,
            "TE": projections_df[projections_df["position"] == "TE"].iloc[min(11, len(projections_df[projections_df["position"] == "TE"])-1)]["ufl_pts"] if not projections_df[projections_df["position"] == "TE"].empty else 20.0,
        }

        for p in undrafted_records:
            p["_pos_vorp"] = p["ufl_pts"] - pos_baselines.get(p["position"], 20.0)

        # Shared Monte Carlo Draft Board Simulations (run once for high performance)
        sim_drafted_sets = []
        if num_opp_picks > 0 and not is_back_to_back:
            for sim_i in range(num_sims):
                taken_names = set()
                for opp in upcoming_opps:
                    opp_needs = set(opp.get("predicted_needs", []))
                    
                    cand_pool = []
                    for p_pos in ["QB", "RB", "WR", "TE"]:
                        cand_pool.extend([p for p in pos_records[p_pos] if p["name"] not in taken_names][:5])
                    cand_pool.extend([p for p in undrafted_records if p["name"] not in taken_names][:5])
                    
                    if not cand_pool:
                        break
                        
                    seen_cands = set()
                    unique_pool = []
                    for p in cand_pool:
                        if p["name"] not in seen_cands:
                            seen_cands.add(p["name"])
                            unique_pool.append(p)
                            
                    best_cand = None
                    best_score = -999.0
                    for p in unique_pool:
                        need_mult = 1.35 if (opp_needs and p["position"] in opp_needs) else 1.0
                        noise = np.random.normal(1.0, 0.15)
                        score = (p["_pos_vorp"] + 30.0) * noise * need_mult
                        if score > best_score:
                            best_score = score
                            best_cand = p
                            
                    if best_cand:
                        taken_names.add(best_cand["name"])
                        
                sim_drafted_sets.append(taken_names)

        matrix_rows = []

        for idx, cand in candidates_df.iterrows():
            c_name = cand["name"]
            c_pos = cand["position"]
            c_pts = cand["ufl_pts"]
            c_gain = cand["marginal_gain"]
            c_proj_pts = cand.get("projected_team_pts", 650.0)

            # Survival Probability & Regret Cliff Modeling
            if num_opp_picks == 0 or is_back_to_back:
                survival_pct = 100.0
                regret_cliff = 0.0
            else:
                survived_count = 0
                replacement_pts_list = []
                
                for sim_i in range(num_sims):
                    taken_names = sim_drafted_sets[sim_i]
                    if c_name not in taken_names:
                        survived_count += 1
                        
                    avail_pos = [p for p in pos_records[c_pos] if p["name"] not in taken_names and p["name"] != c_name]
                    if avail_pos:
                        replacement_pts_list.append(avail_pos[0]["ufl_pts"])
                    else:
                        replacement_pts_list.append(c_pts * 0.7)

                survival_pct = round((survived_count / float(num_sims)) * 100.0, 1)
                avg_replacement = np.mean(replacement_pts_list) if replacement_pts_list else (c_pts * 0.7)
                regret_cliff = round(c_pts - avg_replacement, 1)

            volatility = 18.0 if c_pos in ["QB", "TE"] else 24.0
            floor_10 = round(c_proj_pts - volatility, 1)
            ceiling_90 = round(c_proj_pts + volatility, 1)

            # Action Badge Categorization
            cur_qbs_count = len([p for p in current_roster if p["position"] == "QB"])
            if c_pos == "QB" and cur_qbs_count < 2 and picks_until_next >= 4:
                badge = "🚨 MUST DRAFT"
                badge_desc = "QB Squeeze Imminent — Secure Starters Now"
            elif regret_cliff > 25.0 and survival_pct < 25.0:
                badge = "🚨 MUST DRAFT"
                badge_desc = "Massive Cliff Risk & Low Survival"
            elif c_gain == candidates_df["marginal_gain"].max():
                badge = "🔥 HIGH LEVERAGE"
                badge_desc = "#1 Max Net Portfolio Gain"
            elif survival_pct >= 70.0:
                badge = "⏳ CAN WAIT"
                badge_desc = "High Survival Odds — Grab on Turn"
            elif c_pos in ["RB", "WR"] and c_gain > 15.0:
                badge = "🛡️ SAFE FLOOR"
                badge_desc = "Solid Starter Portfolio Value"
            else:
                badge = "⚠️ HIGH RISK"
                badge_desc = "Positional Reach or Secondary Value"

            follow_ups = candidates_df[(candidates_df["name"] != c_name) & (candidates_df["position"] != c_pos)]
            top_follow = follow_ups.iloc[0]["name"] if not follow_ups.empty else "Best VORP Available"

            matrix_rows.append({
                "name": c_name,
                "position": c_pos,
                "team": cand["team"],
                "ufl_pts": cand["ufl_pts"],
                "ppg": round(cand["ufl_pts"] / 4.0, 1),
                "marginal_gain": c_gain,
                "projected_team_pts": c_proj_pts,
                "survival_pct": survival_pct,
                "regret_cliff": regret_cliff,
                "floor_10": floor_10,
                "ceiling_90": ceiling_90,
                "badge": badge,
                "badge_desc": badge_desc,
                "recommended_pair": f"{c_name} ({c_pos}) + {top_follow}"
            })

        top_cand = matrix_rows[0]
        second_cand = matrix_rows[1] if len(matrix_rows) > 1 else top_cand

        delta_pts = round(top_cand["marginal_gain"] - second_cand["marginal_gain"], 1)
        
        if top_cand["regret_cliff"] > second_cand["regret_cliff"]:
            cliff_diff = round(top_cand["regret_cliff"] - second_cand["regret_cliff"], 1)
            exec_dilemma = (
                f"**The Big Choice**: **{top_cand['name']}** ({top_cand['position']}) vs **{second_cand['name']}** ({second_cand['position']}) — "
                f"Drafting {top_cand['name']} provides **+{delta_pts} Net Pts** today and protects against a **-{cliff_diff} Pt {top_cand['position']} Cliff**."
            )
        else:
            exec_dilemma = (
                f"**The Big Choice**: **{top_cand['name']}** ({top_cand['position']}) vs **{second_cand['name']}** ({second_cand['position']}) — "
                f"**{top_cand['name']}** offers **+{delta_pts} Net Portfolio Gain** with **{top_cand['survival_pct']}% Survival Risk**."
            )

        top_pair_text = f"**Optimal Turn Pair**: {top_cand['recommended_pair']} (Expected Starter Total: **{top_cand['projected_team_pts']:.1f} Pts**)"

        return {
            "picks_until_next": picks_until_next,
            "is_back_to_back": is_back_to_back,
            "executive_dilemma": exec_dilemma,
            "top_pair_recommendation": top_pair_text,
            "candidates": matrix_rows
        }

