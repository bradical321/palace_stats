"""
FC 27 data collector.

Confirmed live against club 23137 ("Palace") on 2026-10-14:
  - https://proclubs.ea.com/api/fc/* is unchanged from FC 24-26, same base path,
    same field names, for every endpoint this pipeline uses.
  - Akamai still blocks plain requests/curl and headless Chromium (403 /
    ERR_HTTP2_PROTOCOL_ERROR) — the only path that works is a REAL, VISIBLE
    browser window loading the ea.com Clubs page, then fetch()-ing the API
    from inside that page's JS context. That means this script cannot run
    headless or on a server with no display (Streamlit Cloud included) — run
    it on a machine with a screen, same as before (cron on your Mac, etc).
  - matchType is now numeric in the payload (1=league, 2=playoff, 5=friendly).
  - "friendlyMatch" now has real data for this club — EA's own ranked ladder
    ("leagueMatch") is one competition, and everything this group's actual
    external league/cup play happens through shows up as "friendlyMatch".
  - maxResultCount=10 works (default 5, hard cap 10 — EA refuses anything
    higher silently/with no error, so don't bother asking for more).

Run: python collector.py
"""
import json
import sys
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
        print(f"⚠️  {label}: HTTP {result['status']} — {result['body'][:200]}")
        return None
    try:
        return json.loads(result["body"])
    except json.JSONDecodeError:
        print(f"⚠️  {label}: non-JSON response — {result['body'][:200]}")
        return None


