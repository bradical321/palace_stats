"""Matchup Analysis — how we perform against different opponent tiers and
different lineup-size situations. Opponent win% comes from
opponent_club_stats.csv (refresh with `python opponent_scout.py`); the rest
is already in matches.csv.
"""
import plotly.graph_objects as go
import streamlit as st

import config
import transform
import ui_common as ui
from storage import get_storage

st.set_page_config(page_title="Matchup Analysis", page_icon="📊", layout="wide")

group = ui.render_sidebar()
matches, _ = ui.load_filtered_data(group)

st.title("Matchup Analysis")
st.caption(f"Showing: **{group}** games")

if matches.empty:
    st.info("No match data yet. Run `python collector.py` first.")
    st.stop()


def _bar(df, x_col, y_col, title, hover_suffix=""):
    # No hardcoded background/gridline colors here — st.plotly_chart's
    # default theme="streamlit" adapts those to the viewer's light/dark
    # setting on its own. Setting them explicitly (as an earlier version of
    # this page did) overrides that and is what caused unreadable charts in
    # dark mode (a light plot area floating on a dark page).
    fig = go.Figure(go.Bar(
        x=df[x_col], y=df[y_col], marker_color="#2a78d6",
        text=df["record"], textposition="outside",
        hovertemplate="%{x}<br>" + title + ": %{y:.1f}" + hover_suffix + "<br>Record: %{text}<extra></extra>",
    ))
    fig.update_layout(
        height=360, margin=dict(l=10, r=10, t=10, b=10),
        yaxis_title=title, showlegend=False,
    )
    return fig


st.subheader("Performance vs. opponent tier")

if group == "Comp":
    st.caption(
        "Doesn't apply to Comp: opponent tiers use each club's overall EAFC win %, "
        "not their UFL 10v10 record. Switch to League or All to see this."
    )
else:
    st.caption("Opponents bucketed into thirds by their own season win % (not fixed cutoffs — reflects who we've actually faced).")

    storage = get_storage()
    opp_stats = storage.read_csv(config.TABLE_OPPONENT_CLUB_STATS, dtype={"club_id": str})
    tier_perf = transform.performance_by_opponent_tier(matches, opp_stats)

    if tier_perf.empty:
        st.caption("Not enough opponent scouting data yet — run `python opponent_scout.py`.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.plotly_chart(_bar(tier_perf, "tier", "win_pct", "Win %", "%"), width='stretch')
        with c2:
            st.plotly_chart(_bar(tier_perf, "tier", "ppg", "Points/Game"), width='stretch')
        st.dataframe(tier_perf.rename(columns={"tier": "Tier", "games": "Games", "record": "Record",
                                                "win_pct": "Win %", "ppg": "Pts/Game"}),
                     hide_index=True, width='stretch')

st.divider()

st.subheader("Performance vs. lineup size difference")
st.caption("Our lineup size minus the opponent's, for each match.")

size_perf = transform.performance_by_lineup_diff(matches)
if size_perf.empty:
    st.caption("Not enough matches with lineup data yet.")
else:
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(_bar(size_perf, "size_bucket", "win_pct", "Win %", "%"), width='stretch')
    with c2:
        st.plotly_chart(_bar(size_perf, "size_bucket", "ppg", "Points/Game"), width='stretch')
    st.dataframe(size_perf.rename(columns={"size_bucket": "Situation", "games": "Games", "record": "Record",
                                            "win_pct": "Win %", "ppg": "Pts/Game"}),
                 hide_index=True, width='stretch')
