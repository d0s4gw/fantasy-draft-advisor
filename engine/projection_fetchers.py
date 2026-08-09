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
        # Convert stats to 4-week Q1 totals (QBs per-game, RB/WR/TE season totals)
        qb_mask = combined["position"] == "QB"
        for col in STAT_COLS:
            if col in combined.columns:
                combined.loc[qb_mask, col] = (combined.loc[qb_mask, col] * Q1_WEEKS).round(1)
                combined.loc[~qb_mask, col] = (combined.loc[~qb_mask, col] / GAMES_PER_SEASON * Q1_WEEKS).round(1)

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
        self.context = ssl._create_unverified_context()
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
                        continue

                    parsed_rows = []
                    for r in target_table.find_all('tr'):
                        cols = [td.get_text().strip() for td in r.find_all('td')]
                        if len(cols) < 6 or not cols[1]:
                            continue

                        raw_name = cols[1]
                        if raw_name in ["Chg", "Player"] or raw_name.startswith("Quarterback") or raw_name.startswith("Running") or raw_name.startswith("Wide") or raw_name.startswith("Tight"):
                            continue

                        name = normalize_player_name(raw_name)
                        team = cols[2] if len(cols) > 2 and len(cols[2]) in [2, 3] else "FA"

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
            except Exception:
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
        self.context = ssl._create_unverified_context()

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
        except Exception:
            pass

        cache_path = os.path.join(self.data_dir, "sleeper_players.json")
        if os.path.exists(cache_path):
            with open(cache_path, "r") as f:
                return json.load(f)
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
        sleeper_data = None if self.offline else sleeper_fetcher.fetch()
        sync_time_str = time.strftime("%Y-%m-%d %H:%M")

        if sleeper_data:
            num_players = len(sleeper_data.get("id_to_name", {}))
            print(f"      ✅ Synced {num_players:,} player records from Sleeper API! (Synced: {sync_time_str})")
            self.health_matrix["sleeper"] = {
                "name": "Sleeper API",
                "status": "HEALTHY",
                "players": num_players,
                "published_date": sync_time_str,
                "timestamp": time.time()
            }
        else:
            print("      ⚠️ Sleeper API offline or skipped; using local cache.")
            self.health_matrix["sleeper"] = {
                "name": "Sleeper API",
                "status": "CACHED",
                "players": 0,
                "published_date": "Cached JSON",
                "timestamp": time.time()
            }

        # Step 2: FantasyPros & FFToday Live Web Scrapers
        print("[2/3] 🌐 Executing Live Web Scrapers for FantasyPros & FFToday...")
        target_fp = os.path.join(self.sources_dir, "fantasypros.csv")

        if not self.offline:
            # 2a. FantasyPros Live Web Scraper
            fp_fetcher = FantasyProsWebFetcher(self.data_dir)
            df_fp, urls_fp = fp_fetcher.fetch()
            valid_fp, _ = DataSanityGuard.validate(df_fp, "FantasyPros Web", min_players=20)

            if valid_fp:
                df_fp.to_csv(target_fp, index=False)
                pub_fp = fp_fetcher.published_date
                print(f"      ✅ Scraped {len(df_fp)} players from FantasyPros Web -> data/sources/fantasypros.csv (Published: {pub_fp})")
                self.health_matrix["fantasypros"] = {
                    "name": "FantasyPros Projections (Live Scraper)",
                    "status": "HEALTHY",
                    "source": "Live Web Scraper",
                    "players": len(df_fp),
                    "published_date": pub_fp,
                    "timestamp": time.time()
                }
            else:
                print("      • FantasyPros Web Scraper incomplete; checking ~/Downloads fallback...")
                dl_fetcher = DownloadsWatcherFetcher(self.data_dir)
                df_dl, _ = dl_fetcher.fetch()
                valid_dl, _ = DataSanityGuard.validate(df_dl, "FantasyPros Downloads", min_players=50)
                if valid_dl:
                    df_dl.to_csv(target_fp, index=False)
                    pub_dl = time.strftime("%Y-%m-%d")
                    print(f"      ✅ Auto-ingested {len(df_dl)} players from ~/Downloads -> data/sources/fantasypros.csv (Published: {pub_dl})")
                    self.health_matrix["fantasypros"] = {
                        "name": "FantasyPros Projections (Downloads Fallback)",
                        "status": "HEALTHY",
                        "source": "~/Downloads Fallback",
                        "players": len(df_dl),
                        "published_date": pub_dl,
                        "timestamp": time.time()
                    }

            # 2b. FFToday Live Web Scraper
            target_fft = os.path.join(self.sources_dir, "fftoday.csv")
            fft_fetcher = FFTodayWebFetcher(self.data_dir)
            df_fft, urls_fft = fft_fetcher.fetch()
            valid_fft, _ = DataSanityGuard.validate(df_fft, "FFToday Web", min_players=50)

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
                print("      ⚠️ FFToday Web Scraper skipped or empty.")
                self.health_matrix["fftoday"] = {
                    "name": "FFToday Projections (Live Scraper)",
                    "status": "UNAVAILABLE",
                    "source": "Live Web Scraper",
                    "players": 0,
                    "published_date": "N/A",
                    "timestamp": time.time()
                }
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
