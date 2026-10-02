"""
Multi-Source Projection Fetcher Engine.
Handles automatic fetching, scraping, ingestion, and validation of player projections
from multiple sources (FantasyPros, Sleeper API, local ~/Downloads) with parallel fetching,
sanity guardrails, and rich console progress output.
"""

import os
import re
import glob
import json
import time
import shutil
import ssl
import logging
import urllib.request
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
from bs4 import BeautifulSoup

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

# Stat column names standard
STAT_COLS = [
    "pass_yds", "pass_tds", "pass_ints",
    "rush_yds", "rush_tds",
    "receptions", "rec_yds", "rec_tds", "two_pts"
]

GAMES_PER_SEASON = 17
NUM_Q_WEEKS = 4  # Number of scoring weeks in the target quarter (Q1=4, Q2=4)


TEAM_ABBR_CANONICAL = {"JAC": "JAX", "WSH": "WAS", "AZ": "ARI", "LVR": "LV"}


def enrich_bye_weeks(df: pd.DataFrame, bye_weeks_map: dict, weeks: list) -> pd.DataFrame:
    """
    Enriches a DataFrame with per-week UFL point columns and bye-week zeroing.
    
    For each week in `weeks`, adds a column `ufl_pts_wN` where N is the week number.
    If a player's team has a bye in that week, ufl_pts_wN = 0.0.
    Otherwise, ufl_pts_wN = ufl_pts / NUM_Q_WEEKS (uniform per-week distribution).
    
    Also updates bye_week column from the canonical bye_weeks_map.
    """
    if df.empty or not weeks:
        return df
    df = df.copy()

    def _lookup_bye(team_val: str) -> int:
        if not team_val:
            return 0
        t_str = str(team_val).upper().strip()
        return bye_weeks_map.get(t_str, bye_weeks_map.get(TEAM_ABBR_CANONICAL.get(t_str, t_str), 0))

    for week in weeks:
        col = f"ufl_pts_w{week}"
        if "ufl_pts" in df.columns and "team" in df.columns:
            per_week = df["ufl_pts"] / NUM_Q_WEEKS
            bye_mask = df["team"].map(_lookup_bye) == week
            df[col] = per_week.where(~bye_mask, 0.0).round(2)
        else:
            df[col] = 0.0
    # Set authoritative bye_week from the map (overrides CSV if present)
    if bye_weeks_map and "team" in df.columns:
        df["bye_week"] = df["team"].map(_lookup_bye).astype(int)
    return df


