"""
FantasyPros 2026 Projection Importer.
Reads season-long FantasyPros CSV exports (QB, RB, WR, TE),
converts to per-game stats, and writes a unified source CSV
for the projection synthesizer.

Usage:
    python import_fantasypros.py [--downloads-dir ~/Downloads]

The script looks for these files in the downloads directory:
    - FantasyPros_Fantasy_Football_Projections_QB.csv
    - FantasyPros_Fantasy_Football_Projections_RB.csv
    - FantasyPros_Fantasy_Football_Projections_WR.csv
    - FantasyPros_Fantasy_Football_Projections_TE.csv
"""

import os
import sys
import glob
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SOURCES_DIR = os.path.join(DATA_DIR, "sources")
OUTPUT_FILE = os.path.join(SOURCES_DIR, "fantasypros.csv")

GAMES_PER_SEASON = 17
NUM_Q_WEEKS = 4  # Number of scoring weeks in the target quarter


def clean_number(val):
    """Parse a string like '1,381.0' into a float."""
    if pd.isna(val) or val == "":
        return 0.0
    return float(str(val).replace(",", ""))


def import_qb(filepath: str) -> pd.DataFrame:
    """Import QB projections. Columns: Player, Team, ATT, CMP, YDS, TDS, INTS, ATT, YDS, TDS, FL, FPTS"""
    df = pd.read_csv(filepath, skiprows=1)  # Skip the blank second row by re-reading
    # Re-read with proper handling
    df = pd.read_csv(filepath)
    # Skip blank rows
    df = df[df["Player"].str.strip() != ""].copy()
    df = df[df["Player"].notna()].copy()

    # The CSV has duplicate column names (ATT, YDS, TDS appear twice: passing then rushing)
    # Read raw and use positional indexing
    raw = pd.read_csv(filepath, header=None, skiprows=2)
    raw = raw[raw[0].notna() & (raw[0].str.strip() != "")]

    rows = []
    for _, r in raw.iterrows():
        name = str(r[0]).strip().strip('"')
        team = str(r[1]).strip().strip('"')
        if not name or name == " ":
            continue
        rows.append({
            "name": name,
            "position": "QB",
            "team": team,
            "pass_yds": clean_number(r[4]),      # Passing YDS (col index 4)
            "pass_tds": clean_number(r[5]),      # Passing TDS
            "pass_ints": clean_number(r[6]),     # INTS
            "rush_yds": clean_number(r[8]),      # Rushing YDS (col index 8)
            "rush_tds": clean_number(r[9]),      # Rushing TDS
            "receptions": 0.0,
            "rec_yds": 0.0,
            "rec_tds": 0.0,
        })
    return pd.DataFrame(rows)


def import_rb(filepath: str) -> pd.DataFrame:
    """Import RB projections. Columns: Player, Team, ATT, YDS, TDS, REC, YDS, TDS, FL, FPTS"""
    raw = pd.read_csv(filepath, header=None, skiprows=2)
    raw = raw[raw[0].notna() & (raw[0].str.strip() != "")]

    rows = []
    for _, r in raw.iterrows():
        name = str(r[0]).strip().strip('"')
        team = str(r[1]).strip().strip('"')
        if not name or name == " ":
            continue
        rows.append({
            "name": name,
            "position": "RB",
            "team": team,
            "pass_yds": 0.0,
            "pass_tds": 0.0,
            "pass_ints": 0.0,
            "rush_yds": clean_number(r[3]),      # Rushing YDS
            "rush_tds": clean_number(r[4]),      # Rushing TDS
            "receptions": clean_number(r[5]),    # REC
            "rec_yds": clean_number(r[6]),       # Receiving YDS
            "rec_tds": clean_number(r[7]),       # Receiving TDS
        })
    return pd.DataFrame(rows)


def import_wr(filepath: str) -> pd.DataFrame:
    """Import WR projections. Columns: Player, Team, REC, YDS, TDS, ATT, YDS, TDS, FL, FPTS"""
    raw = pd.read_csv(filepath, header=None, skiprows=2)
    raw = raw[raw[0].notna() & (raw[0].str.strip() != "")]

    rows = []
    for _, r in raw.iterrows():
        name = str(r[0]).strip().strip('"')
        team = str(r[1]).strip().strip('"')
        if not name or name == " ":
            continue
        rows.append({
            "name": name,
            "position": "WR",
            "team": team,
            "pass_yds": 0.0,
            "pass_tds": 0.0,
            "pass_ints": 0.0,
            "rush_yds": clean_number(r[6]),      # Rushing YDS (col index 6, after rec stats)
            "rush_tds": clean_number(r[7]),      # Rushing TDS
            "receptions": clean_number(r[2]),    # REC
            "rec_yds": clean_number(r[3]),       # Receiving YDS
            "rec_tds": clean_number(r[4]),       # Receiving TDS
        })
    return pd.DataFrame(rows)


