"""Win Shares — a first working version of the player/position-effects model.
Password-gated for now (same as Admin) while this is still under
construction and the sample size is too small to show as a finished page.

See win_shares.py's module docstring for the full method writeup. Short
version: a context baseline (OLS) removes what's explainable by the
matchup, then two separate ridge models explain the leftover (context-
adjusted) goal differential — one by player presence (plus-minus style),
one by player x position presence (identity-preserving, split by role).
"""
import plotly.graph_objects as go
import streamlit as st

import config
import transform
import ui_common as ui
import win_shares as ws
from storage import get_storage

st.set_page_config(page_title="Win Shares", page_icon="🧮", layout="wide")

group = ui.render_sidebar()

if not ui.require_admin_password():
    st.stop()

matches, player_matches = ui.load_filtered_data(group)

st.title("Win Shares")
st.caption(f"Showing: **{group}** games")

if matches.empty:
    st.info("No match data yet. Run `python collector.py` first.")
    st.stop()

storage = get_storage()
opp_stats = storage.read_csv(config.TABLE_OPPONENT_CLUB_STATS, dtype={"club_id": str})

df, player_cols, player_position_cols = ws.build_match_level_dataset(matches, player_matches, opp_stats)

if df.empty or len(df) < 8:
    st.warning(
        f"Only {len(df)} matches have everything this model needs (goal diff, opponent win %, "
        "lineup sizes). Need more before this is worth looking at — run `python opponent_scout.py` "
        "if win % is the gap, or just keep collecting."
    )
    st.stop()

st.info(
    f"**N = {len(df)} matches.** This is genuinely early — every number below is directional, "
    "not a settled conclusion. The model tells you itself when it doesn't trust a number yet "
    "(see the cross-validation notes); read those as seriously as the estimates."
)

# --- Stage 1: context baseline ------------------------------------------------
st.header("1. Matchup baseline")
st.caption("What's explainable by the matchup alone, before any player/position credit is assigned.")

baseline_model, df = ws.fit_baseline_model(df)

c1, c2, c3 = st.columns(3)
c1.metric("R²", f"{baseline_model.rsquared:.2f}")
opp_p = baseline_model.pvalues["opponent_win_pct"]
size_p = baseline_model.pvalues["team_size_diff"]
c2.metric("Opponent win % effect", f"{baseline_model.params['opponent_win_pct']:+.3f}",
          help=f"Goal-diff change per 1-point rise in opponent win%. p={opp_p:.2f}")
c3.metric("Lineup-size-diff effect", f"{baseline_model.params['team_size_diff']:+.3f}",
          help=f"Goal-diff change per extra player we have vs. them. p={size_p:.2f}")

sig_note = []
if opp_p < 0.05:
    sig_note.append("opponent win %")
if size_p < 0.05:
    sig_note.append("lineup-size difference")
if sig_note:
    st.caption(f"Statistically significant (p<0.05) so far: {', '.join(sig_note)}.")
else:
    st.caption("Neither effect clears p<0.05 yet at this sample size — directions look sensible (stronger opponents and being short-handed both point the expected way), just not proven yet.")

st.divider()

# --- Stage 2: player effects ---------------------------------------------------
st.header("2. Player effects")
st.caption("Plus-minus style: how the context-adjusted scoreline moved when this player was on the field — not their own box-score stats (see the position-group section for that).")

player_info = ws.resolve_alpha(df, player_cols)
if player_info["is_exploratory"]:
    st.warning(
        f"Cross-validation wants to shrink every player's effect to ~0 right now (it tried "
        f"alpha up to {player_info['cv_alpha']:,.0f} and kept wanting more) — with this few "
        "matches and this much overlap in who plays together, there's no individually-separable "
        "signal yet. The ranking below uses a smaller, fixed regularization purely to show "
        "**direction** for discussion — treat it as exploratory, not validated."
    )
else:
    st.caption(f"Cross-validation found a stable regularization strength (alpha={player_info['alpha']:.1f}) — more trustworthy than the exploratory fallback case.")

player_boot = ws.bootstrap_ridge_effects(df, player_cols, alpha=player_info["alpha"], n_boot=300)
games_played = (df[player_cols] > 0).sum().rename("games_played")
player_boot = player_boot.merge(games_played.reset_index().rename(columns={"index": "feature", "games_played": "games_played"}),
                                 on="feature", how="left")

fig = go.Figure(go.Bar(
    x=player_boot["coefficient"], y=player_boot["feature"], orientation="h",
    marker_color="#2a78d6",
    error_x=dict(
        type="data", symmetric=False,
        array=player_boot["p90"] - player_boot["coefficient"],
        arrayminus=player_boot["coefficient"] - player_boot["p10"],
    ),
    hovertemplate="%{y}: %{x:.2f} goal-diff/game (90% band shown)<extra></extra>",
))
fig.update_layout(height=max(320, 32 * len(player_boot)), margin=dict(l=10, r=10, t=10, b=10),
                   xaxis_title="Context-adjusted goal-diff contribution per game", showlegend=False)
