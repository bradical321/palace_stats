"""
Opponent scouting collector — port of opponent_stats_2.py for the single-club
FC 27 setup, storage-backed instead of Dropbox-direct.

For every opponent club found in matches.csv, fetch:
  - clubs/overallStats  -> win %, record, skill rating          (opponent_club_stats.csv)
  - members/stats       -> full roster season-to-date stats     (opponent_player_stats.csv)

Run after collector.py (or on its own slower cadence — opponents' season
stats don't need refreshing every 30 minutes). Needs the same visible-browser
session as collector.py, for the same Akamai reason — see collector.py's
module docstring.

Run: python opponent_scout.py [--all]
    --all   refetch every opponent ever played, not just ones missing from
            opponent_club_stats.csv
"""
import sys
import json
from datetime import datetime

import pandas as pd
from playwright.sync_api import sync_playwright

import config
from storage import get_storage

FETCH_JS = """
async (url) => {
  try {
    const r = await fetch(url, {headers: {'Accept': 'application/json'}});
    const text = await r.text();
    return {status: r.status, body: text};
  } catch (e) {
    return {status: -1, body: String(e)};
  }
}
"""


def _fetch_json(page, url: str, label: str):
    result = page.evaluate(FETCH_JS, url)
    if result["status"] != 200:
        print(f"⚠️  {label}: HTTP {result['status']}")
        return None
    try:
        return json.loads(result["body"])
    except json.JSONDecodeError:
        return None


def get_opponent_ids_to_fetch(storage, refetch_all: bool) -> list[str]:
    matches = storage.read_csv(config.TABLE_MATCHES, dtype={"opponent_club_id": str})
    if matches.empty:
        return []
    # matches.csv has a row per perspective (is_our_club True/False) — read
    # opponent_club_id only from OUR rows, or the opponent-perspective rows
    # (whose "opponent" is us) leak our own club id into this list.
    our_rows = matches[matches["is_our_club"].astype(str).str.lower() == "true"]
    all_opponents = set(our_rows["opponent_club_id"].dropna().astype(str))

    if refetch_all:
        return sorted(all_opponents)

    existing = storage.read_csv(config.TABLE_OPPONENT_CLUB_STATS, dtype={"club_id": str})
    already_have = set(existing["club_id"].astype(str)) if not existing.empty else set()
    return sorted(all_opponents - already_have)


def fetch_opponent_data(opponent_ids: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    club_rows, player_rows = [], []
    fetched_at = datetime.now().isoformat()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1680, "height": 1000},
            locale="en-US",
        )
        page = ctx.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});window.chrome={runtime:{}};"
        )
        page.goto(config.LANDING_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(7000)

        for idx, club_id in enumerate(opponent_ids, 1):
            print(f"🔄 ({idx}/{len(opponent_ids)}) club {club_id}")

            stats = _fetch_json(page, config.club_overall_stats_url(club_id), f"overallStats:{club_id}")
            if stats:
                s = stats[0] if isinstance(stats, list) else stats
                games = int(s.get("gamesPlayed", 0) or 0)
                wins = int(s.get("wins", 0) or 0)
                ties = int(s.get("ties", 0) or 0)
                club_rows.append({
                    "club_id": str(club_id),
                    "games_played": games,
                    "wins": wins,
                    "losses": int(s.get("losses", 0) or 0),
                    "ties": ties,
                    "win_pct": round(wins / games * 100, 2) if games else 0,
                    "win_or_draw_pct": round((wins + ties) / games * 100, 2) if games else 0,
                    "goals": int(s.get("goals", 0) or 0),
                    "goals_against": int(s.get("goalsAgainst", 0) or 0),
                    "skill_rating": int(s.get("skillRating", 0) or 0),
                    "data_fetched_at": fetched_at,
                })

            page.wait_for_timeout(1500)

            members = _fetch_json(page, config.member_stats_url(club_id), f"memberStats:{club_id}")
            if members and members.get("members"):
                for m in members["members"]:
                    m["club_id"] = str(club_id)
                    m["data_fetched_at"] = fetched_at
                    player_rows.append(m)

            if idx < len(opponent_ids):
                page.wait_for_timeout(2000)

        browser.close()

    return pd.DataFrame(club_rows), pd.DataFrame(player_rows)


def run(refetch_all: bool = False):
    storage = get_storage()
    opponent_ids = get_opponent_ids_to_fetch(storage, refetch_all)

    if not opponent_ids:
        print("✅ No new opponents to fetch — opponent_club_stats.csv is up to date.")
        return

    print(f"Fetching {len(opponent_ids)} opponent club(s): {opponent_ids}")
    new_club_stats, new_player_stats = fetch_opponent_data(opponent_ids)

    existing_club = storage.read_csv(config.TABLE_OPPONENT_CLUB_STATS, dtype={"club_id": str})
    if not existing_club.empty and not new_club_stats.empty:
        existing_club = existing_club[~existing_club["club_id"].isin(new_club_stats["club_id"])]
        final_club = pd.concat([existing_club, new_club_stats], ignore_index=True)
    else:
        final_club = new_club_stats if not new_club_stats.empty else existing_club
    storage.write_csv(config.TABLE_OPPONENT_CLUB_STATS, final_club)

    existing_players = storage.read_csv(config.TABLE_OPPONENT_PLAYER_STATS, dtype={"club_id": str})
    if not existing_players.empty and not new_player_stats.empty:
        existing_players = existing_players[~existing_players["club_id"].isin(new_player_stats["club_id"])]
        final_players = pd.concat([existing_players, new_player_stats], ignore_index=True)
    else:
        final_players = new_player_stats if not new_player_stats.empty else existing_players
    storage.write_csv(config.TABLE_OPPONENT_PLAYER_STATS, final_players)

    print(f"✅ opponent_club_stats.csv: {len(final_club)} clubs total")
    print(f"✅ opponent_player_stats.csv: {len(final_players)} players total")


if __name__ == "__main__":
    try:
        run(refetch_all="--all" in sys.argv)
    except Exception as e:
        print(f"❌ Opponent scout failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
