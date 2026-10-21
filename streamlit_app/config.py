"""
Central configuration for the FC 27 Streamlit app.

Nothing here should need Playwright or Streamlit imports — this module is safe
to import from the collector, the transform layer, and every page.
"""
import os

# --- Club / platform -------------------------------------------------------
CLUB_ID = os.environ.get("FC_CLUB_ID", "23137")   # "Palace" — FC 27
PLATFORM = "common-gen5"
CLUB_NAME = "Palace"

API_BASE = "https://proclubs.ea.com/api/fc"
LANDING_URL = f"https://www.ea.com/games/ea-sports-fc/clubs/overview?clubId={CLUB_ID}&platform={PLATFORM}"

# EA caps maxResultCount at 10 per call (default is 5 if omitted).
MATCH_PAGE_SIZE = 10

def matches_url(match_type: str) -> str:
    return (f"{API_BASE}/clubs/matches?matchType={match_type}&platform={PLATFORM}"
            f"&clubIds={CLUB_ID}&maxResultCount={MATCH_PAGE_SIZE}")

def club_overall_stats_url(club_id: str) -> str:
    return f"{API_BASE}/clubs/overallStats?platform={PLATFORM}&clubIds={club_id}"

def club_info_url(club_id: str) -> str:
    return f"{API_BASE}/clubs/info?platform={PLATFORM}&clubIds={club_id}"

def member_stats_url(club_id: str) -> str:
    return f"{API_BASE}/members/stats?platform={PLATFORM}&clubId={club_id}"

def member_career_stats_url(club_id: str) -> str:
    return f"{API_BASE}/members/career/stats?platform={PLATFORM}&clubId={club_id}"

# EA's numeric matchType codes, observed live on this club (2026-10-14).
# Keep both directions — the raw API gives us the string query param on the
# way in, and an integer back in the payload on the way out.
MATCH_TYPE_QUERY = {
    "league": "leagueMatch",
    "playoff": "playoffMatch",
    "friendly": "friendlyMatch",
}
EA_MATCH_TYPE_CODE = {
    1: "league",
    2: "playoff",
    5: "friendly",
}

# --- Our own tagging layer ---------------------------------------------------
# EA's own ranked ladder ("leagueMatch") is tagged automatically — it's always
# "League" and needs no manual review.
#
# Everything EA calls "friendlyMatch" needs a human to say what it actually was,
# because this group plays its real competitive league (Next Pro, Jazz Night,
# MPL, etc.) through EA's friendly-match plumbing. Until tagged, a friendly
# defaults to NEEDS_REVIEW so it surfaces in the Tag Matches page.
MATCH_TAG_LEAGUE = "League"        # EA ranked league (auto)
MATCH_TAG_PLAYOFF = "Playoff"      # EA ranked playoffs (auto) — distinct from League, same ladder
MATCH_TAG_COMP = "Comp"            # our real competitive league, played as an EA "friendly"
MATCH_TAG_FRIENDLY = "Friendly"    # a true casual friendly
MATCH_TAG_CUP = "Cup"
MATCH_TAG_NEEDS_REVIEW = "Needs Review"
MATCH_TAG_EXCLUDE = "Exclude"      # quit / disconnected / bugged game — drop from stats

MATCH_TAG_CHOICES = [
    MATCH_TAG_LEAGUE, MATCH_TAG_PLAYOFF, MATCH_TAG_COMP, MATCH_TAG_FRIENDLY,
    MATCH_TAG_CUP, MATCH_TAG_EXCLUDE,
]

# Tags that count as "our competitive record" when the user picks the
# League / Comp / All filter in the app.
FILTER_GROUPS = {
    "League": [MATCH_TAG_LEAGUE, MATCH_TAG_PLAYOFF],
    "Comp": [MATCH_TAG_COMP],
    "All": [MATCH_TAG_LEAGUE, MATCH_TAG_PLAYOFF, MATCH_TAG_COMP, MATCH_TAG_FRIENDLY, MATCH_TAG_CUP],
}

# Position groups as EA's own per-match `position` field spells them —
# used to let Player Stats / Player Scouting compare like-for-like roles.
# Goalkeeper excluded on purpose: we don't have enough keeper games logged
# yet (and won't for a while) to make it a useful group — see
# filter_by_position(), which also drops any goalkeeper rows from "All" so
# a rare keeper appearance doesn't skew someone's outfield stats.
POSITION_GROUPS = ["All", "Defender", "Midfielder", "Forward"]

# --- Archetypes --------------------------------------------------------------
# EA does not publish archetypeid -> name mappings, and the ids are not simply
# numbered per position (we've observed e.g. id 4,5,6 appearing under both
# "defender" and "midfielder"). This table starts empty/unknown and is filled
# in by hand (Tag Matches / Player Stats page shows the raw id next to a
# player + position so you can cross-reference the archetype name shown in
# your own in-game Clubhouse and fill it in once).
KNOWN_ARCHETYPE_NAMES = {
    # Goalkeepers
    "Shot Stopper": None,
    "Sweeper Keeper": None,
    # Defenders
    "Progressor": None,
    "Boss": None,
    "Engine": None,
    "Marauder": None,
    # Midfielders
    "Recycler": None,
    "Maestro": None,
    "Creator": None,
    "Spark": None,
    "Disruptor": None,  # confirmed live (id 5) — not in the original public archetype list
    # Forwards
    "Magician": None,
    "Finisher": None,
    "Target": None,
}

# --- Data files --------------------------------------------------------------
# Logical table names used across storage backends (Local / Drive).
TABLE_MATCHES = "matches.csv"
TABLE_PLAYER_MATCHES = "player_matches.csv"
TABLE_MATCH_TAGS = "match_tags.csv"
TABLE_PLAYER_OVERRIDES = "player_overrides.csv"
TABLE_OPPONENT_CLUB_STATS = "opponent_club_stats.csv"
TABLE_OPPONENT_PLAYER_STATS = "opponent_player_stats.csv"
TABLE_ARCHETYPE_MAP = "archetype_map.csv"

# --- Visual status thresholds (dataviz skill: status palette, fixed) --------
# Used for the FotMob-style colored rating chip. A rating is a state judgement
# (great / fine / poor game), so it uses the reserved status colors rather
# than a sequential ramp.
RATING_STATUS = {
    "good": "#0ca30c",       # >= 7.5
    "warning": "#fab219",    # 6.8 - 7.49 (ok, unremarkable)
    "serious": "#ec835a",    # 6.0 - 6.79
    "critical": "#d03b3b",   # < 6.0
}
RATING_NEUTRAL = "#898781"   # muted ink — no rating / excluded game

# Player Stats quartile shading: one distinct hue per quartile at similar
# visual weight (yellow needs a stronger alpha to read as strongly as the
# others), plus purple for the leader in each stat.
# (label, hex, alpha) — bottom quartile first.
TIER_COLORS = [
    ("Bottom quartile", "#d03b3b", 0.42),
    ("2nd quartile", "#fab219", 0.55),
    ("3rd quartile", "#0ca30c", 0.38),
    ("Top quartile", "#2563eb", 0.40),
]
TIER_BEST = ("Best", "#7c3aed", 0.58)

RESULT_COLOR = {
    "W": RATING_STATUS["good"],
    "D": RATING_NEUTRAL,
    "L": RATING_STATUS["critical"],
}
