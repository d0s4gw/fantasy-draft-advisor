# UFL Fantasy Football Draft Advisor — Quick Agent Guide (`CLAUDE.md`)

This repository contains the **UFL Fantasy Football Draft Advisor 2026** (Streamlit app + math/AI engine).
For complete architectural details, see [AGENTS.md](AGENTS.md).

## Quick Reference Commands

- **Launch Dashboard**: `streamlit run app.py`
- **Run Test Suite**: `python test_system.py`
- **Run Mock Draft**: `python run_mock_draft.py`
- **Run Monte Carlo Variance Stress-Tester**: `python run_variance_simulation.py`
- **Precompute Gameplan**: `python precompute_gameplan.py`
- **Update Projections**: `python populate_real_projections.py`

## Core Architecture Principles

1. **UFL Scoring Math**:
   - Rushing & Receiving Yards = **0.20 pts/yd** (1 pt per 5 yards — 2x multiplier).
   - Passing Yards = **0.04 pts/yd**, Pass TD = 4 pts, INT = -2 pts, PPR = 0.3.
2. **Draft Context**:
   - 6 Teams (Governors), 12 Rounds, 72 Total Picks.
   - User Target Team = `Team 1 (User)`.
   - Primary target window = **Q1 (Weeks 1–4)**.
3. **Data Integrity**:
   - State managed in `engine/draft_state.py` and saved to `data/draft_state.json`.
   - Projections synthesized across CSVs in `data/sources/` using `engine/projection_synth.py`.

## Directory Agent Guides

- **Engine Architecture**: [engine/AGENTS.md](engine/AGENTS.md)
- **Data Schemas & Sources**: [data/AGENTS.md](data/AGENTS.md)
