"""
Multi-Source Projection Synthesizer & UFL Converter.
Combines multiple raw projection CSVs using configurable source weights
and converts raw stats into custom UFL 4-week points.
"""

import os
import json
import pandas as pd
from engine.scoring import calculate_ufl_points
from engine.projection_fetchers import normalize_player_name, FetcherManager

class ProjectionSynthesizer:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.sources_config_path = os.path.join(data_dir, "sources.json")
        self.sources_dir = os.path.join(data_dir, "sources")
        self.overrides_path = os.path.join(data_dir, "overrides.json")
        
        # Ensure directories exist
        os.makedirs(self.sources_dir, exist_ok=True)
        self.load_config()

    def load_config(self):
        """Loads source weights and overrides configuration."""
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

    def save_config(self):
        """Saves current sources config."""
        with open(self.sources_config_path, "w") as f:
            json.dump(self.config, f, indent=2)

    def synthesize(self) -> pd.DataFrame:
        """
        Ingests all active CSV sources, applies weights, calculates consensus
        projected stats, computes UFL points, and applies overrides.
        """
        self.load_config()
        dfs = []
        
        for source in self.config.get("sources", []):
            if not source.get("enabled", True):
                continue
            
            filepath = os.path.join(self.sources_dir, source["filename"])
            if not os.path.exists(filepath):
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
                "bye_week": int(group["bye_week"].iloc[0]) if "bye_week" in group.columns and pd.notnull(group["bye_week"].iloc[0]) else 0
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

            if inj_status in ["OUT", "IR", "PUP", "SUS"]:
                inj_mult = 0.0
            elif inj_status == "DOUBTFUL":
                inj_mult = 0.25
            elif inj_status == "QUESTIONABLE":
                inj_mult = 0.75

            # Apply manual overrides if present
            if inj_mult == 0.0:
                for col in stat_cols:
                    row[col] = 0.0
            elif "touch_multiplier" in player_override:
                touch_mult = float(player_override["touch_multiplier"])
                for col in ["rush_yds", "rush_tds", "receptions", "rec_yds", "rec_tds"]:
                    row[col] = round(row[col] * touch_mult, 1)

            # Compute UFL Fantasy Points (injury multiplier applied once here)
            ufl_pts = calculate_ufl_points(row) * inj_mult
            row["ufl_pts"] = round(ufl_pts, 2)
            row["points_per_game"] = round(ufl_pts / 4.0, 1)
            row["injury_status"] = inj_status
            row["injury_multiplier"] = inj_mult
            
            aggregated.append(row)

        res_df = pd.DataFrame(aggregated)
        res_df = res_df.sort_values(by="ufl_pts", ascending=False).reset_index(drop=True)
        return res_df
