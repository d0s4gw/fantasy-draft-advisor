# UFL Fantasy Football Draft Advisor — Roadmap

## Recently Completed

### Q4 Scoring Window, Matchup Projections & Recency Weighting
**Status**: Completed (November 2026)
- **Target Quarter Configured**: Switched target scoring window to **Q4 (Weeks 13–16)** across [LEAGUE_RULES.md](data/LEAGUE_RULES.md) and [config.json](data/config.json) (6 teams on bye: W13 BAL/IND/LV/NYJ, W14 ARI/DAL; 0 byes in W15–16).
- **Per-Week Matchup Projections**: Preserved individual weekly Sleeper/RotoWire matchup ratios (`wk_ratio_w13`–`wk_ratio_w16`) from live weekly projections through `ProjectionSynthesizer` into `JointOptimizer.solve_4_week_portfolio()`.
- **Recency-Weighted Sleeper YTD**: Weighted the most recent 4 completed weeks at `2.0×` vs. earlier weeks (`1.0×`) in `SleeperStatsFetcher`, plus added `l4w_pts` (Last 4 Weeks 4-game pace) tracking.
- **Calibrated `QUESTIONABLE` Discount & Injury Badges**: Refined `QUESTIONABLE` from `0.75×` to `0.90×` (keeping `OUT` at `0.75×` and `IR/PUP/SUS` at `0.0×`) and surfaced explicit injury badges in the Command Center & War Room.
- **In-App Quick Overrides & UI Polish**: Added sidebar player override editor, active-game PPG display, bye-aware standings, and always-visible Sleeper sync status.

### Q2 Scoring Window & Per-Week Bye Modeling
**Status**: Completed (September/October 2026)
- **Target Quarter Configured**: Switched target scoring window to **Q2 (Weeks 5–8)** in [LEAGUE_RULES.md](data/LEAGUE_RULES.md) and [config.json](data/config.json).
- **2026 Bye Schedule Integration**: Loaded canonical 2026 bye schedule in [bye_weeks.json](data/bye_weeks.json), mapping all 14 NFL teams with byes in Weeks 5–8 (CAR, KC, CIN, DET, MIA, MIN, BUF, JAX, LAC, WAS, HOU, NO, NYG, SF).
- **Per-Week Point Columns**: Built `ufl_pts_w5` through `ufl_pts_w8` generation in `projection_synth.py` with automated bye-week zeroing and active PPG calculations.
- **Independent Weekly Portfolio Optimizer**: Built `solve_4_week_portfolio()` in `joint_optimizer.py` solving 4 independent weekly optimal starting lineups with automatic bench substitution for starters on bye.
- **Q2 Cliff & Squeeze Alerts**: Calibrated `vorp_calculator.py` with bye annotations and adjusted QB squeeze thresholds for 3-game QBs.
- **Prominent Q2 UI Presence**: Added high-visibility Q2 target header banners, sidebar status badges, dynamic table columns, and standings labels across the Streamlit dashboard.

### Optimal Roster Lineup & Draft Results Projections
**Status**: Completed (August 2026)
Added a dedicated **Draft Results** tab in `app.py` displaying optimal starting lineup weekly (PPG) and 4-week quarter projections for all 6 teams, based on custom UFL scoring rules and roster constraints, along with stacked positional composition charts.

### Live Sleeper YTD Actuals Ingestion & Auto-Refresh
**Status**: Completed (October 2026)
Built `SleeperStatsFetcher` to dynamically scan completed regular season weeks via the Sleeper API (`/v1/stats/nfl/regular/{season}/{week}`). Automatically aggregates completed weeks (e.g. Weeks 1–3, auto-expanding to Week 4 upon completion), calculates per-game run rates, scales them to 4-week quarter projections, and integrates with the multi-source weighted synthesizer. Registered in [sources.json](data/sources.json) with dynamic UI sidebar weight controls.

### Automated Data Ingestion & Injury Sync
**Status**: Completed (August 2026)
Built `refresh_draft_data.py` and `projection_fetchers.py` to handle automated FantasyPros CSV ingestion from `~/Downloads`, live web scraping fallbacks, and real-time Sleeper API injury status synchronization (`PUP`, `QUESTIONABLE`, `OUT`, `IR`).


