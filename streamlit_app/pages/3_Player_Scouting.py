"""Player Scouting — FBref/FotMob-style percentile scouting report for one
of our players, filterable by position group.

Three comparison pools:
  - "Our Squad" — our own players' per-game averages.
  - "vs. Opponents (Head to Head)" — how opposing players performed in games
    against us (opponent rows in player_matches.csv; exact per-match
    position). Each is a single game, so the pool is simulated N-game
    averages (transform.build_simulated_opponent_pool) to compare like
    with like.
  - "vs. All Players (Season Stats)" — our squad plus every scouted
    player's EA season stats (opponent_player_stats.csv): the big universe
    of players. Position there is each player's usual position
    (favoritePosition), so the position filter is approximate.
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
        options=["Our Squad", "vs. Opponents (Head to Head)", "vs. All Players (Season Stats)"],
        help=(
            "**Our Squad**: our own players.\n\n"
            "**vs. Opponents (Head to Head)**: compared to how opposing players at the same "
            "position performed against us.\n\n"
            "**vs. All Players (Season Stats)**: our squad plus every scouted player's EA season stats. "
            "Uses each player's reported primary position, so best used with **All** positions."
        ),
    )

our_rows = our_scoped[our_scoped["player_name"] == player_choice]
player_stats = transform.calculate_player_radar_stats(our_rows)

if not player_stats:
    st.caption("Not enough games for this player at this position group yet.")
    st.stop()

storage = get_storage()
pool = transform.build_pool_from_player_matches(our_scoped, min_games=3)

pool_note = f"Pool: {len(pool)} players"
if pool_choice == "vs. All Players (Season Stats)":
    opp_stats = storage.read_csv(config.TABLE_OPPONENT_PLAYER_STATS, dtype={"club_id": str})
    opp_pool = transform.build_season_totals_pool(opp_stats, min_games=5, position_group=position_group)
    pool = pd.concat([pool, opp_pool], ignore_index=True) if not opp_pool.empty else pool
    pool_note = f"Pool: {len(pool)} players (our squad + scouted season stats)"
elif pool_choice == "vs. Opponents (Head to Head)":
    all_player_matches = storage.read_csv(config.TABLE_PLAYER_MATCHES, dtype={"matchId": str})
    opp_rows = all_player_matches[all_player_matches["is_our_club"].astype(str).str.lower() == "false"]
    opp_rows = transform.drop_quit_games(transform.filter_by_position(opp_rows, position_group))
    n_games = len(transform.drop_quit_games(our_rows))
    pool = transform.build_simulated_opponent_pool(opp_rows, n_games)
    pool_note = f"Pool: {len(opp_rows)} opposing player-games vs us, compared over your {n_games} games"

percentiles = transform.calculate_percentiles(player_stats, pool)

if not percentiles:
    st.caption("Not enough comparison data yet — need more players with qualifying game counts.")
    st.stop()

rows = []
for key, label in transform.FBREF_STATS:
    if key not in player_stats:
        continue
    val = player_stats[key]
    val_str = f"{val:.1f}" if key not in ("goals_per_game", "assists_per_game") else f"{val:.2f}"
    if key not in percentiles:
        # e.g. Win Rate vs opponents — no meaningful pool, so the bar stays empty.
        rows.append(
            "<tr>"
            f"<td style='padding:4px 8px;width:35%;'>{label}</td>"
            f"<td style='padding:4px 8px;text-align:center;width:15%;'>{val_str}</td>"
            "<td style='padding:4px 8px;width:50%;'></td></tr>"
        )
        continue
    pct = percentiles[key]
    color = transform.percentile_color(pct)
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
    f"<p style='color:#898781;font-size:12px;'>{pool_note}"
    + (f" at {position_group}" if position_group != "All" else "") + "</p>"
    "<table style='width:100%;border-collapse:collapse;font-family:system-ui,-apple-system,sans-serif;font-size:13px;'>"
    "<thead><tr style='border-bottom:2px solid #c3c2b7;text-align:left;'>"
    "<th style='padding:4px 8px;'>Stat</th><th style='padding:4px 8px;'>Value</th>"
    "<th style='padding:4px 8px;'>Percentile</th></tr></thead>"
    f"<tbody>{''.join(rows)}</tbody></table>",
    unsafe_allow_html=True,
)
