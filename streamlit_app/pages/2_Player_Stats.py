"""Player Stats — season aggregates with percentile-tier shading, filterable
by position group so you're comparing like-for-like roles, by competition
level, and narrowable to each player's current form."""
import streamlit as st

import config
import transform
import ui_common as ui
from storage import get_storage

st.set_page_config(page_title="Player Stats", page_icon="⚽", layout="wide")

group = ui.render_sidebar()
matches, player_matches = ui.load_filtered_data(group)

st.title("Player Stats")
st.caption(f"Showing: **{group}** games")

if player_matches.empty:
    st.info("No player data yet. Run `python collector.py` first.")
    st.stop()

c1, c2 = st.columns(2)
with c1:
    position_group = st.radio("Position group", options=config.POSITION_GROUPS, horizontal=True)
with c2:
    if group == "Comp":
        # Opponent tiers use each club's overall EAFC win %, not their UFL record.
        competition = "All"
    else:
        competition = st.radio(
            "Competition", options=config.COMPETITION_LEVELS, horizontal=True,
            help="Each game's expected points, from a fit of our results on the opponent's season "
                 "win % and our lineup size minus theirs. Hardest third of games = Hard, "
                 "easiest third = Easy.",
        )

if competition != "All":
    opp_stats = get_storage().read_csv(config.TABLE_OPPONENT_CLUB_STATS, dtype={"club_id": str})
    # Fit on every (non-excluded) game, not just the sidebar's slice, so a
    # game's level doesn't change with the League / All toggle.
    all_matches, _ = ui.load_filtered_data("All")
    model = transform.fit_competition_model(all_matches, opp_stats)
    if model is None:
        st.caption("Not enough scouted games yet to rate competition level.")
    else:
        per_player = model["lineup_diff"] / -model["opp_win_pct"]
        st.caption(
            f"Fit on {model['n_games']} games: each extra player on our side is worth about "
            f"the same as facing a team with a {per_player:.1f}-point lower win %."
        )
    matches, player_matches = transform.filter_by_competition(matches, player_matches, opp_stats, model, competition)

scoped = transform.filter_by_position(player_matches, position_group)

c1, c2 = st.columns(2)
with c1:
    view = st.radio(
        "Stats", options=["All-time", "Current form"], horizontal=True,
        help=f"Current form = each player's last {config.FORM_GAMES} games for the filters above, "
             f"only counting games from the last {config.FORM_MAX_DAYS} days.",
    )
if view == "Current form":
    scoped = transform.filter_current_form(scoped)

agg = transform.compute_player_aggregates(scoped)
if agg.empty:
    st.info("No qualifying games for this filter yet.")
    st.stop()

max_games = int(agg["games_played"].max())
default_min = 5 if view == "Current form" else 3
with c2:
    if max_games > 1:
        min_games = st.slider("Minimum games played", 1, max_games, min(default_min, max_games))
    else:
        min_games = 1
display = agg[agg["games_played"] >= min_games].copy()

labels = [l for l in (position_group, competition) if l != "All"]
if view == "Current form":
    labels.append("Current form")
st.subheader(f"{len(display)} players" + "".join(f" · {l}" for l in labels))
st.markdown(transform.tier_legend_html(), unsafe_allow_html=True)

# Stat columns that get percentile-tier shading — everything except
# games_played (a volume stat, not a performance tier).
SHADED_STATS = [
    ("win_pct", "Win %", "{:.1f}%"),
    ("rating", "Rating", "{:.1f}"),
    ("goals", "Goals", "{:.0f}"),
    ("assists", "Assists", "{:.0f}"),
    ("ga_per_game", "G+A/game", "{:.2f}"),
    ("pass_success_rate", "Pass %", "{:.1f}%"),
    ("shots_per_game", "Shots/game", "{:.2f}"),
    ("shot_conversion_rate", "Shot Conv %", "{:.1f}%"),
    ("tackles_made_per_game", "Tackles/game", "{:.2f}"),
]

# Render as an HTML table so stat cells can carry a percentile tint and the
# rating column can carry its colored chip — st.dataframe can't style
# individual cells with arbitrary HTML/CSS like this.
rows_html = []
for _, r in display.iterrows():
    cells = [
        f"<td style='padding:6px 10px;font-weight:600;'>{r['player_name']}</td>",
        f"<td style='padding:6px 10px;text-align:center;'>{int(r['games_played'])}</td>",
    ]
    for key, _, fmt in SHADED_STATS:
        style = transform.tier_bg_style(r[key], display[key])
        if key == "rating":
            cell_content = ui.rating_chip_html(r[key])
        else:
            cell_content = fmt.format(r[key])
        cells.append(f"<td style='padding:6px 10px;text-align:center;{style}'>{cell_content}</td>")
    rows_html.append("<tr>" + "".join(cells) + "</tr>")

header_cells = "".join(f"<th style='padding:6px 10px;'>{label}</th>" for _, label, _ in SHADED_STATS)
table_html = f"""
<table style="width:100%;border-collapse:collapse;font-family:system-ui,-apple-system,sans-serif;font-size:14px;">
  <thead>
    <tr style="border-bottom:2px solid #c3c2b7;text-align:left;">
      <th style="padding:6px 10px;">Player</th>
      <th style="padding:6px 10px;">GP</th>
      {header_cells}
    </tr>
  </thead>
  <tbody>
    {''.join(rows_html)}
  </tbody>
</table>
"""
st.markdown(table_html, unsafe_allow_html=True)
