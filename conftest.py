"""
Shared pytest fixtures for Fantasy Draft Advisor test suite.
Uses tmp_path for draft state isolation so tests don't mutate real data/draft_state.json.
"""

import os
import json
import shutil
import pytest
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")


@pytest.fixture
def data_dir():
    """Returns the real data directory path."""
    return DATA_DIR


@pytest.fixture
def config_path():
    """Returns the real config.json path."""
    return CONFIG_PATH


@pytest.fixture
def draft_state(tmp_path):
    """Creates an isolated DraftState using tmp_path for state persistence."""
    from engine.draft_state import DraftState
    state_path = str(tmp_path / "draft_state.json")
    ds = DraftState(CONFIG_PATH, state_path)
    ds.reset_draft()
    return ds


@pytest.fixture
def synth():
    """Creates a ProjectionSynthesizer pointed at real data."""
    from engine.projection_synth import ProjectionSynthesizer
    return ProjectionSynthesizer(DATA_DIR)


@pytest.fixture
def projections_df(synth):
    """Returns synthesized projections DataFrame."""
    df = synth.synthesize()
    assert not df.empty, "Projections DataFrame should not be empty"
    return df
