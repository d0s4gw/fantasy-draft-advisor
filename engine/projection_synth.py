"""
Multi-Source Projection Synthesizer & UFL Converter.
Combines multiple raw projection CSVs using configurable source weights
and converts raw stats into custom UFL Q2 (Weeks 5-8) points with
bye week zeroing and per-week breakdown columns.
"""

import os
import json
import pandas as pd
from engine.scoring import calculate_ufl_points
from engine.projection_fetchers import normalize_player_name, FetcherManager, enrich_bye_weeks

class ProjectionSynthesizer:
    # Default scoring coefficients (fallback if config.json missing)
    DEFAULT_SCORING_RULES = {
        "pass_yds_per_pt": 25.0, "pass_td_pts": 4.0, "pass_int_pts": -2.0,
        "rush_yds_per_pt": 5.0, "rush_td_pts": 6.0,
        "rec_pts": 0.3, "rec_yds_per_pt": 5.0, "rec_td_pts": 6.0,
        "two_pt_pts": 2.0
    }

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.sources_config_path = os.path.join(data_dir, "sources.json")
        self.sources_dir = os.path.join(data_dir, "sources")
        self.overrides_path = os.path.join(data_dir, "overrides.json")
        self.league_config_path = os.path.join(data_dir, "config.json")
        
        # Ensure directories exist
        os.makedirs(self.sources_dir, exist_ok=True)
        self.load_config()

    def load_config(self):
        """Loads source weights, overrides, league config, and bye week schedule."""
        if os.path.exists(self.sources_config_path):
            with open(self.sources_config_path, "r") as f:
                self.config = json.load(f)
        else:
            self.config = {"sources": []}

        if os.path.exists(self.overrides_path):
            with open(self.overrides_path, "r") as f:
                self.overrides = json.load(f)
        else:
            self.overrides = {"players": {}}

        # Load scoring rules and quarter config from league config.json
        self.scoring_rules = self.DEFAULT_SCORING_RULES.copy()
        self.weeks = [5, 6, 7, 8]  # default Q2
        self.target_quarter = "Q2"
        if os.path.exists(self.league_config_path):
            try:
                with open(self.league_config_path, "r") as f:
                    league_cfg = json.load(f)
                self.scoring_rules = league_cfg.get("scoring_rules", self.DEFAULT_SCORING_RULES)
                self.weeks = league_cfg.get("weeks", [5, 6, 7, 8])
                self.target_quarter = league_cfg.get("target_quarter", "Q2")
                # Load bye weeks from referenced file
                bye_file = league_cfg.get("bye_weeks_file", "bye_weeks.json")
            except Exception:
                bye_file = "bye_weeks.json"
        else:
            bye_file = "bye_weeks.json"

        # Load bye weeks schedule
        self.bye_weeks_map = {}
        bye_path = os.path.join(self.data_dir, bye_file)
        if os.path.exists(bye_path):
            try:
                with open(bye_path, "r") as f:
                    raw_bye = json.load(f)
                # Filter out metadata keys (non-team-abbr keys start with _)
                self.bye_weeks_map = {k: int(v) for k, v in raw_bye.items() if not k.startswith("_")}
                # Load aliases so alternative team abbreviations (e.g. JAC->JAX, WSH->WAS) resolve
                aliases = raw_bye.get("_aliases", {})
                for alias, canonical in aliases.items():
                    if canonical in self.bye_weeks_map:
                        self.bye_weeks_map[alias] = self.bye_weeks_map[canonical]
            except Exception as e:
                print(f"⚠️  WARNING: Could not load bye_weeks.json: {e}")

    def save_config(self):
        """Saves current sources config."""
        with open(self.sources_config_path, "w") as f:
            json.dump(self.config, f, indent=2)

    def synthesize(self) -> pd.DataFrame:
        """
        Ingests all active CSV sources, applies weights, calculates consensus
        projected stats, computes UFL points, applies bye week zeroing,
        generates per-week point columns, and applies overrides.
        """
        self.load_config()
        dfs = []
        
        for source in self.config.get("sources", []):
            if not source.get("enabled", True):
                continue
            
            filepath = os.path.join(self.sources_dir, source["filename"])
            if not os.path.exists(filepath):
                print(f"⚠️  WARNING: Source '{source['name']}' is enabled but file '{source['filename']}' not found in data/sources/. Skipping.")
                continue
                
            try:
                df = pd.read_csv(filepath)
                # Ensure standard columns exist
                required_cols = ["name", "position", "team"]
                if not all(col in df.columns for col in required_cols):
                    continue
                    
                df["name"] = df["name"].apply(normalize_player_name)
                df["source_weight"] = float(source.get("weight", 1.0))
                dfs.append(df)
            except Exception as e:
                print(f"Error loading source {source['filename']}: {e}")

        if not dfs:
            return pd.DataFrame()

        # Combine sources
        combined = pd.concat(dfs, ignore_index=True)

        # Stat fields to aggregate
        stat_cols = [
            "pass_yds", "pass_tds", "pass_ints",
            "rush_yds", "rush_tds",
            "receptions", "rec_yds", "rec_tds", "two_pts"
        ]
        
        for col in stat_cols:
            if col not in combined.columns:
                combined[col] = 0.0
            else:
                combined[col] = combined[col].fillna(0.0)

        # Weighted aggregation grouped by player name & position
        aggregated = []
        grouped = combined.groupby(["name", "position", "team"])

        for (name, pos, team), group in grouped:
            total_weight = group["source_weight"].sum()
            row = {
                "name": name,
                "position": pos.upper(),
                "team": team.upper(),
                "adp": group["adp"].mean() if "adp" in group.columns else 999.0,
            }
            
            # Weighted average for stats
            for col in stat_cols:
                weighted_val = (group[col] * group["source_weight"]).sum() / total_weight if total_weight > 0 else 0.0
                row[col] = round(weighted_val, 1)

            # Check injury status from group or overrides
            inj_status = "HEALTHY"
            inj_mult = 1.0
            
            if "injury_status" in group.columns and pd.notnull(group["injury_status"].iloc[0]):
                inj_status = str(group["injury_status"].iloc[0]).upper().strip()

            player_override = self.overrides.get("players", {}).get(name, {})
            if "status" in player_override:
                inj_status = str(player_override["status"]).upper().strip()

            if inj_status in ["OUT", "IR", "PUP", "SUS", "SUSPENDED", "DNR", "INJURED RESERVE", "NFI"]:
                inj_mult = 0.0
            elif inj_status == "DOUBTFUL":
                inj_mult = 0.25
            elif inj_status == "QUESTIONABLE":
                inj_mult = 0.75

            # Apply injury multiplier to stats (single discount point)
            if inj_mult == 0.0:
                for col in stat_cols:
                    row[col] = 0.0
            elif inj_mult < 1.0:
                for col in stat_cols:
                    row[col] = round(row[col] * inj_mult, 1)

            # Apply manual touch_multiplier override (independent of injury mult)
            if "touch_multiplier" in player_override and inj_mult > 0.0:
                touch_mult = float(player_override["touch_multiplier"])
                for col in ["rush_yds", "rush_tds", "receptions", "rec_yds", "rec_tds"]:
                    row[col] = round(row[col] * touch_mult, 1)

            # Get authoritative bye week from the canonical bye_weeks_map
            team_upper = team.upper()
            bye_week = self.bye_weeks_map.get(team_upper, 0)
            # Fallback: check if source CSV had a bye_week column
            if bye_week == 0 and "bye_week" in group.columns:
                csv_bye = group["bye_week"].iloc[0]
                if pd.notnull(csv_bye) and int(csv_bye) > 0:
                    bye_week = int(csv_bye)
            row["bye_week"] = bye_week

            # Compute total 4-week UFL Fantasy Points from discounted stats
            # This is the sum across all scoring weeks, accounting for the bye
            ufl_pts_full = calculate_ufl_points(row, self.scoring_rules)
            num_weeks = len(self.weeks)
            num_active_weeks = sum(1 for w in self.weeks if w != bye_week)

            # Scale total pts: if player has a bye in the scoring window, they only play num_active_weeks
            # The raw ufl_pts_full is for (num_weeks) game-equivalents; zero the bye week
            if bye_week in self.weeks and num_weeks > 0:
                # Per-week value, then zero the bye week
                per_week_pts = ufl_pts_full / num_weeks
                ufl_pts = round(per_week_pts * num_active_weeks, 2)
            else:
                ufl_pts = round(ufl_pts_full, 2)

            row["ufl_pts"] = ufl_pts

            # Compute per-week point columns for the optimizer
            for week in self.weeks:
                col = f"ufl_pts_w{week}"
                if week == bye_week:
                    row[col] = 0.0
                else:
                    # Distribute evenly across non-bye weeks
                    row[col] = round(ufl_pts / num_active_weeks, 2) if num_active_weeks > 0 else 0.0

            # Points per active game (PPG)
            row["points_per_game"] = round(ufl_pts / num_active_weeks, 1) if num_active_weeks > 0 else 0.0
            row["injury_status"] = inj_status
            row["injury_multiplier"] = inj_mult
            
            aggregated.append(row)

        res_df = pd.DataFrame(aggregated)
        res_df = res_df.sort_values(by="ufl_pts", ascending=False).reset_index(drop=True)
        return res_df
