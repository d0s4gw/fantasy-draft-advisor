# Fantasy Football Draft Advisor 2026 — Agent & Developer Guide (`AGENTS.md`)

Welcome to the **Fantasy Football Draft Advisor 2026** codebase!
This file serves as the primary technical map and agentic context document for AI coding assistants (Antigravity, Claude, Cursor, Windsurf, Copilot) and human developers.

---

## 1. Executive Summary & League Domain

This project is a high-speed Python + Streamlit application engineered to optimize draft strategy for a **6-team, 4-quarter high-stakes fantasy football league**.

### Core League Parameters & Scoring Rules
- **League Size**: 6 Teams ("Governors"):
  1. `Team 1 (User)` (User / Target Team)
  2. `Team 2`
  3. `Team 3`
  4. `Team 4`
  5. `Team 5`
  6. `Team 6`

  > **NOTE**: The draft order above is a placeholder. Update `data/config.json`
  > (and `data/config.local.json` for real governor names) once the actual draft
  > order is determined.

- **Draft Format**: 12-Round Snake Draft (72 total picks).
- **Target Focus**: **Q1 (Weeks 1–4)** performance.
- **Canonical Rules**: See [LEAGUE_RULES.md](data/LEAGUE_RULES.md) — the single source of truth for all league rules.
- **Custom UFL Yardage Multiplier**:
  - **Rushing & Receiving**: **1 pt per 5 yards** ($0.20\text{ pts/yd}$) — **2x standard fantasy scoring**.
  - **Passing**: 1 pt per 25 yards ($0.04\text{ pts/yd}$), 4 pt Pass TD, -2 INT.
  - **Receptions**: 0.3 PPR.
  - **2-pt Conversion**: 2 pts.
  - **Fumble Lost**: 0 pts (not penalized).
  - **ST Player TD**: 6 pts (not projected by sources).
- **Starting Lineup (7 starters)**: 2 QB, 1 RB, 1 WR, 1 TE, 2 FLEX (RB/WR/TE).
- **Bench**: 5 open slots. **Total Roster**: 12 players.
- **Roster Requirements** (no-waiver league): QB ≥3, RB ≥3, WR ≥3, TE ≥2.

---

## 2. Directory & Repository Map

```
fantasy-draft-advisor/
├── AGENTS.md                         # [ROOT AGENT GUIDE] Master architectural roadmap
├── CLAUDE.md                         # Symlink / concise reference for Claude Code & Cursor
├── .cursorrules                      # Workspace instructions for Cursor IDE
├── README.md                         # Quick start documentation for human users
├── ROADMAP.md                        # Feature roadmap & deferred per-week projections plan
├── app.py                            # Primary Streamlit web application dashboard UI
├── import_fantasypros.py             # FantasyPros CSV projection converter & dataset builder
├── refresh_draft_data.py             # Live Sleeper injury tracker & source status updater (supports --offline)
├── run_mock_draft.py                 # Full 72-pick (12 round) mock draft simulation harness
├── run_variance_simulation.py        # Monte Carlo high-variance strategy stress-tester
├── test_system.py                    # Complete end-to-end unit and integration test suite
├── data/
│   ├── LEAGUE_RULES.md                # [CANONICAL] Definitive league rules — single source of truth
│   ├── AGENTS.md                     # Data directory schema & CSV mapping guide
│   ├── CLAUDE.md                     # Data quick reference
│   ├── config.json                   # League settings, governors list, roster limits
│   ├── draft_state.json              # Active draft state & pick history persistence
│   ├── sleeper_players.json          # Cached Sleeper API player mapping database
│   ├── sources.json                  # Projection source weighting and auto-fetch config
│   └── sources/                      # Raw projection CSV exports from external providers
│       ├── baseline_2026.csv
│       └── fantasypros.csv
├── engine/
│   ├── AGENTS.md                     # Engine module contracts, VORP math & War Room guide
│   ├── CLAUDE.md                     # Engine quick reference
│   ├── base_engine.py                # Abstract Base Class contract for recommendation engines
│   ├── draft_state.py                # Draft matrix tracker & snake pick state manager
│   ├── fuzzy_search.py               # Player name search & shorthand lookup engine
│   ├── joint_optimizer.py            # Knapsack portfolio, marginal gain & War Room matrix calculator
│   ├── live_math_engine.py           # Core Live Joint VORP, strategy preset & decision matrix engine
│   ├── opponent_predictor.py         # Draft board matrix analyzer & opponent target predictor
│   ├── projection_fetchers.py        # Multi-source auto-fetcher, sanity guardrails & progress manager
│   ├── projection_synth.py           # Multi-source weighted projection synthesizer
│   ├── scoring.py                    # Centralized UFL fantasy scoring formulas
│   ├── sleeper_sync.py               # Sleeper API live draft auto-polling client
│   ├── strategy_presets.py           # Dynamic macro strategy preset manager
│   └── vorp_calculator.py            # VORP baseline computation & QB squeeze alert engine
└── .agents/
    ├── AGENTS.md                     # Workspace-level agent rules
    └── skills/
        └── developing-with-streamlit/ # Streamlit skill directory
```

