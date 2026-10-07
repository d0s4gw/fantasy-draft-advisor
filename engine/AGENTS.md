# Engine Subsystem Architecture & Module Contracts (`engine/AGENTS.md`)

The `engine/` directory contains all calculation, simulation, optimization, search, and AI recommendation modules for the UFL Fantasy Football Draft Advisor.

---

## Module Index & File Responsibilities

| Module | Description | Primary Classes / Functions | Key Dependencies |
| :--- | :--- | :--- | :--- |
| [base_engine.py](base_engine.py) | Abstract interface for recommendation engines | `BaseEngine`, `EngineRecommendation` | Standard dataclasses |
| [scoring.py](scoring.py) | UFL scoring math logic | `calculate_ufl_points()` | Pandas, Numpy |
| [projection_synth.py](projection_synth.py) | Multi-source weighted projection synthesizer | `ProjectionSynthesizer` | `scoring.py`, `data/sources.json` |
| [draft_state.py](draft_state.py) | Pick history & 72-pick snake draft state | `DraftState` | `data/config.json`, `data/draft_state.json` |
| [joint_optimizer.py](joint_optimizer.py) | Knapsack optimization for portfolio VORP | `JointOptimizer` | `draft_state.py` |
| [vorp_calculator.py](vorp_calculator.py) | Dynamic portfolio VORP & QB squeeze solver | `VORPCalculator` | `joint_optimizer.py` |
| [opponent_predictor.py](opponent_predictor.py) | Draft board analysis & opponent steal prediction | `OpponentPredictor` | `draft_state.py` |
| [projection_fetchers.py](projection_fetchers.py) | Multi-source auto-fetcher, sanity guardrails & progress manager | `FetcherManager`, `BaseFetcher`, `DataSanityGuard` | Requests, BeautifulSoup, `data/sources.json` |
| [fuzzy_search.py](fuzzy_search.py) | Rapid shorthand & fuzzy player search | `FuzzySearcher` | Difflib |
| [sleeper_sync.py](sleeper_sync.py) | Sleeper API live draft polling & auto-sync | `SleeperSync` | Requests, `data/sleeper_players.json` |
| [strategy_presets.py](strategy_presets.py) | Dynamic & adaptive macro strategy presets | `StrategyPresetManager`, `STRATEGY_PRESETS` | Pandas (for AUTO triggers) |
| [live_math_engine.py](live_math_engine.py) | Core live Joint VORP, strategy preset & decision matrix engine | `LiveMathEngine` | `base_engine.py`, `vorp_calculator.py` |

---

## 1. Abstract Engine Contract (`engine/base_engine.py`)

All recommendation engines inherit from `DraftEngineBase`:

```python
from abc import ABC, abstractmethod
import pandas as pd
from typing import Dict, Any

class DraftEngineBase(ABC):
    @abstractmethod
    def recommend(self, projections_df: pd.DataFrame, draft_state) -> Dict[str, Any]:
        """
        Returns standardized recommendation dictionary:
        {
          "top_qbs": list of player dicts (top 5),
          "top_rbs": list of player dicts (top 5),
          "top_wrs": list of player dicts (top 5),
          "top_tes": list of player dicts (top 5),
          "best_decision": player dict,
          "advice_text": str,
          "engine_name": str
        }
        """
        pass
```

---

## 2. UFL Scoring Math & Projection Synthesizer (`engine/scoring.py`, `engine/projection_synth.py`)

UFL scoring gives **double weight** to rushing and receiving yards:

$$\text{Rush Pts} = \text{RushYds} \times 0.20 + \text{RushTD} \times 6.0$$
$$\text{Rec Pts} = \text{RecYds} \times 0.20 + \text{RecTD} \times 6.0 + \text{Rec} \times 0.30$$
$$\text{Pass Pts} = \text{PassYds} \times 0.04 + \text{PassTD} \times 4.0 - \text{INT} \times 2.0$$

The `ProjectionSynthesizer`:
1. Loads active CSV sources configured in `data/sources.json`.
2. Computes weighted average per-game stats based on `weight` attribute.
3. Scales stats to 4-week totals ($\times 4$) for Q1 targeting.
4. Applies injury multiplier to stats once (not to final score). Games-based return discount scale: 3 games = 0.75×, 2 games = 0.50×, 1 game = 0.25×, 0 games = 0.0× (IR/PUP/SUS = 0.0×, single-game OUT = 0.75×, QUESTIONABLE = 0.75×). Overrides support `expected_games` or `return_week` with per-week missed zeroing.
5. Applies `touch_multiplier` overrides independently after injury discount.
6. Generates `ufl_pts` per player from discounted stats.

