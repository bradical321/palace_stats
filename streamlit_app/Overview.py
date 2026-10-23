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
c1.metric("Record (W-D-L)", f"{wins}-{draws}-{losses}")
c2.metric("Win %", f"{win_pct}%")
c3.metric("Goals / Game", f"{gf_pg:.2f}")
c4.metric("Goals Against / Game", f"{ga_pg:.2f}")
c5.metric("Avg Goal Diff", f"{gf_pg - ga_pg:+.2f}")

st.divider()

# --- Form: last 10 games + points-per-game trend ------------------------------
PPG_WINDOW = 10      # games in the trend window; 5 was too jagged to read a trend
PPG_WEIGHTED = False  # True = recent-weighted average; tried it, it reacts more and looks jaggier
PPG_LABEL = (f"({PPG_WINDOW}-game weighted ppg trend)" if PPG_WEIGHTED
             else f"({PPG_WINDOW}-game ppg trend)")
GOOD, BAD = config.RATING_STATUS["good"], config.RATING_STATUS["critical"]


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def _trend_figure(trend, avg_ppg: float) -> go.Figure:
    """PPG trend vs the all-time average: green fill above it, red below,
    both fading out toward the average line."""
    x, y = trend["game"], trend["rolling_ppg"]
    above, below = y.clip(lower=avg_ppg), y.clip(upper=avg_ppg)
    fig = go.Figure()
    # Invisible baseline at the average, so each band fills to it.
    base = dict(x=x, y=[avg_ppg] * len(x), mode="lines", line=dict(width=0), hoverinfo="skip")
    fig.add_trace(go.Scatter(**base))
    fig.add_trace(go.Scatter(
        x=x, y=above, mode="lines", line=dict(width=0), fill="tonexty", hoverinfo="skip",
        fillgradient=dict(type="vertical", start=avg_ppg, stop=max(y.max(), avg_ppg + 0.01),
                          colorscale=[[0, _rgba(GOOD, 0.05)], [1, _rgba(GOOD, 0.6)]]),
    ))
    fig.add_trace(go.Scatter(**base))
    fig.add_trace(go.Scatter(
        x=x, y=below, mode="lines", line=dict(width=0), fill="tonexty", hoverinfo="skip",
        fillgradient=dict(type="vertical", start=avg_ppg, stop=min(y.min(), avg_ppg - 0.01),
                          colorscale=[[0, _rgba(BAD, 0.05)], [1, _rgba(BAD, 0.6)]]),
    ))
    fig.add_hline(y=avg_ppg, line=dict(color="#2a78d6", width=1.5, dash="dot"),
                  annotation_text=f"avg {avg_ppg:.1f}", annotation_position="top left",
                  annotation_font=dict(size=11, color="#2a78d6"))
    fig.add_trace(go.Scatter(
        x=x, y=y, mode="lines", line=dict(color="#55534e", width=2),
        customdata=trend[["date", "opponent", "result", "score"]],
        hovertemplate="%{customdata[0]} vs %{customdata[1]}<br>%{customdata[2]} %{customdata[3]}"
                      " · trend <b>%{y:.2f}</b><extra></extra>",
    ))
    last = trend.iloc[-1]
    fig.add_trace(go.Scatter(
        x=[last["game"]], y=[last["rolling_ppg"]], mode="markers+text",
        marker=dict(color="#55534e", size=8), text=[f"{last['rolling_ppg']:.1f}"],
        textposition="middle right", textfont=dict(size=13), hoverinfo="skip",
    ))
    fig.update_layout(
        height=190, margin=dict(l=0, r=28, t=6, b=0), showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False),
        yaxis=dict(range=[0, 3.05], tickvals=[0, 1, 2, 3], showgrid=True,
                   gridcolor="rgba(128,128,128,0.15)", zeroline=False, tickfont=dict(size=10)),
        hovermode="x",
    )
    return fig


form = transform.compute_form(matches, n=10)
fcol1, fcol2 = st.columns([1, 1.4], gap="large")
with fcol1:
    st.subheader("Form (last 10)")
    if form["results"]:
        st.markdown(ui.form_strip_html(form["results"]), unsafe_allow_html=True)
    else:
        st.caption("Not enough games yet.")
    st.caption(f'Last 10 record (W-D-L): {form["record"]} · {form["ppg"]} pts/game')
with fcol2:
    st.subheader("Club Performance Trend")
    st.markdown(
        f"<div style='margin-top:-14px;font-size:13px;opacity:0.6;'>{PPG_LABEL}</div>",
        unsafe_allow_html=True,
    )
    trend = transform.rolling_ppg(matches, window=PPG_WINDOW, weighted=PPG_WEIGHTED)
    if len(trend) >= 2:
        avg_ppg = matches["clean_result"].map({"W": 3, "D": 1, "L": 0}).mean()
        st.plotly_chart(_trend_figure(trend, avg_ppg), width="stretch",
                        config={"displayModeBar": False}, theme="streamlit")
    else:
        st.caption(f"Trend appears after {PPG_WINDOW + 1} games.")

st.divider()

# NOTE: a "trending hot / trending poorly over last 10" per-player view was
# cut from here for now — needs more match volume and a clearer definition
# of "trending" before it's worth building. Revisit once there's more data.

st.caption(
    "Note: League is regular EAFC clubs games, Comp is UFL 10v10 games."
)
