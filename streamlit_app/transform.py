"""
Shared data-shaping layer: tags + overrides + derived stats.

This is a straight port of the logic already proven out in palace/app.R
(PK phantom-goal correction, quit-game filtering, player aggregates) onto the
new canonical tables, plus the new League/Comp/All filter and the form/streak
helpers the new app adds.
"""
from __future__ import annotations

import pandas as pd

import config

FULL_ET_SECONDS = 6800  # app.R's threshold for "this went to penalties"


def _as_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin(["true", "1", "yes"])


def load_tagged_matches(storage) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read matches + player_matches, join match_tags and player_overrides,
    apply the PK clean-score correction. Returns (matches, player_matches)
    from OUR club's perspective only (is_our_club == True) — this is the
    "our record" view every page but Match History works from. Filtering by
    tag/exclude happens in filter_by_group so callers can still see the full
    picture if they want it.

    The raw table also holds an opponent-perspective row per match (and that
    club's roster) — see get_match_rosters() for pulling both sides of a
    single match for the match-detail view.
    """
    matches = storage.read_csv(config.TABLE_MATCHES, dtype={"matchId": str})
    player_matches = storage.read_csv(config.TABLE_PLAYER_MATCHES, dtype={"matchId": str})
    if matches.empty:
        return matches, player_matches

    if "is_our_club" in matches.columns:
        matches = matches[matches["is_our_club"].astype(str).str.strip().str.lower() == "true"].copy()
    if "is_our_club" in player_matches.columns:
        player_matches = player_matches[
            player_matches["is_our_club"].astype(str).str.strip().str.lower() == "true"
        ].copy()

    tags = storage.read_csv(config.TABLE_MATCH_TAGS, dtype=str)
    if not tags.empty:
        tags = tags.copy()
        tags["matchId"] = tags["matchId"].astype(str).str.strip()
        for col in ("Goals_For", "Goals_Against"):
            if col not in tags.columns:
                tags[col] = ""
        if "Score_Override" not in tags.columns:
            tags["Score_Override"] = "FALSE"
        if "Exclude" not in tags.columns:
            tags["Exclude"] = "FALSE"

        tags_subset = tags[["matchId", "Match_Type", "Exclude", "Score_Override",
                             "Goals_For", "Goals_Against"]].drop_duplicates(subset="matchId")
        matches = matches.merge(tags_subset, on="matchId", how="left")
        player_matches = player_matches.merge(
            tags[["matchId", "Match_Type"]].drop_duplicates(subset="matchId"), on="matchId", how="left"
        )
    else:
        matches["Match_Type"] = pd.NA
        matches["Exclude"] = "FALSE"
        matches["Score_Override"] = "FALSE"
        matches["Goals_For"] = ""
        matches["Goals_Against"] = ""
        player_matches["Match_Type"] = pd.NA

    # Matches with no tag row yet (shouldn't happen once the collector's
    # auto-tagging runs, but keep this failsafe) default to Needs Review.
    matches["Match_Type"] = matches["Match_Type"].fillna(config.MATCH_TAG_NEEDS_REVIEW)
    player_matches["Match_Type"] = player_matches["Match_Type"].fillna(config.MATCH_TAG_NEEDS_REVIEW)

    # Score override: a manually-corrected final score replaces goals_for/against.
    has_override = _as_bool(matches["Score_Override"]) & matches["Goals_For"].astype(str).str.strip().ne("")
    matches.loc[has_override, "goals_for"] = pd.to_numeric(matches.loc[has_override, "Goals_For"], errors="coerce")
    matches.loc[has_override, "goals_against"] = pd.to_numeric(matches.loc[has_override, "Goals_Against"], errors="coerce")

    # PK phantom-goal correction (app.R parity): EA adds a +1 phantom goal to
    # the penalty-shootout winner. We keep the real W/L result but clean the
    # goal tallies so per-game scoring averages aren't inflated by shootouts.
    if "seconds_played" in player_matches.columns and not player_matches.empty:
        max_secs = (
            player_matches.assign(seconds_played=pd.to_numeric(player_matches["seconds_played"], errors="coerce"))
            .groupby("matchId")["seconds_played"].max()
        )
        matches = matches.merge(max_secs.rename("max_seconds"), on="matchId", how="left")
    else:
        matches["max_seconds"] = pd.NA

    gf = pd.to_numeric(matches["goals_for"], errors="coerce")
    ga = pd.to_numeric(matches["goals_against"], errors="coerce")
    is_pk = matches["max_seconds"].notna() & (matches["max_seconds"] >= FULL_ET_SECONDS) & (gf != ga)
    matches["is_penalty_game"] = is_pk
    matches["clean_goals_for"] = gf.where(~(is_pk & (gf > ga)), gf - 1)
    matches["clean_goals_against"] = ga.where(~(is_pk & (ga > gf)), ga - 1)

    matches["clean_result"] = pd.Series("D", index=matches.index)
    matches.loc[gf > ga, "clean_result"] = "W"
    matches.loc[gf < ga, "clean_result"] = "L"

    # Player overrides (manual stat corrections / exclusions for a bad capture).
    overrides = storage.read_csv(config.TABLE_PLAYER_OVERRIDES, dtype=str)
    if not overrides.empty:
        overrides = overrides.copy()
        overrides["matchId"] = overrides["matchId"].astype(str).str.strip()
        overrides["player_name"] = overrides["player_name"].astype(str).str.strip()
        player_matches["player_name"] = player_matches["player_name"].astype(str).str.strip()

        override_fields = ["rating", "passes_made", "pass_attempts", "goals",
                            "assists", "shots", "tackles_made", "red_cards"]
        present = [f for f in override_fields if f in overrides.columns]
        if present:
            ov = overrides[["matchId", "player_name"] + present].rename(
                columns={f: f"{f}_ov" for f in present}
            )
            player_matches = player_matches.merge(ov, on=["matchId", "player_name"], how="left")
            for f in present:
                ov_col = f"{f}_ov"
                mask = player_matches[ov_col].notna() & player_matches[ov_col].astype(str).str.strip().ne("")
                player_matches.loc[mask, f] = pd.to_numeric(player_matches.loc[mask, ov_col], errors="coerce")
                player_matches.drop(columns=[ov_col], inplace=True)

        if "exclude" in overrides.columns:
            excl = overrides[_as_bool(overrides["exclude"])][["matchId", "player_name"]]
            if not excl.empty:
                excl["_x"] = True
                player_matches = player_matches.merge(excl, on=["matchId", "player_name"], how="left")
                player_matches = player_matches[player_matches["_x"] != True].drop(columns=["_x"])  # noqa: E712

    return matches, player_matches


def get_match_rosters(storage, match_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Both rosters for one match, straight from the raw dual-perspective
    table — used by the Match History detail view. Returns (our_players,
    opponent_players)."""
    player_matches = storage.read_csv(config.TABLE_PLAYER_MATCHES, dtype={"matchId": str})
    if player_matches.empty:
        return pd.DataFrame(), pd.DataFrame()
    rows = player_matches[player_matches["matchId"].astype(str).str.strip() == str(match_id).strip()]
    is_ours = rows["is_our_club"].astype(str).str.strip().str.lower() == "true"
    return rows[is_ours].copy(), rows[~is_ours].copy()


def filter_by_group(matches: pd.DataFrame, player_matches: pd.DataFrame, group: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply the League / Comp / All toggle, and drop Exclude-tagged games."""
    if matches.empty:
        return matches, player_matches

    not_excluded = ~_as_bool(matches.get("Exclude", pd.Series("FALSE", index=matches.index)))
    allowed_tags = config.FILTER_GROUPS.get(group, config.FILTER_GROUPS["All"])
    keep_matches = matches[not_excluded & matches["Match_Type"].isin(allowed_tags)].copy()

    keep_ids = set(keep_matches["matchId"])
    keep_players = player_matches[player_matches["matchId"].isin(keep_ids)].copy() if not player_matches.empty else player_matches
    return keep_matches, keep_players


def drop_quit_games(player_matches: pd.DataFrame) -> pd.DataFrame:
    """Same heuristic as app.R: a 3.0 rating with 0/0 passing is a lag-out /
    disconnect, not a real performance — drop it from aggregates only."""
    if player_matches.empty:
        return player_matches
    rating = pd.to_numeric(player_matches["rating"], errors="coerce")
    pm = pd.to_numeric(player_matches["passes_made"], errors="coerce")
    pa = pd.to_numeric(player_matches["pass_attempts"], errors="coerce")
    quit_mask = (rating == 3.0) & (pm == 0) & (pa == 0)
    return player_matches[~quit_mask]


def compute_player_aggregates(player_matches: pd.DataFrame) -> pd.DataFrame:
    """Per-player season totals/averages — same metric set as app.R's
    calculate_player_stats()."""
    if player_matches.empty:
        return pd.DataFrame()

    df = drop_quit_games(player_matches).copy()
    for col in ["rating", "goals", "assists", "passes_made", "pass_attempts",
                "shots", "tackles_made", "red_cards"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    def _agg(g: pd.DataFrame) -> pd.Series:
        n = len(g)
        wins = int((g["match_result"] == "W").sum())
        made = g["passes_made"].sum()
        att = g["pass_attempts"].sum()
        goals = g["goals"].sum()
        shots = g["shots"].sum()
        return pd.Series({
            "games_played": n,
            "wins": wins,
            "win_pct": round(wins / n * 100, 1) if n else 0,
            "rating": g["rating"].mean(),
            "goals": goals,
            "assists": g["assists"].sum(),
            "ga_per_game": (goals + g["assists"].sum()) / n if n else 0,
            "passes_made_per_game": made / n if n else 0,
            "pass_success_rate": round(made / att * 100, 1) if att > 0 else 0,
            "shots_per_game": shots / n if n else 0,
            "shot_conversion_rate": round(goals / shots * 100, 1) if shots > 0 else 0,
            "tackles_made_per_game": g["tackles_made"].sum() / n if n else 0,
            "red_card_rate": g["red_cards"].sum() / n * 100 if n else 0,
        })

    out = df.groupby("player_name").apply(_agg, include_groups=False).reset_index()
    return out.sort_values("rating", ascending=False).reset_index(drop=True)


def rating_status(rating: float) -> str:
    """Bucket a rating into the fixed status palette (dataviz skill) for the
    FotMob-style colored chip."""
    if rating is None or pd.isna(rating):
        return "neutral"
    if rating >= 7.5:
        return "good"
    if rating >= 6.8:
        return "warning"
    if rating >= 6.0:
        return "serious"
    return "critical"


def rating_color(rating: float) -> str:
    bucket = rating_status(rating)
    return config.RATING_STATUS.get(bucket, config.RATING_NEUTRAL)


def compute_form(matches: pd.DataFrame, n: int = 10) -> dict:
    """Last-N form: ordered results (oldest->newest for left-to-right
    reading), current streak, and points-per-game trend."""
    if matches.empty:
        return {"results": [], "streak_type": None, "streak_len": 0, "ppg": 0.0, "record": "0-0-0"}

    recent = matches.sort_values("timestamp", ascending=False).head(n)
    recent = recent.sort_values("timestamp", ascending=True)
    results = recent["clean_result"].tolist()

    streak_type, streak_len = None, 0
    for r in reversed(results):
        if streak_type is None:
            streak_type, streak_len = r, 1
        elif r == streak_type:
            streak_len += 1
        else:
            break

    wins = results.count("W")
    draws = results.count("D")
    losses = results.count("L")
    pts = wins * 3 + draws
    ppg = pts / len(results) if results else 0.0

    return {
        "results": results,
        "streak_type": streak_type,
        "streak_len": streak_len,
        "ppg": round(ppg, 2),
        "record": f"{wins}-{draws}-{losses}",
    }


def build_win_shares_inputs(matches: pd.DataFrame, player_matches: pd.DataFrame,
                            opponent_club_stats: pd.DataFrame, archetype_map: pd.DataFrame = None) -> pd.DataFrame:
    """Assemble the flat table the win-shares model will eventually train on:
    one row per player-match with position, archetype, our/opponent team
    size, the opponent's season win%, and the match result. The weighting
    logic itself (how much each factor should move a player's 'win share')
    is still TBD — this just guarantees every input the model needs is
    already joined and available once that logic is designed.
    """
    if matches.empty or player_matches.empty:
        return pd.DataFrame()

    base = matches[["matchId", "opponent_club_id", "clean_result", "our_player_count", "opponent_player_count"]]
    df = player_matches.merge(base, on="matchId", how="inner")

    if opponent_club_stats is not None and not opponent_club_stats.empty:
        opp = opponent_club_stats[["club_id", "win_pct"]].rename(
            columns={"club_id": "opponent_club_id", "win_pct": "opponent_win_pct"}
        )
        opp["opponent_club_id"] = opp["opponent_club_id"].astype(str)
        df["opponent_club_id"] = df["opponent_club_id"].astype(str)
        df = df.merge(opp, on="opponent_club_id", how="left")
    else:
        df["opponent_win_pct"] = pd.NA

    if archetype_map is not None and not archetype_map.empty and "archetype_id" in df.columns:
        amap = archetype_map[["archetype_id", "archetype_name"]].copy()
        amap["archetype_id"] = amap["archetype_id"].astype(str)
        df["archetype_id"] = df["archetype_id"].astype(str)
        df = df.merge(amap, on="archetype_id", how="left")
        df["archetype"] = df["archetype_name"].fillna(df["archetype_id"].map(lambda a: f"id {a}" if a else ""))
        df.drop(columns=["archetype_name"], inplace=True)
    else:
        df["archetype"] = df.get("archetype_id", "")

    cols = ["matchId", "player_name", "position", "archetype", "clean_result", "our_player_count",
            "opponent_player_count", "opponent_win_pct", "rating", "goals", "assists"]
    return df[[c for c in cols if c in df.columns]]


# --- Percentile coloring: continuous red -> neutral -> green ----------------
# A percentile is a relative-rank judgment (where does this value sit among
# peers), so it gets a continuous gradient centered on the 50th percentile —
# distinct from rating_color() above, which is an absolute 0-10 judgment
# against fixed thresholds (the FotMob-style chip) and stays a discrete
# good/warning/serious/critical bucket. Same three fixed status hues as
# endpoints either way — critical red at 0, neutral gray at 50, good green
# at 100 — just interpolated smoothly here instead of bucketed.

def _hex_to_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lerp_rgb(c1: tuple, c2: tuple, t: float) -> tuple:
    return tuple(round(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _percentile_rgb(pct: float) -> tuple:
    pct = max(0.0, min(100.0, pct))
    red = _hex_to_rgb(config.RATING_STATUS["critical"])
    neutral = _hex_to_rgb(config.RATING_NEUTRAL)
    good = _hex_to_rgb(config.RATING_STATUS["good"])
    if pct <= 50:
        return _lerp_rgb(red, neutral, pct / 50)
    return _lerp_rgb(neutral, good, (pct - 50) / 50)


def percentile_color(pct: float) -> str:
    """Solid hex for a percentile value (0-100) — used for the scouting
    report's bar fill, where a solid, fully-saturated color needs to read
    clearly against the page."""
    if pct is None or pd.isna(pct):
        return config.RATING_NEUTRAL
    r, g, b = _percentile_rgb(pct)
    return f"#{r:02x}{g:02x}{b:02x}"


def tier_bg_style(value, series: pd.Series, higher_is_better: bool = True, max_alpha: float = 0.35) -> str:
    """CSS background tint for one table cell, on the same red->neutral->green
    scale. Alpha scales with distance from the 50th percentile, so a value
    near the middle gets a barely-there tint and one near either extreme
    gets a visibly stronger one — every quartile leans the right direction,
    not just a top/bottom quarter cut with an untinted middle half."""
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if pd.isna(value) or len(clean) < 4:
        return ""
    pct_rank = (clean <= value).mean() * 100  # 0-100, fraction of the field at or below this value
    if not higher_is_better:
        pct_rank = 100 - pct_rank

    r, g, b = _percentile_rgb(pct_rank)
    alpha = abs(pct_rank - 50) / 50 * max_alpha
    return f"background-color: rgba({r},{g},{b},{alpha:.2f});"


# --- FBref-style percentile scouting report -----------------------------------
# Ported from app.R's calculate_player_radar_stats() / calculate_player_percentiles():
# one row per stat, each showing this player's value and the % of a
# comparison pool (our roster + every scouted opponent's roster) they rank
# above. Shot conversion is new here (not in the original R version).

FBREF_STATS = [
    ("pass_completion_pct", "Pass Completion %"),
    ("passes_per_game", "Passes Made/Game"),
    ("goals_per_game", "Goals/Game"),
    ("assists_per_game", "Assists/Game"),
    ("shots_per_game", "Shots/Game"),
    ("shot_conversion_pct", "Shot Conversion %"),
    ("tackles_per_game", "Tackles/Game"),
    ("avg_rating", "Avg Rating"),
    ("win_rate", "Win Rate %"),
]


def calculate_player_radar_stats(player_rows: pd.DataFrame) -> dict:
    """This player's per-game rates from their own match log."""
    if player_rows.empty:
        return {}
    n = len(player_rows)
    passes_made = pd.to_numeric(player_rows["passes_made"], errors="coerce").sum()
    pass_attempts = pd.to_numeric(player_rows["pass_attempts"], errors="coerce").sum()
    goals = pd.to_numeric(player_rows["goals"], errors="coerce").sum()
    shots = pd.to_numeric(player_rows["shots"], errors="coerce").sum()
    return {
        "pass_completion_pct": made_pct(passes_made, pass_attempts),
        "passes_per_game": passes_made / n,
        "goals_per_game": goals / n,
        "assists_per_game": pd.to_numeric(player_rows["assists"], errors="coerce").sum() / n,
        "shots_per_game": shots / n,
        "shot_conversion_pct": made_pct(goals, shots),
        "tackles_per_game": pd.to_numeric(player_rows["tackles_made"], errors="coerce").sum() / n,
        "avg_rating": pd.to_numeric(player_rows["rating"], errors="coerce").mean(),
        "win_rate": (player_rows["match_result"] == "W").mean() * 100,
    }


def made_pct(made, attempts) -> float:
    made, attempts = float(made or 0), float(attempts or 0)
    return (made / attempts * 100) if attempts > 0 else 0.0


def filter_by_position(player_matches_df: pd.DataFrame, position_group: str) -> pd.DataFrame:
    """Restrict to rows played in one position group. 'All' means all
    OUTFIELD positions — goalkeeper rows are always dropped (not enough
    keeper games logged to be useful, and they'd skew a field player's
    aggregate stats on the rare match someone plays keeper). Matches the
    per-match `position` field EA gives us — the same string for both our
    own rows and the opponent-perspective rows in this table."""
    if player_matches_df.empty or "position" not in player_matches_df.columns:
        return player_matches_df
    df = player_matches_df[player_matches_df["position"].str.lower() != "goalkeeper"]
    if position_group == "All":
        return df
    return df[df["position"].str.lower() == position_group.lower()]


def build_pool_from_player_matches(player_matches_df: pd.DataFrame, min_games: int = 3) -> pd.DataFrame:
    """One row per player with their per-game rates — works on any
    player_matches subset with the same schema: our own roster, or the
    opponent-perspective rows from games played against us."""
    if player_matches_df.empty:
        return pd.DataFrame()
    rows = []
    for name, g in player_matches_df.groupby("player_name"):
        if len(g) < min_games:
            continue
        stats = calculate_player_radar_stats(g)
        stats["player_name"] = name
        rows.append(stats)
    return pd.DataFrame(rows)


def build_season_totals_pool(opponent_player_stats: pd.DataFrame, min_games: int = 5,
                              position_group: str = "All") -> pd.DataFrame:
    """The broad pool: every scouted opponent's EA season-to-date totals
    (not just games played against us). Position filtering here uses each
    player's self-reported `favoritePosition` — their usual position, not
    necessarily the one they played in any given match, so it's a looser
    filter than the per-match `position` field used elsewhere."""
    if opponent_player_stats is None or opponent_player_stats.empty:
        return pd.DataFrame()

    opp = opponent_player_stats.copy()
    if "favoritePosition" in opp.columns:
        # Same rule as filter_by_position: "All" still means all outfield positions.
        opp = opp[opp["favoritePosition"].astype(str).str.lower() != "goalkeeper"]
        if position_group != "All":
            opp = opp[opp["favoritePosition"].astype(str).str.lower() == position_group.lower()]

    opp["gamesPlayed"] = pd.to_numeric(opp["gamesPlayed"], errors="coerce").fillna(0)
    opp = opp[opp["gamesPlayed"] >= min_games]

    rows = []
    for _, r in opp.iterrows():
        games = r["gamesPlayed"]
        if games <= 0:
            continue
        goals = float(r.get("goals", 0) or 0)
        shot_success = pd.to_numeric(r.get("shotSuccessRate"), errors="coerce")
        # EA gives season totals, not a raw shot count, for opponents —
        # back-solve an implied shots-per-game from goals and their own
        # shot-success%, same approximation app.R used (shotSuccessRate is
        # already goals/shots, so it doubles as shot_conversion_pct with no
        # back-solving needed for that one specifically).
        shots_per_game = (goals / (shot_success / 100) / games) if pd.notna(shot_success) and shot_success > 0 else 0
        rows.append({
            "player_name": r.get("name", "Unknown"),
            "pass_completion_pct": pd.to_numeric(r.get("passSuccessRate"), errors="coerce") or 0,
            "passes_per_game": float(r.get("passesMade", 0) or 0) / games,
            "goals_per_game": goals / games,
            "assists_per_game": float(r.get("assists", 0) or 0) / games,
            "shots_per_game": shots_per_game,
            "shot_conversion_pct": shot_success if pd.notna(shot_success) else 0,
            "tackles_per_game": float(r.get("tacklesMade", 0) or 0) / games,
            "avg_rating": pd.to_numeric(r.get("ratingAve"), errors="coerce") or 0,
            "win_rate": pd.to_numeric(r.get("winRate"), errors="coerce") or 0,
        })
    return pd.DataFrame(rows)


def _record_summary(group: pd.DataFrame) -> pd.Series:
    n = len(group)
    w = int((group["clean_result"] == "W").sum())
    d = int((group["clean_result"] == "D").sum())
    l = int((group["clean_result"] == "L").sum())
    return pd.Series({
        "games": n,
        "record": f"{w}-{d}-{l}",
        "win_pct": round(w / n * 100, 1) if n else 0,
        "ppg": round((w * 3 + d) / n, 2) if n else 0,
    })


def performance_by_opponent_tier(matches: pd.DataFrame, opponent_club_stats: pd.DataFrame, n_tiers: int = 3) -> pd.DataFrame:
    """Bucket opponents into tiers by their own season win % (terciles, so
    the bands reflect the actual spread of teams we've faced rather than
    arbitrary fixed cutoffs), then show our record against each tier."""
    if matches.empty or opponent_club_stats is None or opponent_club_stats.empty:
        return pd.DataFrame()

    opp = opponent_club_stats[["club_id", "win_pct"]].rename(columns={"win_pct": "opp_win_pct"}).copy()
    opp["club_id"] = opp["club_id"].astype(str)
    df = matches.copy()
    df["opponent_club_id"] = df["opponent_club_id"].astype(str)
    df = df.merge(opp, left_on="opponent_club_id", right_on="club_id", how="inner")
    if df.empty or df["opp_win_pct"].nunique() < 2:
        return pd.DataFrame()

    tier_labels = ["Lower tier", "Mid tier", "Upper tier"][:n_tiers]
    try:
        df["tier"], bins = pd.qcut(df["opp_win_pct"], q=n_tiers, labels=tier_labels, retbins=True, duplicates="drop")
    except ValueError:
        return pd.DataFrame()

    out = df.groupby("tier", observed=True).apply(_record_summary, include_groups=False).reset_index()
    # Drop the Categorical dtype now — groupby(observed=True) only computes
    # rows for tiers that actually have data, but the resulting column still
    # carries ALL of tier_labels as its .categories, and Series.map() on a
    # Categorical maps over .categories (every possible label), not just the
    # labels actually present. With a small/lopsided slice (e.g. filtering to
    # "Comp" games) a tier can have zero matches, so .map() below would
    # KeyError looking up a range for a tier `ranges` never saw.
    out["tier"] = out["tier"].astype(str)

    # Label each tier with its actual win% range so "Upper tier" means something concrete.
    ranges = df.groupby("tier", observed=True)["opp_win_pct"].agg(["min", "max"])
    out["tier"] = out["tier"].map(lambda t: f"{t} ({ranges.loc[t, 'min']:.0f}-{ranges.loc[t, 'max']:.0f}% win)")
    return out


def performance_by_lineup_diff(matches: pd.DataFrame) -> pd.DataFrame:
    """Bucket matches by our lineup size minus the opponent's, then show our
    record in each situation (short-handed / even / a player up)."""
    if matches.empty or "player_count_difference" not in matches.columns:
        return pd.DataFrame()

    df = matches.copy()
    diff = pd.to_numeric(df["player_count_difference"], errors="coerce")

    def _bucket(d):
        if pd.isna(d):
            return None
        if d <= -2:
            return "Short 2+"
        if d == -1:
            return "Short 1"
        if d == 0:
            return "Even"
        if d == 1:
            return "Up 1"
        return "Up 2+"

    df["size_bucket"] = diff.map(_bucket)
    df = df.dropna(subset=["size_bucket"])
    if df.empty:
        return pd.DataFrame()

    out = df.groupby("size_bucket", observed=True).apply(_record_summary, include_groups=False).reset_index()
    order = ["Short 2+", "Short 1", "Even", "Up 1", "Up 2+"]
    out["_order"] = out["size_bucket"].map(order.index)
    return out.sort_values("_order").drop(columns="_order").reset_index(drop=True)


def calculate_percentiles(player_stats: dict, pool: pd.DataFrame) -> dict:
    """% of the comparison pool at or below this player's value, per stat —
    same definition as app.R (mean(pool$x <= player_stats$x) * 100)."""
    if pool.empty:
        return {}
    out = {}
    for key, _ in FBREF_STATS:
        if key not in pool.columns or key not in player_stats:
            continue
        col = pd.to_numeric(pool[key], errors="coerce").dropna()
        if col.empty:
            continue
        out[key] = round((col <= player_stats[key]).mean() * 100)
    return out