> **Important**: Fumble Lost is NOT penalized (0 pts). ST Player TDs (6 pts) are in the league but not projected.

---

## 3. Draft Matrix & State Tracking (`engine/draft_state.py`)

`DraftState` manages a 6-team 12-round snake draft matrix:
- **Team Slots**: 6 Governors indexed 0 through 5.
- **Snake Pattern**:
  - Odd rounds (1, 3, 5, 7, 9, 11): 0 ➔ 1 ➔ 2 ➔ 3 ➔ 4 ➔ 5
  - Even rounds (2, 4, 6, 8, 10, 12): 5 ➔ 4 ➔ 3 ➔ 2 ➔ 1 ➔ 0
- **Pick Recording**:
  - `record_pick(player_name, position, team, ufl_pts, governor=None)`
  - Automatically updates roster arrays, appends pick history, saves to `data/draft_state.json`.
  - `undo_last_pick()` pops from stack, removes only the **last** matching entry from the governor's roster, and restores state.

---

## 4. Optimization Engine (`engine/joint_optimizer.py`, `engine/vorp_calculator.py`)

Instead of static positional baseline replacements, `JointOptimizer` uses a 4-week Knapsack solver:
1. Calculates user's baseline optimal starting lineup score from currently drafted players.
2. For each available candidate player:
   - Temporarily inserts player into roster.
   - Re-runs Knapsack lineup solver to find best 7 starters (2 QB, 1 RB, 1 WR, 1 TE, 2 FLEX).
   - `marginal_gain` = New Optimal Score - Baseline Score.
3. Ranks available players by `marginal_gain` (VORP).
4. **Refreshed Projections**: Both `get_optimal_lineup_details()` and `solve_weekly_starting_lineup()` accept optional `projections_df` to refresh stale pick-time `ufl_pts` with current projection values.

> **Note**: See [LEAGUE_RULES.md](../data/LEAGUE_RULES.md) for the canonical starting lineup configuration.

---

## 5. Strategy Presets & Dynamic AUTO (`engine/strategy_presets.py`)

`StrategyPresetManager.get_positional_multiplier()` returns scaling multipliers (0.7–1.35) based on the active macro strategy:

- **PURE_VORP**: Always returns 1.0 (no adjustment).
- **HERO_RB / ZERO_RB / ROBUST_RB / ELITE_TE**: Static multipliers based on round and roster composition.
- **AUTO** (Dynamic): Adapts in real-time using 5 triggers:
  1. **QB Squeeze Detection**: ≤3 top-tier QBs (≥35 UFL pts) + <2 owned → QB boost 1.25×
  2. **RB Cliff Urgency**: #1 available RB ≥20pts above #2 in R1-3 + 0 RBs → RB boost 1.20×
  3. **Elite TE Window**: 1 elite TE (≥50 UFL pts) left + 0 owned in R3-5 → TE boost 1.30×
  4. **Late-Round Roster Compliance**: R9+ + short of roster minimums → position boost 1.20×
  5. **WR Volume Loading**: R3-6 + ≤1 WR → WR boost 1.15×

AUTO requires `undrafted_df` parameter for tier-aware decisions. All manual strategies remain available in the UI.

---

## 6. Opponent Threat Matrix (`engine/opponent_predictor.py`)

`OpponentPredictor` analyzes Governors picking before user's next turn:
- Inspects positional needs of intermediate Governors.
- Flags high risk of positional runs (e.g. QB/TE hoards).
- Computes `steal_threat_score` per position.

---

## 7. Sleeper Integration (`engine/sleeper_sync.py`, `engine/projection_fetchers.py`)

- `sleeper_players.json` uses structured format: `{"id_to_name": {...}, "name_to_id": {...}}`.
- `SleeperAPIFetcher` writes this structured format (converting from raw API response).
- `SleeperSync._load_player_map()` handles both structured and raw formats (auto-converts raw on read).

---

## 8. Development Rules for Engine Code

1. **No Ad-Hoc Multipliers**: Keep scoring math strictly tied to `engine/scoring.py`.
2. **Immutability**: Avoid modifying DataFrame inputs in-place without `.copy()`.
3. **Engine Interface Compliance**: Always return `EngineRecommendation` instances from `recommend()`.
4. **Injury Discount**: Apply injury multiplier to **stats only**, never to the final UFL score.
5. **Missing Sources**: Log visible `⚠️ WARNING` when enabled sources are not found on disk.
