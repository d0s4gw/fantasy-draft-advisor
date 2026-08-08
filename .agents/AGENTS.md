# Workspace Agent Rules — Fantasy Draft Advisor

These guidelines apply specifically to AI coding agents operating in this workspace (`fantasy-draft-advisor`).

## Core Responsibilities & Workflow Rules

1. **Always Verify Projections Math**:
   - Any changes to scoring rules must update `engine/scoring.py` and `engine/projection_synth.py` simultaneously.
   - Run `python test_system.py` after editing engine modules.

2. **Streamlit Component Best Practices**:
   - Do not add `use_container_width=True` to buttons or inputs (deprecated).
   - Use `st.session_state` keys consistently across reruns.
   - On draft reset, only delete draft-related session state keys (`draft_state`, `synth`, `sleeper_sync`), not all session state.
   - For UI changes, verify using `streamlit run app.py` or inspect layout structure.

3. **Multi-Engine Consistency**:
   - Maintain the `BaseEngine` interface (`engine/base_engine.py`) across all engines:
     - `PrecomputedEngine`
     - `LiveMathEngine`
     - `LiveAIEngine`
   - Ensure all engines return valid `EngineRecommendation` objects containing `top_pick`, `recommended_players`, and `reasoning`.

4. **Injury Discount Model**:
   - Apply injury multiplier to **stats** (single discount point), NOT to the final UFL score.
   - `touch_multiplier` overrides are applied independently after the injury discount.
   - Never apply both stat reduction and score reduction for the same injury.

5. **Sleeper JSON Format**:
   - `sleeper_players.json` uses structured format: `{"id_to_name": {...}, "name_to_id": {...}}`.
   - Both `SleeperAPIFetcher` and `SleeperSync` must read/write this format.

6. **Sleeper Sync Handling**:
   - Handle Sleeper API rate limits gracefully in `engine/sleeper_sync.py`.
   - Always run name normalization / fuzzy matching when syncing live picks.

7. **Error & Warning Handling**:
   - Log visible `⚠️ WARNING` when enabled projection sources are missing from disk.
   - Show explicit `st.error` messages when projections DataFrame is empty.
   - Gracefully handle missing CSV sources or offline credentials with fallback calculations.
