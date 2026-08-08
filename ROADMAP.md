# UFL Fantasy Football Draft Advisor — Roadmap

## Backlog

### Per-Week Player Projections
**Priority**: Medium (build before Q2 draft, or when weekly source data becomes available)
**Status**: Planned

Replace the flat 4-week aggregate projection model with per-week stat projections (W1–W4). Compute UFL score per week, sum weeks 1–4 for Q1. The optimizer solves 4 independent weekly lineups — a player with 0 pts in a week (bye, suspension, injury) gets benched and a bench player starts.

**Why deferred**: No team has a bye in Weeks 1–4. Weekly projections from FantasyPros/ETR aren't published until the regular season starts (September). No Q1-impacting suspensions found as of August 2026. The current injury override system (`overrides.json`) handles known absences adequately for Q1.

**Key changes when built**:
- Source CSVs get a `week` column (1 row per player per week)
- `projection_synth.py` outputs `ufl_pts_w1`–`ufl_pts_w4` columns
- `joint_optimizer.py` gets `solve_4_week_portfolio()` that solves 4 independent weekly lineups
- `draft_state.py` stores per-week points in pick records
- Legacy season-long CSVs fall back to `÷ 17` per game across weeks 1–4
- App UI shows W1–W4 breakdown with opponents

**Triggers to build**:
- Q2 draft approaches (byes fall in Weeks 5–8)
- Weekly projection CSVs become available from a source
- A relevant player has a Q1 suspension

---

## Recently Completed

### Optimal Roster Lineup & Draft Results Projections
**Status**: Completed (August 2026)
Added a dedicated **Draft Results** tab in `app.py` displaying optimal starting lineup weekly (W1–W4 average) and 4-week quarter projections for all 6 teams, based on custom UFL scoring rules and roster constraints, along with stacked positional composition charts.

### Automated Data Ingestion & Injury Sync
**Status**: Completed (August 2026)
Built `refresh_draft_data.py` and `projection_fetchers.py` to handle automated FantasyPros CSV ingestion from `~/Downloads`, live web scraping fallbacks, and real-time Sleeper API injury status synchronization (`PUP`, `QUESTIONABLE`, `OUT`, `IR`).

