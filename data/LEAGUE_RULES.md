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
| Scoring Window      | Q1 — Weeks 1 through 4    |
| Waivers             | **None** (no-waiver league)|

### Governors (Draft Order)

1. Team 1 (User) *(User / Target Team)*
2. Team 2
3. Team 4
4. Team 3
5. Team 5
6. Team 6

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

### Key Scoring Insight

> Rushing and Receiving yards score at **1 pt / 5 yards (0.20 pts/yd)**, which
> is **2× the standard fantasy scoring rate** (1 pt / 10 yards). This makes
> high-volume rushers and yardage-monster receivers significantly more valuable
> than in standard leagues.

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

*Last updated: 2026-08-03 by Mike Welsh (definitive rules provided directly).*
