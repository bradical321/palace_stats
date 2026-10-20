"""Player Stats — season aggregates with percentile-tier shading, filterable
by position group so you're comparing like-for-like roles."""
import streamlit as st

import config
import transform
import ui_common as ui

st.set_page_config(page_title="Player Stats", page_icon="⚽", layout="wide")

group = ui.render_sidebar()
matches, player_matches = ui.load_filtered_data(group)

st.title("Player Stats")
st.caption(f"Showing: **{group}** games")

if player_matches.empty:
    st.info("No player data yet. Run `python collector.py` first.")
    st.stop()

position_group = st.radio("Position group", options=config.POSITION_GROUPS, horizontal=True)
scoped = transform.filter_by_position(player_matches, position_group)

agg = transform.compute_player_aggregates(scoped)
if agg.empty:
    st.info("No qualifying games for this filter yet.")
    st.stop()

min_games = st.slider("Minimum games played", 1, int(agg["games_played"].max()), 1)
display = agg[agg["games_played"] >= min_games].copy()

st.subheader(f"{len(display)} players" + (f" · {position_group}" if position_group != "All" else ""))
st.caption(
    "Shaded cells = this player's percentile among the players shown — "
    "🟩 leaning toward the top, 🟥 leaning toward the bottom, barely tinted "
    "near the middle. Intensity scales with how far from the middle it is."
)

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
