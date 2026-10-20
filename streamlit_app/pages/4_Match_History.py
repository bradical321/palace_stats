"""Match History — list + both-rosters detail view for one match."""
import pandas as pd
import streamlit as st

import config
import transform
import ui_common as ui
from storage import get_storage

st.set_page_config(page_title="Match History", page_icon="⚽", layout="wide")

group = ui.render_sidebar()
matches, player_matches = ui.load_filtered_data(group)

st.title("Match History")
st.caption(f"Showing: **{group}** games")

if matches.empty:
    st.info("No match data yet. Run `python collector.py` first.")
    st.stop()

listing = matches.sort_values("timestamp", ascending=False).copy()
listing["Score"] = listing["clean_goals_for"].astype(int).astype(str) + "-" + listing["clean_goals_against"].astype(int).astype(str)
listing["label"] = (
    listing["date"].str.slice(0, 10) + "  vs " + listing["opponent_club_name"] +
    "  (" + listing["Score"] + " " + listing["clean_result"] + ")" +
    "  [" + listing["Match_Type"] + "]"
)

# The match-listing table is parked for now (it was crowding this page) —
# just the picker + detail view below.
selected_label = st.selectbox("Pick a match", options=listing["label"].tolist())
selected_row = listing[listing["label"] == selected_label].iloc[0]
match_id = selected_row["matchId"]

st.markdown(
    f"**{selected_row['date']}** · vs **{selected_row['opponent_club_name']}** · "
    f"Score **{selected_row['Score']}** ({selected_row['clean_result']}) · "
    f"Tag: `{selected_row['Match_Type']}`"
    + (" · ⚠️ Penalty shootout (score shown is pre-shootout)" if selected_row.get("is_penalty_game") else "")
)

storage = get_storage()
our_roster, opp_roster = transform.get_match_rosters(storage, match_id)


def _roster_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "<p><em>No player data captured for this match.</em></p>"
    df = df.sort_values("rating", ascending=False)
    rows = "".join(
        "<tr>"
        f"<td style='padding:4px 8px;font-weight:600;'>{r['player_name']}</td>"
        f"<td style='padding:4px 8px;'>{r['position']}</td>"
        f"<td style='padding:4px 8px;text-align:center;'>{ui.rating_chip_html(float(r['rating']))}</td>"
        f"<td style='padding:4px 8px;text-align:center;'>{int(r['goals'])}</td>"
        f"<td style='padding:4px 8px;text-align:center;'>{int(r['assists'])}</td>"
        f"<td style='padding:4px 8px;text-align:center;'>{int(r['passes_made'])}/{int(r['pass_attempts'])}</td>"
        f"<td style='padding:4px 8px;text-align:center;'>{int(r['tackles_made'])}/{int(r['tackle_attempts'])}</td>"
        f"<td style='padding:4px 8px;text-align:center;'>{'⭐' if int(r['mom']) else ''}</td>"
        "</tr>"
        for _, r in df.iterrows()
    )
    return f"""
    <table style="width:100%;border-collapse:collapse;font-family:system-ui,-apple-system,sans-serif;font-size:13px;">
      <thead><tr style="border-bottom:2px solid #c3c2b7;text-align:left;">
        <th style='padding:4px 8px;'>Player</th><th style='padding:4px 8px;'>Pos</th>
        <th style='padding:4px 8px;'>Rating</th><th style='padding:4px 8px;'>G</th>
        <th style='padding:4px 8px;'>A</th><th style='padding:4px 8px;'>Passes</th>
        <th style='padding:4px 8px;'>Tackles</th><th style='padding:4px 8px;'>MOM</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """


t1, t2 = st.tabs([config.CLUB_NAME, "Opponent"])
with t1:
    st.markdown(_roster_table(our_roster), unsafe_allow_html=True)
with t2:
    st.markdown(_roster_table(opp_roster), unsafe_allow_html=True)
