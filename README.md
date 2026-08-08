# Fantasy Football Draft Advisor 2026

A high-speed, single-user local Python application built for high-stakes fantasy football draft optimization and real-time decision support.

---

## Key Features

1. **Custom Scoring Math Engine**:
   - Rushing & Receiving Yards: **1 pt per 5 yards ($0.20\text{ pts/yd}$)** — 2x multiplier vs standard fantasy.
   - 0.3 PPR, 4 pt Pass TD, -2 INT, 2 pt 2-Point Conversion.
   - Fumble Lost: 0 pts (not penalized). ST Player TD: 6 pts (not projected).
   - Tailored specifically for **Q1 (Weeks 1–4)**.

2. **Knapsack Portfolio VORP & Starter-Only Standings**:
   - Evaluates **Marginal Portfolio Gain** for candidate picks across 7 starters (`2 QB, 1 RB, 1 WR, 1 TE, 2 FLEX`).
   - Displays live standings calculated strictly from optimal starting lineups (bench players score 0).

3. **Live Recommendation & Turn Strategy War Room Engine**:
   - **Live Math Optimizer (`LiveMathEngine`)**: Sub-second Knapsack VORP, starter standings, and positional scarcity calculations.
   - **Strategy Presets (`strategy_presets.py`)**: Supports macro strategy overrides (*Zero-RB*, *Hero-RB*, *Robust Dual RB*, *Elite TE Anchor*, *Pure Math VORP*).
   - **Dynamic AUTO Strategy**: Adapts in real-time with 5 triggers (QB Squeeze, RB Cliff, Elite TE Window, Roster Compliance, WR Volume Loading).
   - **Turn Strategy War Room**: Real-time Monte Carlo simulations providing candidate survival odds, regret cliffs, 10th/90th percentile outcome ranges, and automated decision badges.

4. **Sleeper API Live Draft Auto-Sync**:
   - Automatically polls your Sleeper draft room (`GET /v1/draft/<draft_id>/picks`) every 1.5s.
   - As opponents (`Team 2`, `Team 3`, etc.) pick in Sleeper, their picks register in your app in under 1 second without manual typing.

5. **Monte Carlo High-Variance Strategy Stress-Tester**:
   - Runs 500+ stochastic draft iterations with random noise ($\sigma \in [5\%, 15\%, 25\%]$) applied to opponent evaluations.
   - Tests strategy resilience against draft chaos, reaches, and local maxima.

6. **QB Supply Squeeze & Opponent Steal Predictor**:
   - Monitors draft matrix across all 6 Governors (`Team 1 (User)`, `Team 2`, `Team 3`, `Team 4`, `Team 5`, `Team 6`).
   - Flags when opponents picking before your turn are about to hoard or target your position.

7. **Automated Startup Multi-Source Ingestor & Offline Mode**:
   - Runs automatically at startup (Streamlit & CLI), scanning `~/Downloads` for fresh FantasyPros exports, scraping live web tables as backup, and syncing Sleeper API injuries.
   - Includes data quality guardrails (`DataSanityGuard`) and name suffix normalization (`normalize_player_name`).
   - Supports `--offline` mode for zero-latency drafting at venues without Wi-Fi.

---

## Quick Start Instructions

### 1. Launch the Streamlit Dashboard
```bash
./venv/bin/streamlit run app.py
```
App will open automatically in your browser at `http://localhost:8501`. Startup progress streams directly to your terminal console.

### 2. Run Pre-Draft Refresh Pipeline (Live & Offline)
```bash
python refresh_draft_data.py
```
For zero-latency offline drafting:
```bash
python refresh_draft_data.py --offline
```

### 3. Run System Test Suite
```bash
python test_system.py
```

### 3. Run Full 72-Pick Mock Draft Simulation
```bash
python run_mock_draft.py
```

### 4. Run Monte Carlo High-Variance Experiment
```bash
python run_variance_simulation.py
```

---

## Projection CSV Exports
Drop any raw projection CSV files into `data/sources/`. Configure source weights in the sidebar under **⚙️ Weighted Projection Sources**.

---

## Contributions & Usage
This is a free, unlicensed personal repository built for UFL draft strategy.
- **Viewing & Forking**: Free for anyone to view, download, clone, or fork for their own fantasy football league setups.
- **Pull Requests**: External pull requests and code contributions are not being accepted at this time.

