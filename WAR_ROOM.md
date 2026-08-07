# ⚔️ Turn Strategy Matrix ("War Room") — Architectural Plan & Roadmap (`WAR_ROOM.md`)

This document outlines the complete technical blueprint and step-by-step implementation guide for the **Turn Strategy Matrix ("War Room")** feature in the **Fantasy Football Draft Advisor 2026**.

---

## 1. Strategic Goal & Domain Context

- **League Domain**: 6 Teams, 12-round snake draft (72 picks).
- **Lineup**: 2 QB, 1 RB, 1 WR, 1 TE, 2 FLEX (RB/WR/TE), 5 Bench.
- **Target Focus**: Q1 (Weeks 1–4) performance under custom scoring (Rush/Rec: 1pt per 5 yds = 0.20 pts/yd).
- **Core Objective**: Replace single-point VORP recommendation certainty with a **game-theoretic Decision Matrix**. When on the clock, the user can see top options, survival odds across opponent picks, positional regret cliffs, back-to-back turn pairings, and 10% floor / 90% ceiling simulation ranges.

---

## 2. The 4 Architecture Pillars

```
                        ┌──────────────────────────────────────────────┐
                        │          WAR ROOM DECISION MATRIX            │
                        └──────────────────────┬───────────────────────┘
                                               │
       ┌───────────────────────┬───────────────┴───────────────┬───────────────────────┐
       ▼                       ▼                               ▼                       ▼
┌──────────────┐       ┌──────────────┐                ┌──────────────┐        ┌──────────────┐
│ CANDIDATE    │       │ SNAKE TURN   │                │ SURVIVAL &   │        │ EXECUTIVE    │
│ SELECTION    │       │ PAIRING      │                │ REGRET CLIFF │        │ TRADE-OFF    │
│ (Pos Diversity)      │ (Back-to-Back)                │ (Monte Carlo)│        │ SUMMARY CARD │
└──────────────┘       └──────────────┘                └──────────────┘        └──────────────┘
```

### Pillar 1: Candidate Selection with Positional Diversity
Rather than sampling top VORP gainers overall (which could yield 5 RBs and 3 WRs), candidate selection guarantees positional coverage:
- Top 2 QBs, Top 2 RBs, Top 2 WRs, Top 2 TEs (8 players) + Top 2 Overall Net Portfolio Gainers.
- Total Candidate Pool: **10 Players**.

### Pillar 2: Snake Turn Structure Detection
Detects the exact pick distance until the user's *next* turn (`picks_until_next`):
- **Back-to-Back Turn (`picks_until_next <= 1`)**: Occurs at Pick #12/#13 or #6/#7. Survival odds between picks is 100%. Switches to **Turn Pair Combination Optimization** (evaluates 2-player combination starter scores).
- **Long Turn Gap (`picks_until_next > 1`)**: Runs Monte Carlo simulations on opponent pick choices (Team 2, Team 3, Team 4, etc.) before user's next pick turn.

### Pillar 3: Fast Vectorized Monte Carlo Simulation Engine
Runs 60 vectorized opponent draft simulations in $< 250\text{ ms}$:
1. **Survival Probability ($S_i$)**: % of simulations where candidate $C_i$ is still undrafted at user's next turn.
2. **Positional Regret Cliff ($\Delta_i$)**: Point drop-off if user skips position $P$ at current turn and is forced to pick replacement at next turn.
   $$\text{Regret Cliff} = \text{Pts}(\text{Candidate}_i) - \text{Pts}(\text{Best Replacement at Next Turn})$$
3. **10th% Floor & 90th% Ceiling**: Final 7-starter portfolio scores across stochastic outcomes.

### Pillar 4: Action Badges & Executive Dilemma Card
Assigns automated decision badges to candidates:
- `🚨 MUST DRAFT`: Critical position cliff (e.g. QB collapse) + Survival $< 15\%$.
- `🔥 HIGH LEVERAGE`: Top net portfolio gain + Survival $< 30\%$.
- `⏳ CAN WAIT`: High value player + Survival $> 70\%$ (safe to pick on turn).
- `🛡️ SAFE FLOOR`: High floor projection + minimal regret.
- `⚠️ HIGH RISK`: Low survival odds + high variance.

---

## 3. UI Blueprint (`app.py`)

When the user clicks **⚡ Turn Strategy War Room** (or automatically when active turn = Mike Welsh), the dashboard renders:

1. **Executive Head-to-Head Dilemma Card**:
   > **The Big Choice**: **Josh Allen (QB)** vs **Derrick Henry (RB)**
   > *"Drafting Allen over Henry costs -3.3 Net Pts today, BUT protects against a -38.5 Pt QB Cliff at Pick #36."*

2. **Interactive Decision Matrix Table**:

| Candidate | Pos | Base UFL Pts | Net Gain | Survival Odds | Regret Cliff | 10% Floor | 90% Ceiling | Strategic Action |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Josh Allen** | QB | 145.2 | **+78.4** | **0.0% (GONE)** | **-38.5 Pts** | 662 Pts | 712 Pts | 🚨 **MUST DRAFT NOW** |
| **Derrick Henry** | RB | 132.0 | **+75.1** | **12.4% (RISKY)** | **-22.1 Pts** | 654 Pts | 708 Pts | 🔥 **HIGH LEVERAGE** |
| **Ja'Marr Chase** | WR | 128.5 | **+71.0** | **84.2% (SAFE)** | **-6.2 Pts** | 658 Pts | 699 Pts | ⏳ **CAN WAIT TO TURN** |
| **Trey McBride** | TE | 105.0 | **+58.2** | **94.0% (SAFE)** | **-3.1 Pts** | 642 Pts | 685 Pts | 🛡️ **SAFE FLOOR** |

3. **Pairwise Delta Explorer**:
   Dropdown selector allowing side-by-side comparison of any two candidates with exact metric deltas.

---

## 4. Step-by-Step Implementation Roadmap

When resuming implementation:

### Step 1: Engine Implementation
- Update [`engine/joint_optimizer.py`](engine/joint_optimizer.py):
  - Implement `compute_turn_decision_matrix(draft_state, projections_df, candidate_limit=10, num_sims=60, macro_strategy="AUTO")`.
- Update [`engine/live_math_engine.py`](engine/live_math_engine.py):
  - Expose decision matrix result dictionary inside `recommend_from_vorp()`.

### Step 2: Streamlit Dashboard UI
- Update [`app.py`](app.py):
  - Add **⚡ Turn Strategy War Room** container into the recommendation view.
  - Add Executive Dilemma Card, Decision Matrix Dataframe/Table, and Pairwise Delta Explorer.

### Step 3: Test Suite & Validation
- Update [`test_system.py`](test_system.py):
  - Add `test_turn_decision_matrix()` verifying positional coverage, survival odds accuracy, regret cliff calculation, and execution speed ($< 300\text{ ms}$).
- Run automated verification:
  ```bash
  python test_system.py
  python run_mock_draft.py
  ```

---
*Created for UFL Fantasy Football Draft Advisor 2026.*
