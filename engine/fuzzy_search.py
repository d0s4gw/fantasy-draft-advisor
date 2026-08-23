"""
Rapid Sub-Millisecond Fuzzy Player Search & Nickname Mapper.
"""

from rapidfuzz import process, fuzz
from typing import List
from engine.projection_fetchers import normalize_player_name

# Common Fantasy Football Shorthand Aliases & Nicknames
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
    "mhj": "Marvin Harrison",
    "btj": "Brian Thomas",
    "puka": "Puka Nacua",
    "nico": "Nico Collins",
    "laporta": "Sam LaPorta",
    "kelce": "Travis Kelce",
    "kittle": "George Kittle",
    "mcbride": "Trey McBride",
    "jt": "Jonathan Taylor",
    "kw9": "Kenneth Walker",
    "k9": "Kenneth Walker",
    "etn": "Travis Etienne",
    "bowers": "Brock Bowers",
    "nabers": "Malik Nabers",
    "odunze": "Rome Odunze",
    "worthy": "Xavier Worthy",
    "mcconkey": "Ladd McConkey"
}

class FuzzySearcher:
    def __init__(self, player_names: List[str]):
        self.player_names = player_names
        self.normalized_map = {normalize_player_name(p).lower(): p for p in player_names}

    def search(self, query: str, limit: int = 5) -> List[str]:
        """
        Searches player names using exact alias matching or rapid fuzzy logic.
        """
        q = query.strip().lower()
        if not q:
            return []

        # Check direct alias dictionary match
        if q in ALIASES:
            target_norm = normalize_player_name(ALIASES[q]).lower()
            # 1. Exact match in normalized map
            if target_norm in self.normalized_map:
                return [self.normalized_map[target_norm]]
            # 2. Substring match
            for norm_name, orig_name in self.normalized_map.items():
                if target_norm in norm_name or norm_name in target_norm:
                    return [orig_name]

        # Rapid fuzzy matching
        results = process.extract(
            query,
            self.player_names,
            scorer=fuzz.WRatio,
            limit=limit
        )
        return [match[0] for match in results if match[1] > 50]