st.plotly_chart(fig, width='stretch')

display_cols = player_boot[["feature", "games_played", "coefficient", "p10", "p90", "sign_stability_pct"]].rename(
    columns={"feature": "Player", "games_played": "Games", "coefficient": "Effect",
             "p10": "P10", "p90": "P90", "sign_stability_pct": "Sign stability %"}
)
st.dataframe(display_cols.round(2), hide_index=True, width='stretch')
st.caption("Sign stability = % of bootstrap resamples where the effect kept the same direction as the point estimate. Treat anything below ~70% as a coin flip right now.")

st.divider()

# --- Stage 3: player x position effects -----------------------------------------
st.header("3. Player x position effects")
st.caption(
    "Same plus-minus idea as section 2, but each player is split into one variable per role "
    "they've played — BradleyJames13-Forward is separate from BradleyJames13-Midfielder. "
    "Player identity stays attached; this is not a team-wide 'how do our forwards do in general' total."
)

pp_info = ws.resolve_alpha(df, player_position_cols)
if pp_info["is_exploratory"]:
    st.warning(
        f"Cross-validation wants heavy shrinkage here too (tried alpha up to {pp_info['cv_alpha']:,.0f}) — "
        "expected, since this splits the already-thin player data even further by role. Same exploratory "
        "fallback as section 2."
    )
else:
    st.caption(f"Cross-validation found a stable regularization strength (alpha={pp_info['alpha']:.1f}).")

pp_boot = ws.bootstrap_ridge_effects(df, player_position_cols, alpha=pp_info["alpha"], n_boot=300)
pp_games = (df[player_position_cols] > 0).sum().rename("games_played")
pp_boot = pp_boot.merge(pp_games.reset_index().rename(columns={"index": "feature"}), on="feature", how="left")
pp_boot[["Player", "Position"]] = pp_boot["feature"].str.rsplit("_", n=1, expand=True)

fig2 = go.Figure(go.Bar(
    x=pp_boot["coefficient"], y=pp_boot["Player"] + " – " + pp_boot["Position"], orientation="h",
    marker_color="#2a78d6",
    error_x=dict(
        type="data", symmetric=False,
        array=pp_boot["p90"] - pp_boot["coefficient"],
        arrayminus=pp_boot["coefficient"] - pp_boot["p10"],
    ),
    hovertemplate="%{y}: %{x:.2f}<extra></extra>",
))
fig2.update_layout(height=max(320, 26 * len(pp_boot)), margin=dict(l=10, r=10, t=10, b=10),
                    xaxis_title="Context-adjusted goal-diff contribution per game", showlegend=False)
st.plotly_chart(fig2, width='stretch')

display_cols2 = pp_boot[["Player", "Position", "games_played", "coefficient", "p10", "p90", "sign_stability_pct"]].rename(
    columns={"games_played": "Games", "coefficient": "Effect", "p10": "P10", "p90": "P90",
             "sign_stability_pct": "Sign stability %"}
)
st.dataframe(display_cols2.round(2), hide_index=True, width='stretch')
st.caption(
    "Most players show up in only one role here — that's expected, not a gap. A row with very few "
    "Games is riding on almost no data; weight it accordingly."
)

st.divider()
with st.expander("Methodology — what this is actually doing"):
    st.markdown(
        "1. **Baseline (OLS)**: `goal_diff ~ opponent_win_pct + team_size_diff` — the matchup-only expectation.\n"
        "2. **Residual**: actual goal diff minus that expectation — over/under-performance relative to the matchup.\n"
        "3. **Player effects (Ridge)**: regress the residual on each player's minutes-fraction that match. "
        "Isolates presence on the field, not personal box-score stats (that would double-count goals).\n"
        "4. **Player x position effects (Ridge)**: same as step 3, but each player's minutes-fraction is "
        "split into a separate variable per position group they played that match (identity-preserving — "
        "not a team-wide role total).\n\n"
        "Ridge (not plain regression) because there are more features than matches once rosters/position "
        "stats are added — plain regression wouldn't be solvable. Alpha (how hard to shrink toward zero) is "
        "chosen by leave-one-out cross-validation where that lands on a stable interior value, or a smaller "
        "fixed fallback (clearly flagged above) when CV just wants to shrink everything to nothing. "
        "Confidence bands come from refitting on 300 match-level bootstrap resamples, since ridge "
        "coefficients don't have a standard p-value."
    )
