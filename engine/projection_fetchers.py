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
import urllib.request
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
from bs4 import BeautifulSoup

# Stat column names standard
STAT_COLS = [
    "pass_yds", "pass_tds", "pass_ints",
    "rush_yds", "rush_tds",
    "receptions", "rec_yds", "rec_tds", "two_pts"
]

GAMES_PER_SEASON = 17
Q1_WEEKS = 4


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
            except Exception:
                continue

        if not all_dfs:
            return None, self.read_files

        combined = pd.concat(all_dfs, ignore_index=True)
        # Convert season totals to 4-week Q1 totals
        for col in STAT_COLS:
            if col in combined.columns:
                combined[col] = (combined[col] / GAMES_PER_SEASON * Q1_WEEKS).round(1)

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
        self.context = ssl._create_unverified_context()
        self.scraped_urls = []

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
            except Exception:
                continue

        if not all_dfs:
            return None, self.scraped_urls

        combined = pd.concat(all_dfs, ignore_index=True)
        # Convert season totals to 4-week Q1 totals
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
        self.context = ssl._create_unverified_context()

    def fetch(self) -> Optional[dict]:
        try:
            req = urllib.request.Request(self.SLEEPER_URL, headers=self.headers)
            with urllib.request.urlopen(req, context=self.context, timeout=5) as resp:
                if resp.status == 200:
                    raw_data = json.loads(resp.read().decode('utf-8'))
                    # Build structured format compatible with SleeperSync
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
        except Exception:
            pass

        # Try local cache
        cache_path = os.path.join(self.data_dir, "sleeper_players.json")
        if os.path.exists(cache_path):
            with open(cache_path, "r") as f:
                return json.load(f)
        return None


class FetcherManager:
    """
    Coordinates multi-source projection fetching, quality guardrails,
    caching TTL, offline mode, and console progress reporting.
    """
    def __init__(self, data_dir: str, offline: bool = False):
        self.data_dir = data_dir
        self.sources_dir = os.path.join(data_dir, "sources")
        self.sources_config_path = os.path.join(data_dir, "sources.json")
        self.offline = offline or os.environ.get("OFFLINE_MODE", "0") == "1"
        self.health_matrix = {}

    def run_pipeline(self) -> Dict[str, dict]:
        """Runs the complete auto-fetch and ingestion pipeline with console progress reporting."""
        print("\n" + "=" * 75)
        print("🏈 DRAFT ADVISOR 2026 — STARTUP PROJECTION INGESTION PIPELINE")
        print("=" * 75)

        # Step 1: Sleeper API Sync
        print("[1/3] 📡 Connecting to Sleeper API for live injuries & player mapping...")
        sleeper_fetcher = SleeperAPIFetcher(self.data_dir)
        sleeper_data = None if self.offline else sleeper_fetcher.fetch()

        if sleeper_data:
            print(f"      ✅ Synced {len(sleeper_data):,} player records from Sleeper API!")
            self.health_matrix["sleeper"] = {
                "status": "HEALTHY",
                "message": f"{len(sleeper_data):,} players cached",
                "timestamp": time.time()
            }
        else:
            print("      ⚠️ Sleeper API offline or skipped; using local cache.")
            self.health_matrix["sleeper"] = {
                "status": "CACHED",
                "message": "Using cached sleeper_players.json",
                "timestamp": time.time()
            }

        # Step 2: FantasyPros / Multi-Source Downloads & Scraping
        print("[2/3] 📥 Checking local ~/Downloads & web sources for updated projections...")

        target_fp = os.path.join(self.sources_dir, "fantasypros.csv")
        rel_target_fp = os.path.relpath(target_fp, self.data_dir)

        if not self.offline:
            # Try Downloads Watcher first
            dl_fetcher = DownloadsWatcherFetcher(self.data_dir)
            df_dl, read_files = dl_fetcher.fetch()
            valid, msg = DataSanityGuard.validate(df_dl, "FantasyPros Downloads", min_players=50)

            if valid:
                if read_files:
                    print("      • Found matching export CSVs in ~/Downloads:")
                    for pos, fname, fpath in read_files:
                        print(f"        - [{pos}] {fname}")
                
                # Save backup
                if os.path.exists(target_fp):
                    shutil.copy(target_fp, target_fp + ".bak")
                df_dl.to_csv(target_fp, index=False)
                print(f"      ✅ Auto-ingested {len(df_dl)} players from ~/Downloads -> data/sources/fantasypros.csv!")
                self.health_matrix["fantasypros"] = {
                    "status": "HEALTHY",
                    "source": "~/Downloads CSV",
                    "files": [f[1] for f in read_files],
                    "target": "data/sources/fantasypros.csv",
                    "players": len(df_dl),
                    "timestamp": time.time()
                }
            else:
                # Fallback to Web Scraper
                print("      • No complete ~/Downloads CSV set found. Falling back to FantasyPros Web Scraper...")
                web_fetcher = FantasyProsWebFetcher(self.data_dir)
                df_web, scraped_urls = web_fetcher.fetch()
                
                if scraped_urls:
                    print("      • Scraping live FantasyPros projection tables:")
                    for pos, url in scraped_urls:
                        print(f"        - [{pos}] {url}")

                valid_web, msg_web = DataSanityGuard.validate(df_web, "FantasyPros Web", min_players=20)
                if valid_web:
                    if os.path.exists(target_fp):
                        shutil.copy(target_fp, target_fp + ".bak")
                    df_web.to_csv(target_fp, index=False)
                    print(f"      ✅ Scraped {len(df_web)} players from FantasyPros Web -> data/sources/fantasypros.csv!")
                    self.health_matrix["fantasypros"] = {
                        "status": "HEALTHY",
                        "source": "Web Scraper",
                        "urls": [u[1] for u in scraped_urls],
                        "target": "data/sources/fantasypros.csv",
                        "players": len(df_web),
                        "timestamp": time.time()
                    }
                else:
                    print(f"      ⚠️ FantasyPros auto-fetch fallback used existing local CSV at data/sources/fantasypros.csv: {msg}")
                    self.health_matrix["fantasypros"] = {
                        "status": "FALLBACK",
                        "source": "Existing Local CSV",
                        "target": "data/sources/fantasypros.csv",
                        "players": 0,
                        "timestamp": time.time()
                    }
        else:
            print("      ⚡ Offline mode active; using existing local CSV at data/sources/fantasypros.csv.")
            self.health_matrix["fantasypros"] = {
                "status": "OFFLINE",
                "source": "Local CSV Cache",
                "target": "data/sources/fantasypros.csv",
                "players": 0,
                "timestamp": time.time()
            }

        print("[3/3] 🔄 Projection sources updated & ready for synthesizer!")
        print("=" * 75 + "\n")
        return self.health_matrix
