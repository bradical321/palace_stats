"""Overview — record, form, and the headline numbers. Run with:
    streamlit run Overview.py
"""
import plotly.graph_objects as go
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
gf_pg = matches["clean_goals_for"].sum() / games
ga_pg = matches["clean_goals_against"].sum() / games

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Record", f"{wins}-{draws}-{losses}")
c2.metric("Win %", f"{win_pct}%")
c3.metric("Goals / Game", f"{gf_pg:.2f}")
c4.metric("Goals Against / Game", f"{ga_pg:.2f}")
c5.metric("Avg Goal Diff", f"{gf_pg - ga_pg:+.2f}")

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
    st.caption(f'Last 10 record: {form["record"]} · {form["ppg"]} pts/game')
with fcol2:
    trend = transform.rolling_ppg(matches, window=5)
    if len(trend) >= 2:
        last = trend.iloc[-1]
        st.markdown(
            f"<div style='font-size:14px;'>Points per game · 5-game avg "
            f"<b style='font-size:18px;margin-left:6px;'>{last['rolling_ppg']:.1f}</b></div>",
            unsafe_allow_html=True,
        )
        line = "#2a78d6"
        fig = go.Figure(go.Scatter(
            x=trend["game"], y=trend["rolling_ppg"], mode="lines",
            line=dict(color=line, width=2),
            customdata=trend[["date", "opponent", "result", "score"]],
            hovertemplate="%{customdata[0]} vs %{customdata[1]}<br>%{customdata[2]} %{customdata[3]}"
                          " · 5-game avg <b>%{y:.1f}</b><extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=[last["game"]], y=[last["rolling_ppg"]], mode="markers",
            marker=dict(color=line, size=8), hoverinfo="skip",
        ))
        fig.update_layout(
            height=110, margin=dict(l=0, r=0, t=4, b=0), showlegend=False,
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(visible=False),
            yaxis=dict(range=[0, 3.1], tickvals=[0, 1.5, 3], showgrid=True,
                       gridcolor="rgba(128,128,128,0.18)", zeroline=False, tickfont=dict(size=10)),
            hovermode="x",
        )
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False}, theme="streamlit")
    else:
        st.caption("Points-per-game trend appears after 6 games.")

st.divider()

# NOTE: a "trending hot / trending poorly over last 10" per-player view was
# cut from here for now — needs more match volume and a clearer definition
# of "trending" before it's worth building. Revisit once there's more data.

st.caption(
    "Note: League is regular EAFC clubs games, Comp is UFL 10v10 games."
)
