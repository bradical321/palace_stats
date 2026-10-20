"""Overview — record, form, and the headline numbers. Run with:
    streamlit run Overview.py
"""
import streamlit as st

import config
import transform
import ui_common as ui

st.set_page_config(page_title=f"{config.CLUB_NAME} Stats", page_icon="⚽", layout="wide")

group = ui.render_sidebar()
matches, player_matches = ui.load_filtered_data(group)

review_count = ui.needs_review_count()
if review_count:
    st.sidebar.warning(f"{review_count} match(es) need a tag — see **Admin**.")

st.title(f"{config.CLUB_NAME} — Overview")
st.caption(f"Showing: **{group}** games")

if matches.empty:
    st.info("No match data yet. Run `python collector.py` to pull your first batch from EA.")
    st.stop()

# --- Headline stat tiles -----------------------------------------------------
games = len(matches)
wins = int((matches["clean_result"] == "W").sum())
draws = int((matches["clean_result"] == "D").sum())
losses = int((matches["clean_result"] == "L").sum())
win_pct = round(wins / games * 100, 1) if games else 0
gf = matches["clean_goals_for"].sum()
ga = matches["clean_goals_against"].sum()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Record", f"{wins}-{draws}-{losses}")
c2.metric("Win %", f"{win_pct}%")
c3.metric("Goals For", f"{gf:.0f}")
c4.metric("Goals Against", f"{ga:.0f}")
c5.metric("Goal Diff", f"{gf - ga:+.0f}")

st.divider()

# --- Form: last 10 games ------------------------------------------------------
form = transform.compute_form(matches, n=10)
st.subheader("Form (last 10)")

fcol1, fcol2 = st.columns([2, 1])
with fcol1:
    if form["results"]:
        st.markdown(ui.form_strip_html(form["results"]), unsafe_allow_html=True)
    else:
        st.caption("Not enough games yet.")
with fcol2:
    streak_label = f'{form["streak_len"]}{form["streak_type"]}' if form["streak_type"] else "—"
    st.metric("Current streak", streak_label)
    st.caption(f'Last 10 record: {form["record"]} · {form["ppg"]} pts/game')

st.divider()

# NOTE: a "trending hot / trending poorly over last 10" per-player view was
# cut from here for now — needs more match volume and a clearer definition
# of "trending" before it's worth building. Revisit once there's more data.

st.caption(
    "Note: League is regular EAFC clubs games, Comp is UFL 10v10 games."
)
