"""
Rapid Sub-Millisecond Fuzzy Player Search & Nickname Mapper.
"""

from rapidfuzz import process, fuzz
from typing import List

# Common Fantasy Football Shorthand Aliases
ALIASES = {
    "cmc": "Christian McCaffrey",
    "jj": "Justin Jefferson",
    "cd": "CeeDee Lamb",
    "chase": "Ja'Marr Chase",
    "bijan": "Bijan Robinson",
    "lamar": "Lamar Jackson",
    "allen": "Josh Allen",
    "hurts": "Jalen Hurts",
    "mahomes": "Patrick Mahomes",
    "breece": "Breece Hall",
    "saquon": "Saquon Barkley",
    "gibbs": "Jahmyr Gibbs",
    "sun god": "Amon-Ra St. Brown",
    "arsb": "Amon-Ra St. Brown",
    "mhj": "Marvin Harrison Jr.",
    "btj": "Brian Thomas Jr.",
    "puka": "Puka Nacua",
    "nico": "Nico Collins",
    "laporta": "Sam LaPorta",
    "kelce": "Travis Kelce",
    "kittle": "George Kittle",
    "mcbride": "Trey McBride"
}

class FuzzySearcher:
    def __init__(self, player_names: List[str]):
        self.player_names = player_names

    def search(self, query: str, limit: int = 5) -> List[str]:
        """
        Searches player names using exact alias matching or rapid fuzzy logic.
        """
        q = query.strip().lower()
        if not q:
            return []

        # Check direct alias dictionary match
        if q in ALIASES:
            target = ALIASES[q]
            for name in self.player_names:
                if target.lower() in name.lower():
                    return [name]

        # Rapid fuzzy matching
        results = process.extract(
            query,
            self.player_names,
            scorer=fuzz.WRatio,
            limit=limit
        )
        return [match[0] for match in results if match[1] > 50]
