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
- **Draft Format**: 12-Round Snake Draft (72 total picks).
- **Target Focus**: **Q1 (Weeks 1–4)** performance.
- **Canonical Rules**: See [LEAGUE_RULES.md](data/LEAGUE_RULES.md) — the single source of truth for all league rules.
- **Custom UFL Yardage Multiplier**:
  - **Rushing & Receiving**: **1 pt per 5 yards** ($0.20\text{ pts/yd}$) — **2x standard fantasy scoring**.
  - **Passing**: 1 pt per 25 yards ($0.04\text{ pts/yd}$), 4 pt Pass TD, -2 INT.
  - **Receptions**: 0.3 PPR.
  - **2-pt Conversion**: 2 pts.
- **Starting Lineup (7 starters)**: 2 QB, 1 RB, 1 WR, 1 TE, 2 FLEX (RB/WR/TE).
- **Bench**: 5 open slots. **Total Roster**: 12 players.

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
├── refresh_draft_data.py             # Live Sleeper injury tracker & source status updater
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
│   ├── sources.json                  # Projection source weighting and column mapping config
│   └── sources/                      # Raw projection CSV exports from external providers
│       ├── baseline_2026.csv
│       └── fantasypros.csv
│       ├── etr.csv
│       └── pff.csv
├── engine/
│   ├── AGENTS.md                     # Engine module contracts, VORP math & War Room guide
│   ├── CLAUDE.md                     # Engine quick reference
│   ├── base_engine.py                # Abstract Base Class contract for recommendation engines
│   ├── draft_state.py                # Draft matrix tracker & snake pick state manager
│   ├── fuzzy_search.py               # Player name search & shorthand lookup engine
│   ├── joint_optimizer.py            # Knapsack portfolio, marginal gain & War Room matrix calculator
│   ├── live_math_engine.py           # Core Live Joint VORP, strategy preset & decision matrix engine
│   ├── opponent_predictor.py         # Draft board matrix analyzer & opponent target predictor
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
[Raw CSV Projections] ──► [ProjectionSynthesizer] ──► [UFL Scoring Math]
                                                             │
[Sleeper API Poller]  ──► [DraftState Persistence] ──────────┤
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

### B. UFL Math & Projection Synthesizer (`engine/projection_synth.py`, `engine/scoring.py`)
- Reads configured projection CSV sources from `data/sources/` using rules in `data/sources.json`.
- Normalizes column names (e.g. `PassYds`, `RushYds`, `Rec`) across different provider formats.
- Applies custom UFL scoring formula:
  $$\text{UFL Pts} = (\text{RushYds} + \text{RecYds}) \times 0.20 + (\text{RushTD} + \text{RecTD}) \times 6.0 + \text{PassYds} \times 0.04 + \text{PassTD} \times 4.0 - \text{INT} \times 2.0 + \text{Rec} \times 0.3$$

### C. Joint Portfolio Optimizer & VORP (`engine/joint_optimizer.py`, `engine/vorp_calculator.py`)
- Computes exact **Marginal Portfolio Gain** for every available player using 4-week Knapsack solver.
- Evaluates candidate picks against the user's current roster rather than static baseline replacements.
- Evaluates **QB Supply Squeeze**: Flags warnings when top-tier QBs remain $\le 3$ and user has $< 2$ QBs before an extended pick wait.

### D. Recommendation & Turn Strategy Engine (`engine/live_math_engine.py`, `engine/joint_optimizer.py`)
- **Live Math Engine (`LiveMathEngine`)**: Real-time sub-millisecond Knapsack VORP, starter standings, and opponent scarcity optimizer.
- **Strategy Presets (`strategy_presets.py`)**: Supports macro strategy overrides (*Zero-QB*, *Zero-RB*, *Hero-RB*, *QB Squeeze Aggressive*, *Balanced VORP*).
- **Turn Strategy War Room**: Fast Monte Carlo simulation matrix generating candidate survival odds, positional regret cliffs, 10th/90th percentile outcome ranges, and automated decision badges (`🚨 MUST DRAFT`, `🔥 HIGH LEVERAGE`, `⏳ CAN WAIT`, `🛡️ SAFE FLOOR`).

---

## 5. Development Workflows & Commands

### 1. Launch Main Streamlit App
```bash
streamlit run app.py
```
App will serve on `http://localhost:8501`.

### 2. Run System Test Suite
```bash
python test_system.py
```
Validates projection synth, draft state, VORP math, fuzzy search, and engine recommendations.

### 3. Run Full 72-Pick Mock Draft Simulation
```bash
python run_mock_draft.py
```

### 4. Run Monte Carlo High-Variance Strategy Stress-Tester
```bash
python run_variance_simulation.py
```

### 5. Regenerate Precomputed Gameplan
```bash
python precompute_gameplan.py
```

### 6. Import Real NFL Projections
```bash
python populate_real_projections.py
```

---

## 6. Coding Conventions & Agent Rules

1. **Streamlit UI Conventions**:
   - Do NOT use `use_container_width=True` (deprecated in newer Streamlit versions). Use `width="stretch"` or standard container layouts.
   - Use `st.session_state` carefully. Clear caches (`st.cache_data.clear()`) on draft reset or weight re-calculations.
2. **State Mutability**:
   - Always record draft picks via `DraftState.record_pick()`.
   - Never mutate `picks_history` or `rosters` directly without invoking persistence.
3. **File Scheme & Markdown Links**:
   - Always reference project files with Markdown links (e.g. `[app.py](app.py)`).
4. **Error Handling**:
   - Gracefully handle missing CSV sources or offline GCP credentials by providing fallback calculations.
