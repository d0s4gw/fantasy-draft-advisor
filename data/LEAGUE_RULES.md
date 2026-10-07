# Fantasy Football League Rules — DEFINITIVE CANONICAL SOURCE

> **THIS IS THE SINGLE SOURCE OF TRUTH FOR ALL LEAGUE RULES.**
>
> All code (`config.json`, `scoring.py`, `joint_optimizer.py`), documentation
> (`AGENTS.md`, `engine/AGENTS.md`), and AI agent context files MUST match
> the rules defined in this document. If there is ever a conflict, **this file wins**.

---

## League Structure

| Parameter           | Value                      |
| :------------------ | :------------------------- |
| League Name         | Fantasy Football League    |
| Teams               | 6 ("Governors")            |
| Draft Format        | 12-Round Snake Draft       |
| Total Picks         | 72                         |
| Scoring Window      | Q2 — Weeks 5 through 8    |
| Waivers             | **None** (no-waiver league)|

### Governors (Draft Order)

1. Team 1 (Pick 1)
2. Team 2 (Pick 2)
3. Team 3 (Pick 3)
4. Team 4 (Pick 4)
5. Team 5 (Pick 5)
6. Team 6 (User) *(Pick 6 / Turn Slot — Target Team)*

> **NOTE**: Real governor names are kept private in `data/config.local.json` (gitignored).
> Never commit real personal names to git-tracked files.

---

## Starting Lineup (7 Starters)

| Slot   | Position         | Count |
| :----- | :--------------- | :---- |
| QB     | Quarterback      | 2     |
| RB     | Running Back     | 1     |
| WR     | Wide Receiver    | 1     |
| TE     | Tight End        | 1     |
| FLEX   | RB / WR / TE     | 2     |
| **Total Starters** |        | **7** |

## Bench

| Slot   | Description      | Count |
| :----- | :--------------- | :---- |
| BENCH  | Open (any position) | 5  |

## Full Roster

| Category | Count |
| :------- | :---- |
| Starters | 7     |
| Bench    | 5     |
| **Total Roster** | **12** |

---

## Scoring Rules

### Passing

| Category              | Points           |
| :-------------------- | :--------------- |
| Passing Yards         | 1 pt / 25 yards  |
| Passing Touchdown     | 4 pts            |
| Interception          | −2 pts           |

### Rushing

| Category              | Points           |
| :-------------------- | :--------------- |
| Rushing Yards         | 1 pt / 5 yards   |
| Rushing Touchdown     | 6 pts            |

### Receiving

| Category              | Points           |
| :-------------------- | :--------------- |
| Reception             | 0.3 pts (PPR)    |
| Receiving Yards       | 1 pt / 5 yards   |
| Receiving Touchdown   | 6 pts            |

### Special

| Category              | Points           |
| :-------------------- | :--------------- |
| 2-Point Conversion    | 2 pts            |

### Not Penalized

| Category              | Points           |
| :-------------------- | :--------------- |
| Fumble Lost           | 0 pts (no penalty) |

### Special Teams

| Category              | Points           |
| :-------------------- | :--------------- |
| ST Player TD          | 6 pts            |

> **NOTE**: Special Teams Player TDs (kick/punt return TDs) score 6 pts but are
> not projected by standard fantasy projection sources. The scoring engine does
> not include them in automated projections.

### Key Scoring Insight

> Rushing and Receiving yards score at **1 pt / 5 yards (0.20 pts/yd)**, which
> is **2× the standard fantasy scoring rate** (1 pt / 10 yards). This makes
> high-volume rushers and yardage-monster receivers significantly more valuable
> than in standard leagues.

---

## Bye Weeks (Q2 Handling)

- Each NFL team has exactly one bye week during the season (Weeks 5–14).
- Players score **0 pts** in their team's bye week. The optimizer automatically benches
  them and starts the best available bench replacement that week.
- The 2026 bye week schedule is in `data/bye_weeks.json` (single source of truth).
- **Q2 bye weeks (byes that fall within Weeks 5–8)**:
  - **Week 5**: Carolina Panthers (CAR), Kansas City Chiefs (KC)
  - **Week 6**: Cincinnati Bengals (CIN), Detroit Lions (DET), Miami Dolphins (MIA), Minnesota Vikings (MIN)
  - **Week 7**: Buffalo Bills (BUF), Jacksonville Jaguars (JAX), Los Angeles Chargers (LAC), Washington Commanders (WAS)
  - **Week 8**: Houston Texans (HOU), New Orleans Saints (NO), New York Giants (NYG), San Francisco 49ers (SF)
- Teams with byes in Weeks 9–14 are **unaffected** during Q2 scoring (play all 4 weeks).

---

## UFL Points Formula

```
UFL Pts = PassYds / 25
        + PassTD × 4
        + INT × (−2)
        + RushYds / 5
        + RushTD × 6
        + Receptions × 0.3
        + RecYds / 5
        + RecTD × 6
        + 2PtConv × 2
```

---

## `config.json` Mapping Reference

The values in `data/config.json` must match the rules above:

```json
{
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
  }
}
```

---

*Last updated: 2026-08-03 (definitive rules provided directly).*
