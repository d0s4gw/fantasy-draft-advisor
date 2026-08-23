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

logger = logging.getLogger(__name__)

# Stat column names standard
STAT_COLS = [
    "pass_yds", "pass_tds", "pass_ints",
    "rush_yds", "rush_tds",
    "receptions", "rec_yds", "rec_tds", "two_pts"
]

GAMES_PER_SEASON = 17
Q1_WEEKS = 4


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
            # Season totals: divide by games per season, then multiply by Q1 weeks
            for col in STAT_COLS:
                if col in combined.columns:
                    combined[col] = (combined[col] / GAMES_PER_SEASON * Q1_WEEKS).round(1)
        else:
            # Per-game averages: multiply by Q1 weeks
            for col in STAT_COLS:
                if col in combined.columns:
                    combined[col] = (combined[col] * Q1_WEEKS).round(1)

        combined["two_pts"] = 0.0
        combined["adp"] = range(1, len(combined) + 1)
        combined["bye_week"] = 0
        return combined, self.read_files


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
        # All stats on FantasyPros web pages are per-game averages -> multiply by Q1_WEEKS (4)
        for col in STAT_COLS:
            if col in combined.columns:
                combined[col] = (combined[col] * Q1_WEEKS).round(1)
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
        # All FFToday stats are full season projections -> scale to 4-week Q1 totals (÷ 17 * 4)
        for col in STAT_COLS:
            if col in combined.columns:
                combined[col] = (combined[col] / GAMES_PER_SEASON * Q1_WEEKS).round(1)

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
        print("[1/3] 📡 Connecting to Sleeper API for live injuries & player mapping...")
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
        print("[2/3] 🌐 Executing Live Web Scrapers for FantasyPros & FFToday...")
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

        # Step 3: Console Summary Matrix Log
        print("[3/3] 🔄 Live projection sources updated & ready for synthesizer!")
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
            fp_fetcher = FantasyProsWebFetcher(self.data_dir)
            df_fp, urls_fp = fp_fetcher.fetch()
            valid_fp, msg = DataSanityGuard.validate(df_fp, "FantasyPros Web", min_players=20)
            fp_result["df"] = df_fp
            fp_result["urls"] = urls_fp
            fp_result["valid"] = valid_fp
            fp_result["published_date"] = fp_fetcher.published_date
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
            print(f"      ✅ Scraped {len(fp_result['df'])} players from FantasyPros Web -> data/sources/fantasypros.csv (Published: {pub_fp})")
            self.health_matrix["fantasypros"] = {
                "name": "FantasyPros Projections (Live Scraper)",
                "status": "HEALTHY",
                "source": "Live Web Scraper",
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