def fetch_all_raw():
    """Open one visible browser session and pull every endpoint we need from it."""
    raw = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1680, "height": 1000},
            locale="en-US",
            timezone_id="America/Denver",
        )
        page = ctx.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            "window.chrome={runtime:{}};"
        )

        print(f"-> loading {config.LANDING_URL}")
        page.goto(config.LANDING_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(7000)

        raw["club_info"] = _fetch_json(page, config.club_info_url(config.CLUB_ID), "clubInfo")
        raw["club_overall_stats"] = _fetch_json(
            page, config.club_overall_stats_url(config.CLUB_ID), "clubOverallStats"
        )
        raw["member_stats"] = _fetch_json(page, config.member_stats_url(config.CLUB_ID), "memberStats")
        raw["member_career_stats"] = _fetch_json(
            page, config.member_career_stats_url(config.CLUB_ID), "memberCareerStats"
        )
        page.wait_for_timeout(1000)

        raw["matches"] = {}
        for key, query_type in config.MATCH_TYPE_QUERY.items():
            raw["matches"][key] = _fetch_json(page, config.matches_url(query_type), f"matches:{key}") or []
            page.wait_for_timeout(1200)

        browser.close()
    return raw


def _ea_result_letter(club_entry: dict) -> str:
    """W/L/D for this club in this match.

    Confirmed live on 2026-10-14: EA's own wins/losses/ties flags on the club
    entry are unambiguous (exactly one is "1") and were cross-checked against
    goals_for/goals_against on every match in this club's history — use those
    directly rather than decoding the separate numeric 'result' code, whose
    encoding has changed at least once already (FC 24-26 scrapers assumed
    '0'=W/'2'=L/else D; on this club's FC 27 data that code is actually
    '1'=W/'2'=L/'4'=D — decoding it is a trap, the flags aren't).
    """
    if str(club_entry.get("wins", "0")) == "1":
        return "W"
    if str(club_entry.get("losses", "0")) == "1":
        return "L"
    if str(club_entry.get("ties", "0")) == "1":
        return "D"
    # Fallback, only if EA ever sends all-zero flags: decode the result code
    # using the mapping confirmed live above.
    r = str(club_entry.get("result", ""))
    return "W" if r == "1" else "L" if r == "2" else "D"


def _match_row(match, club_id, club_data, is_our_club, opponent_club_id, opponent_club_name,
                our_player_count, opponent_player_count, ea_match_type, fetched_at) -> dict:
    return {
        "matchId": str(match["matchId"]).strip(),
        "match_type": ea_match_type,          # league / playoff / friendly (our query bucket, EA's string type)
        "match_type_ea": club_data.get("matchType", ""),  # EA's own numeric code, kept as a sanity check
        "season_id": club_data.get("season_id", ""),
        "game_number": club_data.get("gameNumber", ""),
        "timestamp": match["timestamp"],
        "date": datetime.fromtimestamp(match["timestamp"]).strftime("%Y-%m-%d %H:%M:%S"),
        "is_our_club": is_our_club,
        "club_id": club_id,
        "goals_for": int(club_data["goals"]),
        "goals_against": int(club_data["goalsAgainst"]),
        "result": _ea_result_letter(club_data),
        "wins": int(club_data.get("wins", 0) or 0),
        "losses": int(club_data.get("losses", 0) or 0),
        "ties": int(club_data.get("ties", 0) or 0),
        "our_player_count": our_player_count,
        "opponent_player_count": opponent_player_count,
        "opponent_club_id": opponent_club_id,
        "opponent_club_name": opponent_club_name,
        "player_count_difference": our_player_count - opponent_player_count,
        "score": club_data.get("score", ""),
        "winner_by_dnf": club_data.get("winnerByDnf", ""),
        "data_fetched_at": fetched_at,
    }


def _player_row(match, club_id, club_name, player_id, p, is_our_club, ea_match_type,
                 our_player_count, opponent_player_count, result_letter, fetched_at) -> dict:
    return {
        "matchId": str(match["matchId"]).strip(),
        "match_type": ea_match_type,
        "timestamp": match["timestamp"],
        "date": datetime.fromtimestamp(match["timestamp"]).strftime("%Y-%m-%d %H:%M:%S"),
        "is_our_club": is_our_club,
        "club_id": club_id,
        "club_name": club_name,
        "player_id": str(player_id).strip(),
        "player_name": p.get("playername", "Unknown"),
        "archetype_id": str(p.get("archetypeid", "")),
        "position": p.get("pos", "Unknown"),
        "rating": float(p.get("rating", 0) or 0),
        "goals": int(p.get("goals", 0) or 0),
        "assists": int(p.get("assists", 0) or 0),
        "shots": int(p.get("shots", 0) or 0),
        "passes_made": int(p.get("passesmade", 0) or 0),
        "pass_attempts": int(p.get("passattempts", 0) or 0),
        "tackles_made": int(p.get("tacklesmade", 0) or 0),
        "tackle_attempts": int(p.get("tackleattempts", 0) or 0),
        "saves": int(p.get("saves", 0) or 0),
        "goals_conceded": int(p.get("goalsconceded", 0) or 0),
        "ball_dive_saves": int(p.get("ballDiveSaves", 0) or 0),
        "cross_saves": int(p.get("crossSaves", 0) or 0),
        "good_direction_saves": int(p.get("goodDirectionSaves", 0) or 0),
        "parry_saves": int(p.get("parrySaves", 0) or 0),
        "punch_saves": int(p.get("punchSaves", 0) or 0),
        "reflex_saves": int(p.get("reflexSaves", 0) or 0),
        "clean_sheets_any": int(p.get("cleansheetsany", 0) or 0),
        "clean_sheets_def": int(p.get("cleansheetsdef", 0) or 0),
        "clean_sheets_gk": int(p.get("cleansheetsgk", 0) or 0),
        "red_cards": int(p.get("redcards", 0) or 0),
        "mom": int(p.get("mom", 0) or 0),
        "seconds_played": int(p.get("secondsPlayed", 0) or 0),
        "game_time": int(p.get("gameTime", 0) or 0),
        "realtime_game": int(p.get("realtimegame", 0) or 0),
        "realtime_idle": int(p.get("realtimeidle", 0) or 0),
        "match_result": result_letter,
        "our_team_size": our_player_count,
        "opponent_team_size": opponent_player_count,
        "team_size_difference": our_player_count - opponent_player_count,
        "user_result": p.get("userResult", ""),
        "vpro_attr": p.get("vproattr", ""),
        "vpro_hack_reason": p.get("vprohackreason", ""),
        "namespace": p.get("namespace", ""),
        "score": p.get("SCORE", ""),
        "match_aggregate_0": str(p.get("match_event_aggregate_0", "")),
        "match_aggregate_1": str(p.get("match_event_aggregate_1", "")),
        "match_aggregate_2": str(p.get("match_event_aggregate_2", "")),
        "match_aggregate_3": str(p.get("match_event_aggregate_3", "")),
        "data_fetched_at": fetched_at,
    }


def process_matches(raw_matches_by_type: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Flatten raw EA match JSON into dual-perspective matches / player_matches
    tables — one row per club per match (is_our_club True/False), same shape
    mpl_palace_scraper.py already proved out, generalized across EA's three
    match-query buckets (league/playoff/friendly) instead of friendly-only.

    Keeping both perspectives in one table is what lets a single match-detail
    view show both rosters without a second table or a second fetch.
    """
    processed_matches = []
    processed_player_matches = []
    fetched_at = datetime.now().isoformat()
    club_id = config.CLUB_ID
    club_name = config.CLUB_NAME

    for ea_match_type, matches in raw_matches_by_type.items():
        for match in matches:
            if club_id not in match.get("clubs", {}):
                continue

            our_club_data = match["clubs"][club_id]
            opponent_club_id = next((cid for cid in match["clubs"] if cid != club_id), None)
            opponent_club_name = "Unknown"
            if opponent_club_id:
                opponent_club_name = (
                    match["clubs"][opponent_club_id].get("details", {}).get("name", f"Club_{opponent_club_id}")
                )

            our_player_count = len(match.get("players", {}).get(club_id, {}))
            opponent_player_count = len(match.get("players", {}).get(opponent_club_id, {})) if opponent_club_id else 0
            our_result = _ea_result_letter(our_club_data)

            processed_matches.append(_match_row(
                match, club_id, our_club_data, True, opponent_club_id, opponent_club_name,
                our_player_count, opponent_player_count, ea_match_type, fetched_at,
            ))

            if opponent_club_id and opponent_club_id in match["clubs"]:
                opp_club_data = match["clubs"][opponent_club_id]
                processed_matches.append(_match_row(
                    match, opponent_club_id, opp_club_data, False, club_id, club_name,
                    opponent_player_count, our_player_count, ea_match_type, fetched_at,
                ))

            for player_id, p in match.get("players", {}).get(club_id, {}).items():
                processed_player_matches.append(_player_row(
                    match, club_id, club_name, player_id, p, True, ea_match_type,
                    our_player_count, opponent_player_count, our_result, fetched_at,
                ))

            if opponent_club_id:
                opp_result = "L" if our_result == "W" else "W" if our_result == "L" else "D"
                for player_id, p in match.get("players", {}).get(opponent_club_id, {}).items():
                    processed_player_matches.append(_player_row(
                        match, opponent_club_id, opponent_club_name, player_id, p, False, ea_match_type,
                        opponent_player_count, our_player_count, opp_result, fetched_at,
                    ))

    return pd.DataFrame(processed_matches), pd.DataFrame(processed_player_matches)


def merge_and_dedupe(existing: pd.DataFrame, new: pd.DataFrame, key: list[str], sort_col: str) -> pd.DataFrame:
    """Append new rows, drop duplicate keys (keep earliest capture), re-sort.
    `key` may be a single column or several (e.g. matchId + club_id, since the
    dual-perspective schema has two match rows sharing a matchId)."""
    if existing.empty:
        return new.sort_values(sort_col, ascending=False).reset_index(drop=True)
    if new.empty:
        return existing

    existing = existing.copy()
    new = new.copy()
    for col in key:
        existing[col] = existing[col].astype(str).str.strip()
        new[col] = new[col].astype(str).str.strip()

    combined = pd.concat([existing, new], ignore_index=True)
    combined = combined.sort_values("data_fetched_at", ascending=True)
    combined = combined.drop_duplicates(subset=key, keep="first").reset_index(drop=True)
    combined = combined.sort_values(sort_col, ascending=False).reset_index(drop=True)
    return combined


def upsert_match_tags(storage, new_matches_df: pd.DataFrame) -> None:
    """Auto-tag EA's own league/playoff matches as 'League'; flag friendlies
    for manual review. Never touches a matchId that's already tagged.
    Tags are per-match (not per-perspective), so only look at our own rows."""
    tags_df = storage.read_csv(config.TABLE_MATCH_TAGS, dtype=str)
    if tags_df.empty:
        tags_df = pd.DataFrame(columns=["matchId", "date_str", "Match_Type", "Exclude",
                                         "Goals_For", "Goals_Against", "Score_Override"])
    known_ids = set(tags_df["matchId"].astype(str).str.strip()) if not tags_df.empty else set()

    our_rows = new_matches_df[new_matches_df["is_our_club"] == True]  # noqa: E712
    new_rows = []
    for _, row in our_rows.iterrows():
        mid = str(row["matchId"]).strip()
        if mid in known_ids:
            continue
        if row["match_type"] == "league":
            tag = config.MATCH_TAG_LEAGUE
        elif row["match_type"] == "playoff":
            tag = config.MATCH_TAG_PLAYOFF
        else:
            tag = config.MATCH_TAG_NEEDS_REVIEW
        new_rows.append({
            "matchId": mid,
            "date_str": row["date"],
            "Match_Type": tag,
            "Exclude": "FALSE",
            "Goals_For": "",
            "Goals_Against": "",
            "Score_Override": "FALSE",
        })

    if new_rows:
        tags_df = pd.concat([tags_df, pd.DataFrame(new_rows)], ignore_index=True)
        storage.write_csv(config.TABLE_MATCH_TAGS, tags_df)
        n_review = sum(1 for r in new_rows if r["Match_Type"] == config.MATCH_TAG_NEEDS_REVIEW)
        print(f"✅ match_tags: added {len(new_rows)} new matches ({n_review} need manual review)")


def upsert_archetype_observations(storage, new_player_matches_df: pd.DataFrame) -> None:
    """Record any archetype ids we haven't seen before, with one example
    player/position, so the Tag Matches page can prompt you to name them.
    Restricted to our own roster — that's the only group the Player Stats
    page displays archetypes for."""
    if new_player_matches_df.empty:
        return
    our_rows = new_player_matches_df[new_player_matches_df["is_our_club"] == True]  # noqa: E712
    if our_rows.empty:
        return
    arche_df = storage.read_csv(config.TABLE_ARCHETYPE_MAP, dtype=str)
    if arche_df.empty:
        arche_df = pd.DataFrame(columns=["archetype_id", "archetype_name", "example_player",
                                          "example_position", "first_seen"])
    known_ids = set(arche_df["archetype_id"].astype(str)) if not arche_df.empty else set()

    new_rows = []
    seen_this_run = set()
    for _, row in our_rows.iterrows():
        aid = str(row.get("archetype_id", "")).strip()
        if not aid or aid in known_ids or aid in seen_this_run:
            continue
        seen_this_run.add(aid)
        new_rows.append({
            "archetype_id": aid,
            "archetype_name": "",
            "example_player": row["player_name"],
            "example_position": row["position"],
            "first_seen": row["date"],
        })

    if new_rows:
        arche_df = pd.concat([arche_df, pd.DataFrame(new_rows)], ignore_index=True)
        storage.write_csv(config.TABLE_ARCHETYPE_MAP, arche_df)
        print(f"✅ archetype_map: {len(new_rows)} new archetype id(s) seen — name them in the Tag Matches page")


def save_club_snapshot(storage, club_overall_stats, club_info) -> None:
    """Keep every run's overall-stats snapshot (skill rating, record) so we
    can chart it over time later — append-only, one row per collector run."""
    if not club_overall_stats:
        return
    stats = club_overall_stats[0] if isinstance(club_overall_stats, list) else club_overall_stats
    name = config.CLUB_NAME
    if club_info and config.CLUB_ID in club_info:
        name = club_info[config.CLUB_ID].get("name", name)

    snap = {
        "fetched_at": datetime.now().isoformat(),
        "club_name": name,
        "skill_rating": stats.get("skillRating"),
        "wins": stats.get("wins"),
        "losses": stats.get("losses"),
        "ties": stats.get("ties"),
        "games_played": stats.get("gamesPlayed"),
        "games_played_playoff": stats.get("gamesPlayedPlayoff"),
        "goals": stats.get("goals"),
        "goals_against": stats.get("goalsAgainst"),
        "wstreak": stats.get("wstreak"),
        "unbeaten_streak": stats.get("unbeatenstreak"),
    }
    existing = storage.read_csv("club_snapshot.csv")
    combined = pd.concat([existing, pd.DataFrame([snap])], ignore_index=True) if not existing.empty else pd.DataFrame([snap])
    storage.write_csv("club_snapshot.csv", combined)


def save_member_stats(storage, member_stats: dict) -> None:
    """Current roster snapshot (season-to-date totals) — replaced each run."""
    if not member_stats or "members" not in member_stats:
        return
    df = pd.DataFrame(member_stats["members"])
    df["data_fetched_at"] = datetime.now().isoformat()
    storage.write_csv("member_stats.csv", df)


def run():
    storage = get_storage()

    raw = fetch_all_raw()

    new_matches_df, new_player_matches_df = process_matches(raw["matches"])
    print(f"✅ Parsed {len(new_matches_df)} matches / {len(new_player_matches_df)} player-match rows this run")

    if new_matches_df.empty:
        print("⚠️  No matches parsed — EA returned nothing usable this run. Not touching stored data.")
        return

    existing_matches = storage.read_csv(config.TABLE_MATCHES, dtype={"matchId": str, "club_id": str})
    existing_player_matches = storage.read_csv(config.TABLE_PLAYER_MATCHES, dtype={"matchId": str, "club_id": str})

    # Two rows per match (is_our_club True/False) share a matchId, so the
    # dedupe key needs club_id too; player rows need player_id on top of that.
    final_matches = merge_and_dedupe(existing_matches, new_matches_df, key=["matchId", "club_id"], sort_col="timestamp")
    final_player_matches = merge_and_dedupe(existing_player_matches, new_player_matches_df,
                                             key=["matchId", "club_id", "player_id"], sort_col="timestamp")

    existing_match_ids = set(existing_matches["matchId"].astype(str).str.strip()) if not existing_matches.empty else set()
    final_match_ids = set(final_matches["matchId"].astype(str).str.strip())
    n_new_matches = len(final_match_ids - existing_match_ids)

    storage.write_csv(config.TABLE_MATCHES, final_matches)
    storage.write_csv(config.TABLE_PLAYER_MATCHES, final_player_matches)
    print(f"✅ matches.csv: {len(final_match_ids)} unique matches, {len(final_matches)} rows ({n_new_matches} new matches)")
    print(f"✅ player_matches.csv: {len(final_player_matches)} rows")

    # Only tag/observe truly-new matches, not the whole re-fetched window.
    truly_new_matches = new_matches_df[~new_matches_df["matchId"].astype(str).str.strip().isin(existing_match_ids)]
    truly_new_player_matches = new_player_matches_df[
        new_player_matches_df["matchId"].astype(str).str.strip().isin(truly_new_matches["matchId"].astype(str).str.strip())
    ]

    upsert_match_tags(storage, truly_new_matches)
    upsert_archetype_observations(storage, truly_new_player_matches)
    save_club_snapshot(storage, raw.get("club_overall_stats"), raw.get("club_info"))
    save_member_stats(storage, raw.get("member_stats"))

    print("✅ Collector run complete.")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(f"❌ Collector failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
