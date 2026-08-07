# Engine Module — Quick Reference (`engine/CLAUDE.md`)

Subsystem guide for `engine/` modules. For full details, see [engine/AGENTS.md](AGENTS.md).

## Key Classes

- `DraftState` (`draft_state.py`): Snake draft matrix manager & json state sync.
- `ProjectionSynthesizer` (`projection_synth.py`): Multi-source weighted projections.
- `JointOptimizer` (`joint_optimizer.py`): Knapsack lineup gain solver.
- `VORPCalculator` (`vorp_calculator.py`): Dynamic VORP & QB squeeze evaluator.
- `LiveMathEngine` (`live_math_engine.py`): Live Knapsack VORP, strategy presets & decision matrix engine.

## Guidelines

- All engines must inherit from `BaseEngine` (`base_engine.py`).
- Always calculate UFL scoring using `calculate_ufl_points` in `scoring.py`.
- Run tests via `python test_system.py` after editing engine logic.