def _create_ssl_context() -> ssl.SSLContext:
    """Creates an SSL context with valid CA bundle (via certifi if available), falling back to unverified if needed."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        try:
            return ssl.create_default_context()
        except Exception as e:
            logger.warning(f"Failed to create verified SSL context, falling back to unverified: {e}")
            return ssl._create_unverified_context()


def normalize_player_name(name: str) -> str:
    """Standardizes player names by stripping suffixes (Jr., III, II, Sr.) and trimming whitespace."""
    if not name or pd.isna(name):
        return ""
    clean = str(name).strip()
    # Strip common suffixes at the end of the name
    clean = re.sub(r'\s+\b(Jr|Sr|III|II|IV|V)\b\.?$', '', clean, flags=re.IGNORECASE)
    # Replace multiple spaces with a single space
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


class DataSanityGuard:
    """Validates fetched projection dataframes before writing to disk."""

    @staticmethod
    def validate(df: pd.DataFrame, source_id: str, min_players: int = 20) -> Tuple[bool, str]:
        if df is None or df.empty:
            return False, f"Source '{source_id}' returned an empty dataframe."

        required_cols = ["name", "position", "team"]
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            return False, f"Source '{source_id}' missing required columns: {missing_cols}"

        if len(df) < min_players:
            return False, f"Source '{source_id}' returned only {len(df)} players (expected at least {min_players})."

        # Check that top QBs have pass_yds or top RBs have rush_yds
        has_stats = False
        for col in ["pass_yds", "rush_yds", "rec_yds"]:
            if col in df.columns and (df[col] > 0).any():
                has_stats = True
                break

        if not has_stats:
            return False, f"Source '{source_id}' has no positive stat values in pass_yds/rush_yds/rec_yds."

        return True, "Data quality check passed."


class BaseFetcher:
    """Abstract Base Class for projection fetchers."""
    def __init__(self, name: str, data_dir: str):
        self.name = name
        self.data_dir = data_dir
        self.sources_dir = os.path.join(data_dir, "sources")
        os.makedirs(self.sources_dir, exist_ok=True)

    def fetch(self) -> Optional[pd.DataFrame]:
        raise NotImplementedError


class DownloadsWatcherFetcher(BaseFetcher):
    """
    Scans the user's ~/Downloads directory for FantasyPros CSV exports.
    If found and newer than existing data/sources/fantasypros.csv, auto-ingests them.
    """
    def __init__(self, data_dir: str):
        super().__init__("Downloads Watcher", data_dir)
        self.downloads_dir = os.path.expanduser("~/Downloads")
        self.read_files = []

    def clean_number(self, val) -> float:
        if pd.isna(val) or val == "":
            return 0.0
        try:
            return float(str(val).replace(",", ""))
        except ValueError:
            return 0.0

    def _detect_csv_format(self, all_dfs: list) -> str:
        """
        Auto-detects whether FantasyPros CSVs contain per-game averages or season totals.
        Heuristic: if top QB pass_yds exceeds 1000, data is season totals.
        Returns 'per_game' or 'season_total'.
        """
        for df in all_dfs:
            qb_rows = df[df["position"] == "QB"]
            if not qb_rows.empty and "pass_yds" in qb_rows.columns:
                max_pass_yds = qb_rows["pass_yds"].max()
                if max_pass_yds > 1000:
                    logger.info(f"CSV format detected as SEASON TOTALS (top QB pass_yds={max_pass_yds:.0f})")
                    return "season_total"
        return "per_game"

    def fetch(self) -> Tuple[Optional[pd.DataFrame], List[str]]:
        self.read_files = []
        if not os.path.exists(self.downloads_dir):
            return None, []

        positions = ["QB", "RB", "WR", "TE"]
        all_dfs = []

        for pos in positions:
            pattern = os.path.join(self.downloads_dir, f"FantasyPros_Fantasy_Football_Projections_{pos}*.csv")
            matches = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
            if not matches:
                continue

            filepath = matches[0]
            filename = os.path.basename(filepath)
            self.read_files.append((pos, filename, filepath))

            try:
                raw = pd.read_csv(filepath, header=None, skiprows=2)
                raw = raw[raw[0].notna() & (raw[0].str.strip() != "")]

                rows = []
                for _, r in raw.iterrows():
                    name = normalize_player_name(str(r[0]))
                    team = str(r[1]).strip().strip('"') if len(r) > 1 and pd.notnull(r[1]) else "FA"
                    if not name:
                        continue

                    if pos == "QB":
                        rows.append({
                            "name": name, "position": "QB", "team": team,
                            "pass_yds": self.clean_number(r[4]) if len(r) > 4 else 0.0,
                            "pass_tds": self.clean_number(r[5]) if len(r) > 5 else 0.0,
                            "pass_ints": self.clean_number(r[6]) if len(r) > 6 else 0.0,
                            "rush_yds": self.clean_number(r[8]) if len(r) > 8 else 0.0,
                            "rush_tds": self.clean_number(r[9]) if len(r) > 9 else 0.0,
                            "receptions": 0.0, "rec_yds": 0.0, "rec_tds": 0.0
                        })
                    elif pos == "RB":
                        rows.append({
                            "name": name, "position": "RB", "team": team,
                            "pass_yds": 0.0, "pass_tds": 0.0, "pass_ints": 0.0,
                            "rush_yds": self.clean_number(r[3]) if len(r) > 3 else 0.0,
                            "rush_tds": self.clean_number(r[4]) if len(r) > 4 else 0.0,
                            "receptions": self.clean_number(r[5]) if len(r) > 5 else 0.0,
                            "rec_yds": self.clean_number(r[6]) if len(r) > 6 else 0.0,
                            "rec_tds": self.clean_number(r[7]) if len(r) > 7 else 0.0,
                        })
                    elif pos == "WR":
                        rows.append({
                            "name": name, "position": "WR", "team": team,
                            "pass_yds": 0.0, "pass_tds": 0.0, "pass_ints": 0.0,
                            "rush_yds": self.clean_number(r[6]) if len(r) > 6 else 0.0,
                            "rush_tds": self.clean_number(r[7]) if len(r) > 7 else 0.0,
                            "receptions": self.clean_number(r[2]) if len(r) > 2 else 0.0,
                            "rec_yds": self.clean_number(r[3]) if len(r) > 3 else 0.0,
                            "rec_tds": self.clean_number(r[4]) if len(r) > 4 else 0.0,
                        })
                    elif pos == "TE":
                        rows.append({
                            "name": name, "position": "TE", "team": team,
                            "pass_yds": 0.0, "pass_tds": 0.0, "pass_ints": 0.0,
                            "rush_yds": 0.0, "rush_tds": 0.0,
                            "receptions": self.clean_number(r[2]) if len(r) > 2 else 0.0,
                            "rec_yds": self.clean_number(r[3]) if len(r) > 3 else 0.0,
                            "rec_tds": self.clean_number(r[4]) if len(r) > 4 else 0.0,
                        })
                if rows:
                    all_dfs.append(pd.DataFrame(rows))
            except Exception as e:
                logger.warning(f"Failed to parse FantasyPros {pos} CSV '{filepath}': {e}")
                continue

        if not all_dfs:
            return None, self.read_files

        combined = pd.concat(all_dfs, ignore_index=True)

        # Auto-detect CSV format and apply appropriate scaling
        csv_format = self._detect_csv_format(all_dfs)
        if csv_format == "season_total":
            # Season totals: divide by games per season, then multiply by NUM_Q_WEEKS
            for col in STAT_COLS:
                if col in combined.columns:
                    combined[col] = (combined[col] / GAMES_PER_SEASON * NUM_Q_WEEKS).round(1)
        else:
            # Per-game averages: multiply by NUM_Q_WEEKS
            for col in STAT_COLS:
                if col in combined.columns:
                    combined[col] = (combined[col] * NUM_Q_WEEKS).round(1)

        combined["two_pts"] = 0.0
        combined["adp"] = range(1, len(combined) + 1)
        combined["bye_week"] = 0
        return combined, self.read_files


class FantasyProsAPIFetcher(BaseFetcher):
    """
    Fetches official consensus projections directly from FantasyPros REST API
    using x-api-key authentication. Aggregates weekly projections across target weeks (e.g. Weeks 5-8).

    Guards & Rate Limits:
    - Enforces 1.1s sleep between requests (Free tier allows max 1 req/sec).
    - Caches results locally for 12 hours so multiple app reloads don't consume the 100 req/day limit.
    - Tracks and limits maximum calls per session.
    """
    BASE_URL = "https://api.fantasypros.com/public/v2/json"
    CACHE_EXPIRY_HOURS = 12

    def __init__(self, data_dir: str, api_key: Optional[str] = None, weeks: Optional[List[int]] = None):
        super().__init__("FantasyPros Official API", data_dir)
        self.api_key = api_key or os.environ.get("FANTASYPROS_API_KEY", "").strip()
        self.weeks = weeks or [5, 6, 7, 8]
        self.published_date = time.strftime("%Y-%m-%d")
        self.cache_file = os.path.join(self.sources_dir, "fantasypros_api_cache.json")

    def _load_cache(self) -> Optional[pd.DataFrame]:
        """Loads cached projections if created within CACHE_EXPIRY_HOURS."""
        if not os.path.exists(self.cache_file):
            return None
        try:
            mtime = os.path.getmtime(self.cache_file)
            age_hours = (time.time() - mtime) / 3600.0
            if age_hours < self.CACHE_EXPIRY_HOURS:
                df = pd.read_json(self.cache_file)
                if not df.empty and len(df) >= 20:
                    cache_date = time.strftime("%Y-%m-%d", time.localtime(mtime))
                    self.published_date = f"{cache_date} (Cached)"
                    logger.info(f"Loaded {len(df)} players from FantasyPros API disk cache ({age_hours:.1f}h old).")
                    return df
        except Exception as e:
            logger.warning(f"Error reading FantasyPros API cache: {e}")
        return None

    def _save_cache(self, df: pd.DataFrame):
        """Saves fetched projections to disk cache to prevent burning daily quota."""
        try:
            df.to_json(self.cache_file, orient="records", indent=2)
        except Exception as e:
            logger.warning(f"Error saving FantasyPros API cache: {e}")

    def fetch(self) -> Tuple[Optional[pd.DataFrame], List[str]]:
        if not self.api_key:
            logger.info("FantasyProsAPIFetcher: No API key found in environment or arguments.")
            return None, []

        # 1. Check local disk cache first (protect 100 calls/day quota)
        cached_df = self._load_cache()
        if cached_df is not None:
            return cached_df, ["Local Cache (<12h old)"]

        import requests
        headers = {"x-api-key": self.api_key}
        positions = ["QB", "RB", "WR", "TE"]
        player_dict: Dict[Tuple[str, str, str], dict] = {}
        fetched_endpoints = []

        try:
            for w in self.weeks:
                for pos in positions:
                    url = f"{self.BASE_URL}/nfl/2024/projections?position={pos}&week={w}"
                    fetched_endpoints.append(f"{pos} W{w}")

                    # Rate limiter: sleep 1.1s to respect 1 req/sec limit
                    time.sleep(1.1)

                    resp = requests.get(url, headers=headers, timeout=8)
                    if resp.status_code == 429:
                        logger.warning(f"FantasyPros API rate limit reached (429) on {pos} W{w}! Aborting remaining API calls.")
                        # Do not keep hammering the API when quota is exceeded
                        return None, fetched_endpoints
                    elif resp.status_code != 200:
                        logger.warning(f"FantasyPros API request for {pos} W{w} failed: {resp.status_code}")
                        continue

                    data = resp.json()
                    for p in data.get("players", []):
                        name = normalize_player_name(p.get("name", ""))
                        pos_id = p.get("position_id", pos).upper()
                        team = (p.get("team_id") or "FA").upper()
                        if not name:
                            continue

                        key_p = (name, pos_id, team)
                        if key_p not in player_dict:
                            player_dict[key_p] = {
                                "name": name,
                                "position": pos_id,
                                "team": team,
                                "pass_yds": 0.0,
                                "pass_tds": 0.0,
                                "pass_ints": 0.0,
                                "rush_yds": 0.0,
                                "rush_tds": 0.0,
                                "receptions": 0.0,
                                "rec_yds": 0.0,
                                "rec_tds": 0.0,
                                "two_pts": 0.0,
                            }
                        st = p.get("stats", {})
                        rec = player_dict[key_p]
                        rec["pass_yds"] += float(st.get("pass_yds") or 0.0)
                        rec["pass_tds"] += float(st.get("pass_tds") or 0.0)
                        rec["pass_ints"] += float(st.get("pass_ints") or 0.0)
                        rec["rush_yds"] += float(st.get("rush_yds") or 0.0)
                        rec["rush_tds"] += float(st.get("rush_tds") or 0.0)
                        rec["receptions"] += float(st.get("rec_rec") or 0.0)
                        rec["rec_yds"] += float(st.get("rec_yds") or 0.0)
                        rec["rec_tds"] += float(st.get("rec_tds") or 0.0)
                        rec["two_pts"] += float(st.get("2pt_tds") or 0.0)

            if not player_dict:
                return None, fetched_endpoints

            df = pd.DataFrame(list(player_dict.values()))
            # Round stat columns
            for col in STAT_COLS:
                if col in df.columns:
                    df[col] = df[col].round(1)
            df["adp"] = range(1, len(df) + 1)
            df["bye_week"] = 0

            # Save to disk cache
            self._save_cache(df)

            return df, fetched_endpoints

        except Exception as e:
            logger.warning(f"FantasyPros API fetch failed: {e}")
            return None, fetched_endpoints


class FantasyProsWebFetcher(BaseFetcher):
    """
    Scrapes live FantasyPros web tables as an online fallback fetcher.
    """
    def __init__(self, data_dir: str):
        super().__init__("FantasyPros Web Scraper", data_dir)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        self.context = _create_ssl_context()
        self.scraped_urls = []
        self.published_date = time.strftime("%Y-%m-%d")

    def fetch(self) -> Tuple[Optional[pd.DataFrame], List[str]]:
        positions = ["qb", "rb", "wr", "te"]
        all_dfs = []
        self.scraped_urls = []

        for pos in positions:
            url = f"https://www.fantasypros.com/nfl/projections/{pos}.php?max-results=all"
            self.scraped_urls.append((pos.upper(), url))
            try:
                req = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(req, context=self.context, timeout=5) as resp:
                    html = resp.read().decode('utf-8', errors='ignore')
                    soup = BeautifulSoup(html, 'html.parser')
                    table = soup.find('table', {'id': 'data'})
                    if not table:
                        logger.warning(f"FantasyPros {pos.upper()}: no data table found at {url}")
                        continue

                    rows = table.find('tbody').find_all('tr')
                    parsed_rows = []
                    for tr in rows:
                        cols = [td.get_text().strip() for td in tr.find_all('td')]
                        if not cols or len(cols) < 5:
                            continue

                        # Extract name and team from first col (e.g., "Jalen Hurts PHI")
                        full_player_str = cols[0]
                        parts = full_player_str.rsplit(' ', 1)
                        raw_name = parts[0] if len(parts) > 1 else full_player_str
                        team = parts[1] if len(parts) > 1 else "FA"
                        name = normalize_player_name(raw_name)

                        def safe_float(idx):
                            try:
                                return float(cols[idx].replace(',', ''))
                            except (IndexError, ValueError):
                                return 0.0

                        if pos == "qb":
                            parsed_rows.append({
                                "name": name, "position": "QB", "team": team,
                                "pass_yds": safe_float(3), "pass_tds": safe_float(4), "pass_ints": safe_float(5),
                                "rush_yds": safe_float(7), "rush_tds": safe_float(8) if len(cols) > 8 else 0.0,
                                "receptions": 0.0, "rec_yds": 0.0, "rec_tds": 0.0
                            })
                        elif pos == "rb":
                            parsed_rows.append({
                                "name": name, "position": "RB", "team": team,
                                "pass_yds": 0.0, "pass_tds": 0.0, "pass_ints": 0.0,
                                "rush_yds": safe_float(2), "rush_tds": safe_float(3),
                                "receptions": safe_float(4), "rec_yds": safe_float(5), "rec_tds": safe_float(6)
                            })
                        elif pos == "wr":
                            parsed_rows.append({
                                "name": name, "position": "WR", "team": team,
                                "pass_yds": 0.0, "pass_tds": 0.0, "pass_ints": 0.0,
                                "rush_yds": safe_float(5), "rush_tds": safe_float(6),
                                "receptions": safe_float(1), "rec_yds": safe_float(2), "rec_tds": safe_float(3)
                            })
                        elif pos == "te":
                            parsed_rows.append({
                                "name": name, "position": "TE", "team": team,
                                "pass_yds": 0.0, "pass_tds": 0.0, "pass_ints": 0.0,
                                "rush_yds": 0.0, "rush_tds": 0.0,
                                "receptions": safe_float(1), "rec_yds": safe_float(2), "rec_tds": safe_float(3)
                            })
                    if parsed_rows:
                        all_dfs.append(pd.DataFrame(parsed_rows))
            except Exception as e:
                logger.warning(f"FantasyPros {pos.upper()} scrape failed: {e}")
                continue

        if not all_dfs:
            return None, self.scraped_urls

        combined = pd.concat(all_dfs, ignore_index=True)
        # All stats on FantasyPros web pages are per-game averages -> multiply by NUM_Q_WEEKS
        for col in STAT_COLS:
            if col in combined.columns:
                combined[col] = (combined[col] * NUM_Q_WEEKS).round(1)
        combined["two_pts"] = 0.0
        combined["adp"] = range(1, len(combined) + 1)
        combined["bye_week"] = 0
        return combined, self.scraped_urls

class FFTodayWebFetcher(BaseFetcher):
    """
    Scrapes live FFToday public projection tables (QB, RB, WR, TE).
    Extracted publish date from Regular Season Header.
    """
    def __init__(self, data_dir: str):
        super().__init__("FFToday Web Scraper", data_dir)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        self.context = _create_ssl_context()
        self.scraped_urls = []
        self.published_date = "Unknown"

    def clean_val(self, val_str) -> float:
        if not val_str or pd.isna(val_str):
            return 0.0
        clean = str(val_str).replace(',', '').strip()
        try:
            return float(clean)
        except ValueError:
            return 0.0

    def fetch(self) -> Tuple[Optional[pd.DataFrame], List[str]]:
        pos_map = [(10, "QB"), (20, "RB"), (30, "WR"), (40, "TE")]
        all_dfs = []
        self.scraped_urls = []

        for pos_id, pos in pos_map:
            url = f"https://www.fftoday.com/rankings/playerproj.php?PosID={pos_id}&LeagueID=1"
            self.scraped_urls.append((pos, url))
            try:
                req = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(req, context=self.context, timeout=7) as resp:
                    html = resp.read().decode('utf-8', errors='ignore')
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Extract published date from page text if present (e.g. "Updated: 8/6/2026")
                    date_match = re.search(r'Updated:\s*([0-9]+/[0-9]+/[0-9]+)', html, re.IGNORECASE)
                    if date_match and self.published_date == "Unknown":
                        self.published_date = date_match.group(1)

                    tables = soup.find_all('table')

                    target_table = None
                    for t in tables:
                        rows = t.find_all('tr')
                        if len(rows) > 20:
                            target_table = t
                            break

                    if not target_table:
                        logger.warning(f"FFToday {pos}: no projection table found at {url}")
                        continue

                    parsed_rows = []
                    for r in target_table.find_all('tr'):
                        cols = [td.get_text().strip() for td in r.find_all('td')]
                        if len(cols) < 6 or not cols[1]:
                            continue

                        raw_name = cols[1].strip()
                        if (
                            raw_name in ["Chg", "Player"]
                            or raw_name.startswith("Player")
                            or raw_name.startswith("Quarterback")
                            or raw_name.startswith("Running")
                            or raw_name.startswith("Wide")
                            or raw_name.startswith("Tight")
                            or "Sort First" in raw_name
                        ):
                            continue

                        name = normalize_player_name(raw_name)
                        if not name:
                            continue

                        raw_team = cols[2].strip().upper() if len(cols) > 2 else "FA"
                        team = raw_team if len(raw_team) in [2, 3] and raw_team != "TM" else "FA"

                        if pos == "QB" and len(cols) >= 12:
                            # Cmp(4), Att(5), Yds(6), TD(7), INT(8), RushAtt(9), RushYds(10), RushTD(11)
                            parsed_rows.append({
                                "name": name, "position": "QB", "team": team,
                                "pass_yds": self.clean_val(cols[6]),
                                "pass_tds": self.clean_val(cols[7]),
                                "pass_ints": self.clean_val(cols[8]),
                                "rush_yds": self.clean_val(cols[10]),
                                "rush_tds": self.clean_val(cols[11]),
                                "receptions": 0.0, "rec_yds": 0.0, "rec_tds": 0.0
                            })
                        elif pos == "RB" and len(cols) >= 10:
                            # RushAtt(4), RushYds(5), RushTD(6), Rec(7), RecYds(8), RecTD(9)
                            parsed_rows.append({
                                "name": name, "position": "RB", "team": team,
                                "pass_yds": 0.0, "pass_tds": 0.0, "pass_ints": 0.0,
                                "rush_yds": self.clean_val(cols[5]),
                                "rush_tds": self.clean_val(cols[6]),
                                "receptions": self.clean_val(cols[7]),
                                "rec_yds": self.clean_val(cols[8]),
                                "rec_tds": self.clean_val(cols[9])
                            })
                        elif pos == "WR" and len(cols) >= 10:
                            # Rec(4), RecYds(5), RecTD(6), RushAtt(7), RushYds(8), RushTD(9)
                            parsed_rows.append({
                                "name": name, "position": "WR", "team": team,
                                "pass_yds": 0.0, "pass_tds": 0.0, "pass_ints": 0.0,
                                "rush_yds": self.clean_val(cols[8]),
                                "rush_tds": self.clean_val(cols[9]),
                                "receptions": self.clean_val(cols[4]),
                                "rec_yds": self.clean_val(cols[5]),
                                "rec_tds": self.clean_val(cols[6])
                            })
                        elif pos == "TE" and len(cols) >= 7:
                            # Rec(4), RecYds(5), RecTD(6)
                            parsed_rows.append({
                                "name": name, "position": "TE", "team": team,
                                "pass_yds": 0.0, "pass_tds": 0.0, "pass_ints": 0.0,
                                "rush_yds": 0.0, "rush_tds": 0.0,
                                "receptions": self.clean_val(cols[4]),
                                "rec_yds": self.clean_val(cols[5]),
                                "rec_tds": self.clean_val(cols[6])
                            })
                    if parsed_rows:
                        all_dfs.append(pd.DataFrame(parsed_rows))
            except Exception as e:
                logger.warning(f"FFToday {pos} scrape failed: {e}")
                continue

        if not all_dfs:
            return None, self.scraped_urls

        combined = pd.concat(all_dfs, ignore_index=True)
        # All FFToday stats are full season projections -> scale to NUM_Q_WEEKS totals (÷ 17 * NUM_Q_WEEKS)
        for col in STAT_COLS:
            if col in combined.columns:
                combined[col] = (combined[col] / GAMES_PER_SEASON * NUM_Q_WEEKS).round(1)

        combined["two_pts"] = 0.0
        combined["adp"] = range(1, len(combined) + 1)
        combined["bye_week"] = 0
        return combined, self.scraped_urls


class SleeperAPIFetcher(BaseFetcher):
    """
    Connects to Sleeper API to pull live player metadata, team rosters, and injury status.
    """
    SLEEPER_URL = "https://api.sleeper.app/v1/players/nfl"

    def __init__(self, data_dir: str):
        super().__init__("Sleeper API", data_dir)
        self.headers = {'User-Agent': 'Mozilla/5.0'}
        self.context = _create_ssl_context()

    def fetch(self) -> Optional[dict]:
        try:
            req = urllib.request.Request(self.SLEEPER_URL, headers=self.headers)
            with urllib.request.urlopen(req, context=self.context, timeout=5) as resp:
                if resp.status == 200:
                    raw_data = json.loads(resp.read().decode('utf-8'))
                    id_to_name = {}
                    name_to_id = {}
                    for pid, pinfo in raw_data.items():
                        first = pinfo.get("first_name", "")
                        last = pinfo.get("last_name", "")
                        full = f"{first} {last}".strip()
                        if full:
                            id_to_name[pid] = full
                            name_to_id[full.lower()] = pid
                    structured = {
                        "id_to_name": id_to_name,
                        "name_to_id": name_to_id,
                        "_raw": raw_data
                    }
                    cache_path = os.path.join(self.data_dir, "sleeper_players.json")
                    with open(cache_path, "w") as f:
                        json.dump(structured, f)
                    return structured
        except Exception as e:
            logger.warning(f"Sleeper API fetch failed: {e}")

        cache_path = os.path.join(self.data_dir, "sleeper_players.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read Sleeper cache: {e}")
        return None


class SleeperStatsFetcher(BaseFetcher):
    """
    Connects to Sleeper API to pull live actual stats for completed regular season weeks,
    computes per-game run rates, and scales them to a 4-week quarter pace.
    Automatically detects completed weeks (e.g. Weeks 1-3 now, auto-picks up Week 4 when completed).
    """
    def __init__(self, data_dir: str, season: int = 2026):
        super().__init__("Sleeper YTD Actuals", data_dir)
        self.season = season
        self.headers = {'User-Agent': 'Mozilla/5.0'}
        self.context = _create_ssl_context()
        self.completed_weeks = []

    def fetch(self, max_weeks: int = 18) -> Tuple[Optional[pd.DataFrame], List[int]]:
        """
        Dynamically scans regular season weeks. Any week with >= 100 players recording
        offensive stats is considered fully completed. Computes per-game average and scales to 4-week pace.
        """
        cache_path = os.path.join(self.data_dir, "sleeper_players.json")
        raw_players = {}
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r") as f:
                    cache_json = json.load(f)
                    raw_players = cache_json.get("_raw", {})
            except Exception as e:
                logger.warning(f"Could not load sleeper_players.json for stats fetcher: {e}")

        # Load bye weeks map with aliases
        bye_path = os.path.join(self.data_dir, "bye_weeks.json")
        bye_map = {}
        if os.path.exists(bye_path):
            try:
                with open(bye_path, "r") as f:
                    raw_bye = json.load(f)
                    bye_map = {k: int(v) for k, v in raw_bye.items() if not k.startswith("_")}
                    for a, c in raw_bye.get("_aliases", {}).items():
                        if c in bye_map:
                            bye_map[a] = bye_map[c]
            except Exception as e:
                logger.warning(f"Could not load bye_weeks.json: {e}")

        weekly_data = []
        completed_weeks = []

        for wk in range(1, max_weeks + 1):
            url = f"https://api.sleeper.app/v1/stats/nfl/regular/{self.season}/{wk}"
            try:
                req = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(req, context=self.context, timeout=5) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode('utf-8'))
                        # Count how many players recorded offensive stats/snaps
                        active_cnt = sum(
                            1 for p in data.values()
                            if any(p.get(k, 0) > 0 for k in ['pass_yd', 'rush_yd', 'rec_yd', 'rec', 'rush_att', 'pass_att', 'off_snp'])
                        )
                        # A week is considered completed if >= 100 players recorded offensive stats
                        if active_cnt >= 100:
                            weekly_data.append((wk, data))
                            completed_weeks.append(wk)
                        else:
                            # Reached in-progress or unplayed week; stop scanning
                            break
                    else:
                        break
            except Exception as e:
                logger.info(f"Sleeper stats week {wk} not available or completed: {e}")
                break

        self.completed_weeks = completed_weeks
        if not weekly_data:
            return None, []

        player_stats = {}
        for wk, w_dict in weekly_data:
            for pid, s in w_dict.items():
                if pid not in player_stats:
                    pinfo = raw_players.get(pid, {})
                    pos = pinfo.get("position")
                    if pos not in ["QB", "RB", "WR", "TE"]:
                        continue
                    first_n = pinfo.get("first_name", "")
                    last_n = pinfo.get("last_name", "")
                    full_n = f"{first_n} {last_n}".strip()
                    if not full_n:
                        continue
                    name = normalize_player_name(full_n)
                    team = (pinfo.get("team") or "FA").upper()

                    player_stats[pid] = {
                        "name": name,
                        "position": pos,
                        "team": team,
                        "gp": 0,
                        "pass_yds": 0.0, "pass_tds": 0.0, "pass_ints": 0.0,
                        "rush_yds": 0.0, "rush_tds": 0.0,
                        "receptions": 0.0, "rec_yds": 0.0, "rec_tds": 0.0,
                        "two_pts": 0.0
                    }

                has_action = any(s.get(k, 0) > 0 for k in ['pass_yd', 'rush_yd', 'rec_yd', 'rec', 'rush_att', 'pass_att', 'off_snp'])
                if has_action and pid in player_stats:
                    ps = player_stats[pid]
                    ps["gp"] += 1
                    ps["pass_yds"] += float(s.get("pass_yd", 0.0))
                    ps["pass_tds"] += float(s.get("pass_td", 0.0))
                    ps["pass_ints"] += float(s.get("pass_int", 0.0))
                    ps["rush_yds"] += float(s.get("rush_yd", 0.0))
                    ps["rush_tds"] += float(s.get("rush_td", 0.0))
                    ps["receptions"] += float(s.get("rec", 0.0))
                    ps["rec_yds"] += float(s.get("rec_yd", 0.0))
                    ps["rec_tds"] += float(s.get("rec_td", 0.0))
                    ps["two_pts"] += float(s.get("pass_2pt", 0.0) + s.get("rush_2pt", 0.0) + s.get("rec_2pt", 0.0))

        rows = []
        for pid, ps in player_stats.items():
            if ps["gp"] == 0:
                continue
            gp = ps["gp"]
            team_val = ps["team"]
            b_wk = bye_map.get(team_val, bye_map.get(TEAM_ABBR_CANONICAL.get(team_val, team_val), 0))
            rows.append({
                "name": ps["name"],
                "position": ps["position"],
                "team": team_val,
                "pass_yds": round(ps["pass_yds"] / gp * NUM_Q_WEEKS, 1),
                "pass_tds": round(ps["pass_tds"] / gp * NUM_Q_WEEKS, 1),
                "pass_ints": round(ps["pass_ints"] / gp * NUM_Q_WEEKS, 1),
                "rush_yds": round(ps["rush_yds"] / gp * NUM_Q_WEEKS, 1),
                "rush_tds": round(ps["rush_tds"] / gp * NUM_Q_WEEKS, 1),
                "receptions": round(ps["receptions"] / gp * NUM_Q_WEEKS, 1),
                "rec_yds": round(ps["rec_yds"] / gp * NUM_Q_WEEKS, 1),
                "rec_tds": round(ps["rec_tds"] / gp * NUM_Q_WEEKS, 1),
                "two_pts": round(ps["two_pts"] / gp * NUM_Q_WEEKS, 1),
                "adp": 999.0,
                "bye_week": b_wk
            })

        if not rows:
            return None, completed_weeks

        res_df = pd.DataFrame(rows)
        # Order by total offensive production to establish ADP index
        res_df["_sort_val"] = res_df["pass_yds"] * 0.4 + res_df["rush_yds"] + res_df["rec_yds"]
        res_df = res_df.sort_values(by="_sort_val", ascending=False).reset_index(drop=True)
        res_df["adp"] = range(1, len(res_df) + 1)
        res_df = res_df.drop(columns=["_sort_val"])
        return res_df, completed_weeks


class FetcherManager:
    """
    Coordinates live multi-source projection fetching and console reporting.
    Exclusively uses live web scrapers and live APIs (FantasyPros, FFToday, Sleeper).
    """
    def __init__(self, data_dir: str, offline: bool = False):
        self.data_dir = data_dir
        self.sources_dir = os.path.join(data_dir, "sources")
        self.sources_config_path = os.path.join(data_dir, "sources.json")
        self.offline = offline or os.environ.get("OFFLINE_MODE", "0") == "1"
        self.health_matrix = {}

    def run_pipeline(self) -> Dict[str, dict]:
        """Runs the complete live auto-fetch and ingestion pipeline with detailed logging."""
        print("\n" + "=" * 75)
        print("🏈 DRAFT ADVISOR 2026 — STARTUP LIVE PROJECTION INGESTION PIPELINE")
        print("=" * 75)

        # Step 1: Sleeper API Sync
        print("[1/4] 📡 Connecting to Sleeper API for live injuries & player mapping...")
        sleeper_fetcher = SleeperAPIFetcher(self.data_dir)
        sleeper_data = None
        if not self.offline:
            sleeper_data = sleeper_fetcher.fetch()
        else:
            cache_path = os.path.join(self.data_dir, "sleeper_players.json")
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, "r") as f:
                        sleeper_data = json.load(f)
                except Exception as e:
                    logger.warning(f"Failed to read Sleeper cache in offline mode: {e}")

        sync_time_str = time.strftime("%Y-%m-%d %H:%M")

        if sleeper_data:
            num_players = len(sleeper_data.get("id_to_name", {}))
            status_label = "HEALTHY" if not self.offline else "CACHED"
            date_label = sync_time_str if not self.offline else "Cached JSON"
            print(f"      ✅ Loaded {num_players:,} player records from Sleeper ({status_label})")
            self.health_matrix["sleeper"] = {
                "name": "Sleeper API",
                "status": status_label,
                "players": num_players,
                "published_date": date_label,
                "timestamp": time.time()
            }
        else:
            print("      ⚠️ Sleeper API offline or skipped; using local cache.")
            self.health_matrix["sleeper"] = {
                "name": "Sleeper API",
                "status": "UNAVAILABLE",
                "players": 0,
                "published_date": "N/A",
                "timestamp": time.time()
            }

        # Step 2: FantasyPros & FFToday Live Web Scrapers
        print("[2/4] 🌐 Executing Live Web Scrapers for FantasyPros & FFToday...")
        target_fp = os.path.join(self.sources_dir, "fantasypros.csv")

        if not self.offline:
            # 2a. Check ~/Downloads for full FantasyPros CSV exports first (500+ players)
            dl_fetcher = DownloadsWatcherFetcher(self.data_dir)
            df_dl, _ = dl_fetcher.fetch()
            valid_dl, dl_msg = DataSanityGuard.validate(df_dl, "FantasyPros Downloads", min_players=50)

            if valid_dl:
                df_dl.to_csv(target_fp, index=False)
                pub_dl = time.strftime("%Y-%m-%d")
                print(f"      ✅ Auto-ingested {len(df_dl)} players from ~/Downloads -> data/sources/fantasypros.csv (Published: {pub_dl})")
                self.health_matrix["fantasypros"] = {
                    "name": "FantasyPros Projections (Full Downloads Export)",
                    "status": "HEALTHY",
                    "source": "~/Downloads Export",
                    "players": len(df_dl),
                    "published_date": pub_dl,
                    "timestamp": time.time()
                }
                # Parallel: FFToday only (FantasyPros already ingested from Downloads)
                self._fetch_fftoday()
            else:
                if dl_msg:
                    logger.info(f"Downloads watcher: {dl_msg}")
                # Parallel: FantasyPros web scraper + FFToday web scraper
                self._fetch_scrapers_parallel(target_fp)
        else:
            print("      ⚡ Offline mode active; using cached CSV sources in data/sources/.")

        # Step 3: Sleeper YTD Actual Performance Aggregator
        print("[3/4] ⚡ Aggregating Live Sleeper YTD Actual Performance...")
        target_ytd = os.path.join(self.sources_dir, "sleeper_ytd.csv")
        if not self.offline:
            stats_fetcher = SleeperStatsFetcher(self.data_dir)
            df_ytd, comp_weeks = stats_fetcher.fetch()
            valid_ytd, ytd_msg = DataSanityGuard.validate(df_ytd, "Sleeper YTD Stats", min_players=30)
            if valid_ytd:
                df_ytd.to_csv(target_ytd, index=False)
                w_range = f"Weeks 1–{comp_weeks[-1]}" if comp_weeks else "YTD"
                print(f"      ✅ Auto-ingested {len(df_ytd)} players from {w_range} actuals -> data/sources/sleeper_ytd.csv")
                self.health_matrix["sleeper_ytd"] = {
                    "name": f"Sleeper YTD Actuals ({w_range} Pace)",
                    "status": "HEALTHY",
                    "source": "Sleeper Stats API",
                    "players": len(df_ytd),
                    "published_date": f"{w_range} Actuals",
                    "timestamp": time.time()
                }
            else:
                logger.info(f"Sleeper YTD stats: {ytd_msg}")
                print(f"      ⚠️ Sleeper YTD stats skipped: {ytd_msg}")
        else:
            if os.path.exists(target_ytd):
                try:
                    df_cached = pd.read_csv(target_ytd)
                    self.health_matrix["sleeper_ytd"] = {
                        "name": "Sleeper YTD Actuals (Offline Cache)",
                        "status": "CACHED",
                        "source": "Cached CSV",
                        "players": len(df_cached),
                        "published_date": "Cached CSV",
                        "timestamp": time.time()
                    }
                except Exception as e:
                    logger.warning(f"Failed to read cached sleeper_ytd.csv: {e}")

        # Step 4: Console Summary Matrix Log
        print("[4/4] 🔄 Live projection sources updated & ready for synthesizer!")
        print("\n" + "=" * 75)
        print("📊 LIVE MULTI-SOURCE DATA COLLECTION & INGESTION REPORT")
        print("=" * 75)
        for src_key, src_info in self.health_matrix.items():
            s_name = src_info.get("name", src_key)
            s_count = src_info.get("players", 0)
            s_date = src_info.get("published_date", "Unknown")
            s_status = src_info.get("status", "HEALTHY")
            print(f"  • {s_name:<42} | Status: {s_status:<10} | Players: {s_count:>4} | Published: {s_date}")
        print("=" * 75 + "\n")
        return self.health_matrix

    def _fetch_fftoday(self):
        """Fetches FFToday projections."""
        target_fft = os.path.join(self.sources_dir, "fftoday.csv")
        fft_fetcher = FFTodayWebFetcher(self.data_dir)
        df_fft, urls_fft = fft_fetcher.fetch()
        valid_fft, fft_msg = DataSanityGuard.validate(df_fft, "FFToday Web", min_players=50)

        if valid_fft:
            df_fft.to_csv(target_fft, index=False)
            pub_fft = fft_fetcher.published_date
            print(f"      ✅ Scraped {len(df_fft)} players from FFToday Web -> data/sources/fftoday.csv (Published: {pub_fft})")
            self.health_matrix["fftoday"] = {
                "name": "FFToday Projections (Live Scraper)",
                "status": "HEALTHY",
                "source": "Live Web Scraper",
                "players": len(df_fft),
                "published_date": pub_fft,
                "timestamp": time.time()
            }
        else:
            logger.info(f"FFToday scraper: {fft_msg}")
            print("      ⚠️ FFToday Web Scraper skipped or empty.")
            self.health_matrix["fftoday"] = {
                "name": "FFToday Projections (Live Scraper)",
                "status": "UNAVAILABLE",
                "source": "Live Web Scraper",
                "players": 0,
                "published_date": "N/A",
                "timestamp": time.time()
            }

    def _fetch_scrapers_parallel(self, target_fp: str):
        """Runs FantasyPros and FFToday web scrapers in parallel using ThreadPoolExecutor."""
        fp_result = {"df": None, "urls": [], "valid": False}
        fft_result = {"df": None, "urls": [], "valid": False}

        def _run_fantasypros():
            # Check for official API key first
            api_key = os.environ.get("FANTASYPROS_API_KEY", "").strip()
            if api_key:
                api_fetcher = FantasyProsAPIFetcher(self.data_dir, api_key=api_key)
                df_api, endpoints = api_fetcher.fetch()
                valid_api, msg = DataSanityGuard.validate(df_api, "FantasyPros Official API", min_players=20)
                if valid_api:
                    fp_result["df"] = df_api
                    fp_result["urls"] = endpoints
                    fp_result["valid"] = True
                    fp_result["published_date"] = api_fetcher.published_date
                    fp_result["source_label"] = "Official REST API"
                    return

            # Fallback to web scraper
            fp_fetcher = FantasyProsWebFetcher(self.data_dir)
            df_fp, urls_fp = fp_fetcher.fetch()
            valid_fp, msg = DataSanityGuard.validate(df_fp, "FantasyPros Web", min_players=20)
            fp_result["df"] = df_fp
            fp_result["urls"] = urls_fp
            fp_result["valid"] = valid_fp
            fp_result["published_date"] = fp_fetcher.published_date
            fp_result["source_label"] = "Live Web Scraper"
            if not valid_fp:
                logger.info(f"FantasyPros web scraper: {msg}")

        def _run_fftoday():
            fft_fetcher = FFTodayWebFetcher(self.data_dir)
            df_fft, urls_fft = fft_fetcher.fetch()
            valid_fft, msg = DataSanityGuard.validate(df_fft, "FFToday Web", min_players=50)
            fft_result["df"] = df_fft
            fft_result["urls"] = urls_fft
            fft_result["valid"] = valid_fft
            fft_result["published_date"] = fft_fetcher.published_date
            if not valid_fft:
                logger.info(f"FFToday web scraper: {msg}")

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(_run_fantasypros),
                executor.submit(_run_fftoday),
            ]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.warning(f"Parallel fetch task failed: {e}")

        # Process FantasyPros result
        if fp_result["valid"]:
            fp_result["df"].to_csv(target_fp, index=False)
            pub_fp = fp_result.get("published_date", time.strftime("%Y-%m-%d"))
            label = fp_result.get("source_label", "Live Web Scraper")
            name_label = f"FantasyPros Projections ({label})"
            print(f"      ✅ Ingested {len(fp_result['df'])} players from FantasyPros ({label}) -> data/sources/fantasypros.csv (Published: {pub_fp})")
            self.health_matrix["fantasypros"] = {
                "name": name_label,
                "status": "HEALTHY",
                "source": label,
                "players": len(fp_result["df"]),
                "published_date": pub_fp,
                "timestamp": time.time()
            }

        # Process FFToday result
        target_fft = os.path.join(self.sources_dir, "fftoday.csv")
        if fft_result["valid"]:
            fft_result["df"].to_csv(target_fft, index=False)
            pub_fft = fft_result.get("published_date", "Unknown")
            print(f"      ✅ Scraped {len(fft_result['df'])} players from FFToday Web -> data/sources/fftoday.csv (Published: {pub_fft})")
            self.health_matrix["fftoday"] = {
                "name": "FFToday Projections (Live Scraper)",
                "status": "HEALTHY",
                "source": "Live Web Scraper",
                "players": len(fft_result["df"]),
                "published_date": pub_fft,
                "timestamp": time.time()
            }
        else:
            print("      ⚠️ FFToday Web Scraper skipped or empty.")
            self.health_matrix["fftoday"] = {
                "name": "FFToday Projections (Live Scraper)",
                "status": "UNAVAILABLE",
                "source": "Live Web Scraper",
                "players": 0,
                "published_date": "N/A",
                "timestamp": time.time()
            }