def import_te(filepath: str) -> pd.DataFrame:
    """Import TE projections. Columns: Player, Team, REC, YDS, TDS, FL, FPTS"""
    raw = pd.read_csv(filepath, header=None, skiprows=2)
    raw = raw[raw[0].notna() & (raw[0].str.strip() != "")]

    rows = []
    for _, r in raw.iterrows():
        name = str(r[0]).strip().strip('"')
        team = str(r[1]).strip().strip('"')
        if not name or name == " ":
            continue
        rows.append({
            "name": name,
            "position": "TE",
            "team": team,
            "pass_yds": 0.0,
            "pass_tds": 0.0,
            "pass_ints": 0.0,
            "rush_yds": 0.0,
            "rush_tds": 0.0,
            "receptions": clean_number(r[2]),    # REC
            "rec_yds": clean_number(r[3]),       # Receiving YDS
            "rec_tds": clean_number(r[4]),       # Receiving TDS
        })
    return pd.DataFrame(rows)


def main():
    # Find the downloads directory
    downloads_dir = os.path.expanduser("~/Downloads")
    if len(sys.argv) > 2 and sys.argv[1] == "--downloads-dir":
        downloads_dir = os.path.expanduser(sys.argv[2])

    # Load bye weeks from the canonical data/bye_weeks.json
    bye_weeks_map = {}
    bye_weeks_path = os.path.join(DATA_DIR, "bye_weeks.json")
    if os.path.exists(bye_weeks_path):
        import json
        with open(bye_weeks_path, "r") as f:
            raw_bye = json.load(f)
        bye_weeks_map = {k: int(v) for k, v in raw_bye.items() if not k.startswith("_")}
        for alias, canonical in raw_bye.get("_aliases", {}).items():
            if canonical in bye_weeks_map:
                bye_weeks_map[alias] = bye_weeks_map[canonical]
        print(f"📅 Loaded bye weeks for {len(bye_weeks_map)} NFL team codes/aliases from bye_weeks.json")
    else:
        print("⚠️  bye_weeks.json not found — bye_week column will be 0 for all players")

    # Map position to importer function
    positions = {
        "QB": import_qb,
        "RB": import_rb,
        "WR": import_wr,
        "TE": import_te,
    }

    all_dfs = []
    for pos, importer_fn in positions.items():
        # Find the most recent file for this position
        pattern = os.path.join(downloads_dir, f"FantasyPros_Fantasy_Football_Projections_{pos}*.csv")
        matches = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        if not matches:
            print(f"⚠️  No {pos} CSV found in {downloads_dir}")
            continue

        filepath = matches[0]
        print(f"📥 Importing {pos} from: {os.path.basename(filepath)}")
        df = importer_fn(filepath)
        print(f"   Found {len(df)} {pos} players")
        all_dfs.append(df)

    if not all_dfs:
        print("❌ No projection files found! Download CSVs from FantasyPros first.")
        sys.exit(1)

    # Combine all positions
    combined = pd.concat(all_dfs, ignore_index=True)

    # Convert stats to target quarter (NUM_Q_WEEKS) totals
    # FantasyPros CSVs are per-game averages -> multiply by NUM_Q_WEEKS
    stat_cols = ["pass_yds", "pass_tds", "pass_ints", "rush_yds", "rush_tds",
                 "receptions", "rec_yds", "rec_tds"]
    for col in stat_cols:
        combined[col] = (combined[col] * NUM_Q_WEEKS).round(1)

    # Add required columns
    combined["two_pts"] = 0.0
    combined["adp"] = range(1, len(combined) + 1)  # Placeholder ADP by projection rank
    # Assign bye week from canonical bye_weeks.json
    combined["bye_week"] = combined["team"].apply(lambda t: bye_weeks_map.get(str(t).upper(), 0))

    # Sort by projected value (rough estimate: rush+rec yards)
    combined = combined.sort_values(
        by=["pass_yds", "rush_yds", "rec_yds"],
        ascending=False
    ).reset_index(drop=True)
    combined["adp"] = range(1, len(combined) + 1)

    # Write output
    os.makedirs(SOURCES_DIR, exist_ok=True)
    combined.to_csv(OUTPUT_FILE, index=False)

    print(f"\n✅ Successfully wrote {len(combined)} players to {OUTPUT_FILE}")
    print(f"   Stats converted: per-game × {NUM_Q_WEEKS} weeks")
    bye_in_q2 = combined[combined["bye_week"].isin([5, 6, 7, 8])]
    print(f"   Bye weeks assigned: {len(combined[combined['bye_week'] > 0])} players with byes ({len(bye_in_q2)} with Q2 byes)")

    # Show top 5 per position
    for pos in ["QB", "RB", "WR", "TE"]:
        pos_df = combined[combined["position"] == pos].head(5)
        print(f"\n   Top 5 {pos}s:")
        for _, r in pos_df.iterrows():
            key_stat = f"pass_yds={r['pass_yds']}" if pos == "QB" else f"rush_yds={r['rush_yds']}, rec_yds={r['rec_yds']}"
            print(f"     {r['name']} ({r['team']}) — {key_stat}")


if __name__ == "__main__":
    main()
