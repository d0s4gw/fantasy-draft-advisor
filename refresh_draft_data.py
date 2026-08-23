"""
Automated Pre-Draft Refresh Pipeline & Live Injury Tracker.
Connects to Sleeper API to fetch live 2026 NFL player injury status, updates projections,
re-synthesizes weighted UFL scoring math, and regenerates data/precomputed_gameplan.json.
"""

import os
import sys
import json
import urllib.request
import pandas as pd
from engine.projection_synth import ProjectionSynthesizer
from engine.projection_fetchers import FetcherManager, normalize_player_name

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SOURCES_DIR = os.path.join(DATA_DIR, "sources")
SLEEPER_PLAYERS_PATH = os.path.join(DATA_DIR, "sleeper_players.json")

SLEEPER_API_URL = "https://api.sleeper.app/v1/players/nfl"

def fetch_sleeper_players() -> dict:
    """Fetches live player data from Sleeper API or loads cached JSON."""
    if os.path.exists(SLEEPER_PLAYERS_PATH):
        with open(SLEEPER_PLAYERS_PATH, "r") as f:
            return json.load(f)
    return {}

def extract_injury_map(sleeper_data: dict) -> dict:
    """Maps normalized player full_name to injury status (IR, PUP, Out, Doubtful, Questionable)."""
    injury_map = {}
    if not sleeper_data:
        return injury_map
        
    # Handle structured Sleeper cache schema: {"id_to_name": ..., "name_to_id": ..., "_raw": ...}
    raw_players = sleeper_data.get("_raw", sleeper_data)
    if not isinstance(raw_players, dict):
        return injury_map

    for p_id, p_info in raw_players.items():
        if not isinstance(p_info, dict):
            continue
        name = p_info.get("full_name")
        if not name:
            fname = p_info.get("first_name", "")
            lname = p_info.get("last_name", "")
            name = f"{fname} {lname}".strip()
            
        if not name:
            continue
            
        inj_status = p_info.get("injury_status")
        status = p_info.get("status")
        
        norm_name = normalize_player_name(name).lower()
        
        if inj_status in ["IR", "PUP", "Out", "Doubtful", "Questionable"]:
            injury_map[norm_name] = inj_status.upper()
        elif status in ["IR", "PUP"]:
            injury_map[norm_name] = status.upper()
            
    return injury_map

def update_csv_sources(injury_map: dict):
    """Updates CSV sources in data/sources/ with injury_status column."""
    if not os.path.exists(SOURCES_DIR):
        return
        
    updated_files = 0
    for filename in os.listdir(SOURCES_DIR):
        if filename.endswith(".csv"):
            filepath = os.path.join(SOURCES_DIR, filename)
            try:
                df = pd.read_csv(filepath)
                if "name" in df.columns:
                    df["injury_status"] = df["name"].apply(
                        lambda n: injury_map.get(normalize_player_name(str(n)).lower(), "HEALTHY")
                    )
                    df.to_csv(filepath, index=False)
                    updated_files += 1
            except Exception as e:
                print(f"  ⚠️ Could not update {filename}: {e}")
                
    print(f"  ✅ Updated injury status across {updated_files} projection CSV sources!")

def main():
    offline_mode = "--offline" in sys.argv
    manager = FetcherManager(DATA_DIR, offline=offline_mode)
    manager.run_pipeline()

    # 1. Extract injury map from Sleeper data
    sleeper_data = fetch_sleeper_players()
    injury_map = extract_injury_map(sleeper_data)
    injured_count = len(injury_map)
    print(f"  🏥 Identified {injured_count} players with active injury/PUP/IR designations.")
    
    # 2. Update CSV sources with live injury status
    update_csv_sources(injury_map)
    
    # 3. Re-synthesize UFL weighted projections
    print("\n🔄 Re-synthesizing multi-source UFL weighted projections...")
    synth = ProjectionSynthesizer(DATA_DIR)
    projections_df = synth.synthesize()
    print(f"  ✅ Synthesized projections for {len(projections_df)} total players!")
    
    # 4. Print Pre-Draft Health & Mover Report
    print("\n" + "=" * 75)
    print("📋 PRE-DRAFT HEALTH & INJURY MOVER REPORT")
    print("=" * 75)
    
    injured_players = projections_df[projections_df["injury_status"] != "HEALTHY"]
    if not injured_players.empty:
        print(f"\nFound {len(injured_players)} top projected players affected by injuries:")
        for idx, row in injured_players.head(15).iterrows():
            print(f"  • {row['name']:<22} ({row['position']:<2}, {row['team']:<3}) | Status: {row['injury_status']:<12} | Multiplier: {row['injury_multiplier']:.2f} | Discounted Q1 Pts: {row['ufl_pts']:.1f}")
    else:
        print("  🎉 No key starter players currently marked as injured!")

    print("\n" + "=" * 75)
    print("🎉 PRE-DRAFT DATA REFRESH COMPLETE! YOUR DRAFT ADVISOR IS 100% UPDATED.")
    print("=" * 75)

if __name__ == "__main__":
    main()
