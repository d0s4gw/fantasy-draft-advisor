# Data Architecture & Schemas (`data/AGENTS.md`)

The `data/` directory houses configuration settings, draft state tracking persistence, precomputed strategy caches, Sleeper API lookup tables, and multi-source projection CSV files.

---

## Data File Inventory

| File / Folder | Purpose | Dynamic / Static | Primary Consumer |
| :--- | :--- | :--- | :--- |
| [LEAGUE_RULES.md](LEAGUE_RULES.md) | **CANONICAL** league rules — single source of truth for roster, scoring, lineup | Static / Authoritative | All engines, all agents |
| [config.json](config.json) | League configuration, Governors, roster limits, GCP settings | Static / Config | `DraftState`, `app.py` |
| [draft_state.json](draft_state.json) | Live pick history, current pick tracker, governor roster state | Dynamic (Auto-saved) | `DraftState` |
| [precomputed_gameplan.json](precomputed_gameplan.json) | Tactical scouting notes & round-by-round target strategies | Static (Precomputed) | `PrecomputedEngine` |
| [sources.json](sources.json) | Projection source weighting & CSV filenames mapping | Config | `ProjectionSynthesizer` |
| [sleeper_players.json](sleeper_players.json) | Sleeper player ID mapping lookup table | Static / Cached | `SleeperSync` |
| [sources/](sources/) | Directory containing raw CSV files from projection providers | Data Inputs | `ProjectionSynthesizer` |

---

## 1. Schema Specifications

### `data/config.json`
```json
{
  "league_name": "UFL Fantasy Football",
  "num_teams": 6,
  "num_rounds": 12,
  "target_quarter": "Q1",
  "weeks": [1, 2, 3, 4],
  "my_team_name": "Team 1 (User)",
  "governors": [
    "Team 1 (User)",
    "Team 2",
    "Team 3",
    "Team 4",
    "Team 5",
    "Team 6"
  ],
  "roster_settings": {
    "QB": 2,
    "RB": 1,
    "WR": 1,
    "TE": 1,
    "FLEX": 2,
    "BENCH": 5
  },
  "scoring_rules": {
    "pass_yds_per_pt": 25.0,
    "pass_td_pts": 4.0,
    "pass_int_pts": -2.0,
    "rush_yds_per_pt": 5.0,
    "rush_td_pts": 6.0,
    "rec_pts": 0.3,
    "rec_yds_per_pt": 5.0,
    "rec_td_pts": 6.0,
    "two_pt_pts": 2.0
  },
  "gcp_project_id": "YOUR_GCP_PROJECT_ID",
  "gcp_location": "us-central1"
}
```

### `data/draft_state.json`
```json
{
  "picks_history": [
    {
      "pick_no": 1,
      "round": 1,
      "governor": "Team 1 (User)",
      "player_name": "Christian McCaffrey",
      "position": "RB",
      "team": "SF",
      "ufl_pts": 175.8,
      "timestamp": 1722648000.0
    }
  ]
}
```

### `data/sources.json`
```json
{
  "sources": [
    {
      "id": "baseline",
      "name": "Baseline Consensus 2026",
      "filename": "baseline_2026.csv",
      "weight": 1.0,
      "enabled": true,
      "auto_fetch": false
    },
    {
      "id": "fantasypros",
      "name": "FantasyPros Projections",
      "filename": "fantasypros.csv",
      "weight": 1.2,
      "enabled": true,
      "auto_fetch": true,
      "fetcher_type": "fantasypros_downloads",
      "cache_ttl_hours": 12
    },
    {
      "id": "underdog",
      "name": "Underdog / ETR Projections",
      "filename": "underdog.csv",
      "weight": 1.5,
      "enabled": true,
      "auto_fetch": false
    }
  ]
}
```

---

## 2. Projection CSV Specifications (`data/sources/`)

All projection CSV files stored in `data/sources/` must contain the following required or transformable column headers:

| Field Name | Description | Example Values |
| :--- | :--- | :--- |
| `Player` / `name` | Full Player Name | `"Christian McCaffrey"` |
| `Pos` / `position` | Positional Designation | `"QB"`, `"RB"`, `"WR"`, `"TE"` |
| `Team` / `team` | NFL Franchise Tri-code | `"SF"`, `"KC"`, `"PHI"` |
| `PassYds` | Per-game passing yardage projection | `265.4` |
| `PassTD` | Per-game passing touchdown projection | `1.8` |
| `Int` | Per-game interception projection | `0.6` |
| `RushYds` | Per-game rushing yardage projection | `82.5` |
| `RushTD` | Per-game rushing touchdown projection | `0.8` |
| `Rec` | Per-game receptions projection | `5.2` |
| `RecYds` | Per-game receiving yardage projection | `45.1` |
| `RecTD` | Per-game receiving touchdown projection | `0.4` |

---

## 3. Data Editing & Maintenance Guidelines

1. **Resetting Draft State**: To reset the draft state, empty `picks_history` in `data/draft_state.json` to `[]` or click **🚨 Reset Draft** in the sidebar.
2. **Adding New Sources**: Drop the new CSV into `data/sources/` and append an entry in `data/sources.json`.
3. **Precomputing**: Run `python precompute_gameplan.py` to regenerate scouting notes in `data/precomputed_gameplan.json`.
