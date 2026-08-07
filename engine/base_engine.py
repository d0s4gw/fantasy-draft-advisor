"""
Base Abstract Draft Engine Contract for UFL Fantasy Football Draft Advisor.
Defines the standard recommendation interface for all pluggable engines.
"""

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
