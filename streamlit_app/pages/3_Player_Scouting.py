"""Player Scouting — FBref/FotMob-style percentile scouting report for one
of our players, filterable by position group.

Two different opponent comparison pools are offered because they trade off
against each other and there's no clearly-right default yet:
  - "Season Totals" (opponent_player_stats.csv) is a big pool — every
    scouted club's full roster — but position is each player's
    self-reported *usual* position (favoritePosition), not the position
    they played in any specific game, so the position-group filter here is
    approximate.
  - "Head-to-Head" uses the opponent rows already sitting in
    player_matches.csv — same per-match `position` field as our own data,
    so the position filter is exact — but the pool is only as big as the
    games we've actually played against them, which right now is small.
"""
import pandas as pd
import streamlit as st

import config
import transform
import ui_common as ui
from storage import get_storage

st.set_page_config(page_title="Player Scouting", page_icon="🔎", layout="wide")

group = ui.render_sidebar()
matches, player_matches = ui.load_filtered_data(group)

st.title("Player Scouting")
st.caption(f"Showing: **{group}** games")

if player_matches.empty:
    st.info("No player data yet. Run `python collector.py` first.")
    st.stop()

position_group = st.radio("Position group", options=config.POSITION_GROUPS, horizontal=True, key="scouting_pos_group")
our_scoped = transform.filter_by_position(player_matches, position_group)

# The player list is built from the FULL (position-unfiltered) roster, not
# `our_scoped` — otherwise switching position group changes which players
# are even selectable, and the selected one resets whenever they drop out
# of the new list. The natural flow is: pick a player once, then flip
# through position groups to see them at each one (showing a "no games at
# this position" message below if they have none there, rather than
# bouncing you to a different player).
all_outfield = transform.filter_by_position(player_matches, "All")
eligible_players = sorted(all_outfield["player_name"].unique())
if not eligible_players:
    st.caption("No one has logged a qualifying outfield game yet.")
    st.stop()

c1, c2 = st.columns([1, 2])
with c1:
    player_choice = st.selectbox("Player", options=eligible_players, key="scouting_player")
with c2:
    pool_choice = st.radio(
        "Comparison pool",
        options=["Our Squad only", "+ Head-to-Head (games vs us only)", "+ Season Totals (all scouted clubs)"],
        help=(
            "Season Totals = a big pool, but position is each opponent's usual position, not necessarily "
            "the one they played against us. Head-to-Head = exact per-game position, but a much smaller pool "
            "(only games we've actually played)."
        ),
    )

our_rows = our_scoped[our_scoped["player_name"] == player_choice]
player_stats = transform.calculate_player_radar_stats(our_rows)

if not player_stats:
    st.caption("Not enough games for this player at this position group yet.")
    st.stop()

storage = get_storage()
pool = transform.build_pool_from_player_matches(our_scoped, min_games=3)

if pool_choice.startswith("+ Season Totals"):
    opp_stats = storage.read_csv(config.TABLE_OPPONENT_PLAYER_STATS, dtype={"club_id": str})
    opp_pool = transform.build_season_totals_pool(opp_stats, min_games=5, position_group=position_group)
    pool = pd.concat([pool, opp_pool], ignore_index=True) if not opp_pool.empty else pool
elif pool_choice.startswith("+ Head-to-Head"):
    all_player_matches = storage.read_csv(config.TABLE_PLAYER_MATCHES, dtype={"matchId": str})
    opp_rows = all_player_matches[all_player_matches["is_our_club"].astype(str).str.lower() == "false"]
    opp_rows = transform.filter_by_position(opp_rows, position_group)
    # min_games=1 here on purpose: we've only played most clubs once so far,
    # so a per-player 3-game minimum (fine for our own roster, who all have
    # plenty of games) would zero out virtually every opponent and make this
    # pool collapse down to "Our Squad only" with nothing added.
    opp_pool = transform.build_pool_from_player_matches(opp_rows, min_games=1)
    pool = pd.concat([pool, opp_pool], ignore_index=True) if not opp_pool.empty else pool

percentiles = transform.calculate_percentiles(player_stats, pool)

if not percentiles:
    st.caption("Not enough comparison data yet — need more players with qualifying game counts.")
    st.stop()

rows = []
for key, label in transform.FBREF_STATS:
    if key not in percentiles:
        continue
    pct = percentiles[key]
    color = transform.percentile_color(pct)
    val = player_stats[key]
    val_str = f"{val:.1f}" if key not in ("goals_per_game", "assists_per_game") else f"{val:.2f}"
    rows.append(
        "<tr>"
        f"<td style='padding:4px 8px;width:35%;'>{label}</td>"
        f"<td style='padding:4px 8px;text-align:center;width:15%;'>{val_str}</td>"
        "<td style='padding:4px 8px;width:50%;'>"
        "<div style='display:flex;align-items:center;gap:6px;'>"
        f"<span style='min-width:26px;font-weight:700;font-size:12px;'>{pct}</span>"
        f"<div style='height:14px;width:{pct}%;max-width:100%;background:{color};border-radius:3px;'></div>"
        "</div></td></tr>"
    )

st.markdown(
    f"<p style='color:#898781;font-size:12px;'>Pool: {len(pool)} players"
    + (f" at {position_group}" if position_group != "All" else "") + "</p>"
    "<table style='width:100%;border-collapse:collapse;font-family:system-ui,-apple-system,sans-serif;font-size:13px;'>"
    "<thead><tr style='border-bottom:2px solid #c3c2b7;text-align:left;'>"
    "<th style='padding:4px 8px;'>Stat</th><th style='padding:4px 8px;'>Value</th>"
    "<th style='padding:4px 8px;'>Percentile</th></tr></thead>"
    f"<tbody>{''.join(rows)}</tbody></table>",
    unsafe_allow_html=True,
)