---

## 3. Subsystem Architecture & Data Flow

```
[Sleeper API / ~/Downloads / Web Scraper] ──► [DataSanityGuard] ──► [ProjectionSynthesizer] ──► [UFL Scoring Math]
                                                                                                    │
[Sleeper API Poller]                      ──► [DraftState Persistence] ─────────────────────────────┤
                                                                                                    ▼
                                                                                           [VORPCalculator & JointOptimizer]
                                                                                                    │
                                                                                                    ▼
                                                                               [LiveMathEngine + Strategy Presets]
                                                                                                    │
                                                                                                    ▼
                                                                               [Turn Strategy War Room Decision Matrix]
                                                                                                    │
                                                                                                    ▼
                                                                                      [Streamlit App Dashboard UI]
```

---

## 4. Key Components & Implementation Details

### A. Draft State & Persistence (`engine/draft_state.py`)
- Maintains snake pick sequence for 6 teams across 12 rounds (Picks #1 to #72).
- Automatically calculates:
  - `current_pick_info()`: Active pick number, round, slot index, governor.
  - `picks_until_my_turn()`: Number of picks remaining before user's next selection.
  - `record_pick()` / `undo_last_pick()`: Full stack-based history mutation with auto-save to `data/draft_state.json`.

### B. UFL Math & Projection Synthesizer (`engine/projection_synth.py`, `engine/scoring.py`, `engine/projection_fetchers.py`)
- **Auto-Fetch Pipeline (`FetcherManager`)**: Runs automatically at startup (Streamlit & CLI), scanning `~/Downloads` for fresh FantasyPros CSV exports, scraping live web tables as backup, and syncing Sleeper API injuries.
- **Data Quality Guardrails (`DataSanityGuard`)**: Validates row counts ($\ge 20$ players) and schemas before updating source files to prevent corrupt overwrites.
- **Name Suffix Normalization (`normalize_player_name`)**: Standardizes suffixes (`Jr.`, `III`, `II`, `Sr.`) for clean cross-source player matching.
- Normalizes column names and applies custom UFL scoring formula:
  $$\text{UFL Pts} = (\text{RushYds} + \text{RecYds}) \times 0.20 + (\text{RushTD} + \text{RecTD}) \times 6.0 + \text{PassYds} \times 0.04 + \text{PassTD} \times 4.0 - \text{INT} \times 2.0 + \text{Rec} \times 0.3 + \text{2PtConv} \times 2.0$$
- **Injury Discount Model**: Injury multiplier is applied to raw stats once (not to the final score). `touch_multiplier` overrides are applied independently after the injury discount. OUT/IR/PUP/SUS = 0×, DOUBTFUL = 0.25×, QUESTIONABLE = 0.75×.

### C. Joint Portfolio Optimizer & VORP (`engine/joint_optimizer.py`, `engine/vorp_calculator.py`)
- Computes exact **Marginal Portfolio Gain** for every available player using 4-week Knapsack solver.
- Evaluates candidate picks against the user's current roster rather than static baseline replacements.
- **Refreshed Projections**: `get_optimal_lineup_details()` and `solve_weekly_starting_lineup()` accept optional `projections_df` to use current projection values rather than stale pick-time snapshots.
- Evaluates **QB Supply Squeeze**: Flags warnings when top-tier QBs ($\ge 35.0$ UFL pts for 4-week Q1) remain $\le 3$ and user has $< 2$ QBs before an extended pick wait.

### D. Recommendation & Turn Strategy Engine (`engine/live_math_engine.py`, `engine/joint_optimizer.py`)
- **Live Math Engine (`LiveMathEngine`)**: Real-time sub-millisecond Knapsack VORP, starter standings, and opponent scarcity optimizer.
- **Strategy Presets (`strategy_presets.py`)**: Supports macro strategy overrides (*Zero-RB*, *Hero-RB*, *Robust Dual RB*, *Elite TE Anchor*, *Pure Math VORP*).
- **Dynamic AUTO Strategy**: Adapts in real-time with 5 triggers:
  1. **QB Squeeze Detection**: ≤3 top-tier QBs + <2 owned → boost 1.25×
  2. **RB Cliff Urgency**: #1 RB ≥20pts above #2 in R1-3, 0 RBs → boost 1.20×
  3. **Elite TE Window**: 1 elite TE left, 0 owned in R3-5 → boost 1.30×
  4. **Late-Round Roster Compliance**: R9+, short of roster minimums → boost 1.20×
  5. **WR Volume Loading**: R3-6, ≤1 WR → boost 1.15×
- **Turn Strategy War Room**: Fast Monte Carlo simulation matrix generating candidate survival odds, positional regret cliffs, 10th/90th percentile outcome ranges, and automated decision badges (`🚨 MUST DRAFT`, `🔥 HIGH LEVERAGE`, `⏳ CAN WAIT`, `🛡️ SAFE FLOOR`).

---

## 5. Development Workflows & Commands

### 1. Launch Main Streamlit App
```bash
streamlit run app.py
```
App will serve on `http://localhost:8501`. Automatically fetches live projections and displays terminal progress logging.

### 2. Run Pre-Draft Data Refresh Pipeline
```bash
python refresh_draft_data.py
```
To run in instant zero-latency offline mode:
```bash
python refresh_draft_data.py --offline
```

### 3. Run System Test Suite
```bash
python test_system.py
```
Validates auto-fetchers, sanity guardrails, name normalization, projection synth, draft state, VORP math, fuzzy search, and engine recommendations.

### 3. Run Full 72-Pick Mock Draft Simulation
```bash
python run_mock_draft.py
```

### 4. Run Monte Carlo High-Variance Strategy Stress-Tester
```bash
python run_variance_simulation.py
```

### 5. Import FantasyPros CSV Projections
```bash
python import_fantasypros.py
```

---

## 6. Coding Conventions & Agent Rules

1. **Streamlit UI Conventions**:
   - Do NOT use `use_container_width=True` (deprecated in newer Streamlit versions). Use `width="stretch"` or standard container layouts.
   - Use `st.session_state` carefully. Clear caches (`st.cache_data.clear()`) on draft reset or weight re-calculations.
   - On draft reset, only delete draft-related session state keys (`draft_state`, `synth`, `sleeper_sync`), not all session state.
2. **State Mutability**:
   - Always record draft picks via `DraftState.record_pick()`.
   - Never mutate `picks_history` or `rosters` directly without invoking persistence.
3. **Injury Discount Model**:
   - Apply injury multiplier to **stats** (single discount point), NOT to the final UFL score.
   - `touch_multiplier` overrides are applied independently after the injury discount.
   - Never apply both stat reduction and score reduction for the same injury.
4. **Sleeper JSON Format**:
   - `sleeper_players.json` uses structured format: `{"id_to_name": {...}, "name_to_id": {...}}`.
   - Both `SleeperAPIFetcher` and `SleeperSync` must read/write this format.
5. **File Scheme & Markdown Links**:
   - Always reference project files with Markdown links (e.g. `[app.py](app.py)`).
6. **Error Handling**:
   - Log visible warnings when enabled projection sources are missing from disk.
   - Show explicit error messages (`st.error`) when projections are empty.
   - Gracefully handle missing CSV sources or offline GCP credentials by providing fallback calculations.
