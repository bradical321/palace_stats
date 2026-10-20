"""
Win-shares model: isolate each player's (and each position group's) effect
on match result, controlling for matchup context.

METHOD — a two-stage "residualized ridge" (Frisch-Waugh-Lovell style),
chosen specifically for a small-N, many-correlated-predictors situation
like this one, rather than one giant regression:

  1. BASELINE (OLS, statsmodels): goal_diff ~ opponent_win_pct + team_size_diff.
     What's explainable by the matchup alone, with real p-values / R² / CI —
     this is the trusted "context" layer, estimated unregularized because
     there are only 2 of these features and they're not collinear with
     each other, so plain OLS is fine and interpretable.

  2. RESIDUAL: goal_diff minus the baseline's prediction — i.e., how much
     better or worse we did than the matchup alone would predict.

  3. PLAYER EFFECTS (Ridge, leave-one-out CV): regress that residual on
     each player's minutes-fraction in the match (0 = didn't play, 1 =
     played the whole thing). This is a plus-minus-style estimate — it
     isolates "how did the scoreline move, relative to expectation, when
     this specific player was on the field" — not their own box-score
     counting stats, which would conflate "what they personally did" with
     "what it meant for the result" (and double-count goals, which
     mechanically ARE most of goal_diff).

  4. PLAYER x POSITION EFFECTS (Ridge, same method): same idea as step 3,
     but each player is split into one variable per position group they've
     played — "BradleyJames13_Forward", "BradleyJames13_Midfielder", etc.
     (NOT a generic team-wide "Forward" column averaged across whoever
     played there — player identity stays attached). Isolates whether a
     given player's on-field effect differs depending which role they're
     in, at the cost of an even sparser feature set than step 3 (most
     players occupy one or two roles, so most player x position columns
     are all-zero most of the time).

Ridge (not OLS) for steps 3-4 because there are more features than matches
once the roster/position-stat columns are added — OLS would be
unidentified. RidgeCV's default (cv=None) does efficient leave-one-out CV,
which is the right call at this sample size. Coefficients are reported
back in original units (goal-diff per full game played, or per 1 extra
goal/tackle/pass%-point) by un-standardizing after fitting on standardized
features — ridge's penalty is scale-sensitive, so fitting on raw units
with wildly different scales (0-1 minutes fraction vs a 0-100 pass %)
would unfairly penalize the larger-scale features more.

CONFIDENCE: ridge coefficients don't have a textbook p-value (it's a
biased estimator by design). Instead this uses match-level bootstrap
resampling — refit on N resamples of the 25-ish matches, report the
10th-90th percentile band per feature and the % of resamples where the
sign agreed with the point estimate ("sign stability"), which is honest
about how little data this is tested on, without requiring a stats PhD to
read.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.linear_model import Ridge, RidgeCV

CONTEXT_COLS = ["opponent_win_pct", "team_size_diff"]
POSITION_GROUPS_CAP = ["Defender", "Midfielder", "Forward"]

# Fallback regularization when cross-validation saturates (confirmed true
# for the player-level model on this data — see select_cv_alpha). Picked to
# be a couple of orders of magnitude below where CV keeps climbing to, so
# it's still a strong shrink, just not "shrink everything to exactly zero" —
# enough to rank players directionally for discussion, explicitly NOT
# claimed to be statistically validated. Revisit this constant as more
# matches come in and re-check whether CV still saturates.
EXPLORATORY_ALPHA = 10.0


def resolve_alpha(df: pd.DataFrame, feature_cols: list[str]) -> dict:
    """Decide which alpha to actually use for a feature set, and whether
    that choice is cross-validation-backed or an exploratory fallback.
    Returns {"alpha": float, "cv_alpha": float, "is_exploratory": bool}."""
    cv_alpha, saturated = select_cv_alpha(df, feature_cols)
    if saturated:
        return {"alpha": EXPLORATORY_ALPHA, "cv_alpha": cv_alpha, "is_exploratory": True}
    return {"alpha": cv_alpha, "cv_alpha": cv_alpha, "is_exploratory": False}


def build_match_level_dataset(matches: pd.DataFrame, player_matches: pd.DataFrame,
                               opponent_club_stats: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    """One row per match: goal_diff target, context features, a wide column
    per player (their minutes-fraction that match), and a wide column per
    player x position-group they've played ("BradleyJames13_Forward", etc —
    identity-preserving, not a generic team-wide position total). Returns
    (df, player_cols, player_position_cols)."""
    if matches.empty or player_matches.empty:
        return pd.DataFrame(), [], []

    df = matches.copy()
    df["goal_diff"] = (
        pd.to_numeric(df["clean_goals_for"], errors="coerce")
        - pd.to_numeric(df["clean_goals_against"], errors="coerce")
    )
    df["team_size_diff"] = (
        pd.to_numeric(df["our_player_count"], errors="coerce")
        - pd.to_numeric(df["opponent_player_count"], errors="coerce")
    )

    if opponent_club_stats is not None and not opponent_club_stats.empty:
        opp = opponent_club_stats[["club_id", "win_pct"]].rename(
            columns={"win_pct": "opponent_win_pct", "club_id": "opponent_club_id"}
        )
        opp["opponent_club_id"] = opp["opponent_club_id"].astype(str)
        df["opponent_club_id"] = df["opponent_club_id"].astype(str)
        df = df.merge(opp, on="opponent_club_id", how="left")
    else:
        df["opponent_win_pct"] = pd.NA

    df = df.dropna(subset=["goal_diff", "opponent_win_pct", "team_size_diff"]).copy()
    if df.empty:
        return pd.DataFrame(), [], []

    pm = player_matches.copy()
    pm["seconds_played"] = pd.to_numeric(pm["seconds_played"], errors="coerce").fillna(0)
    match_max = pm.groupby("matchId")["seconds_played"].transform("max").replace(0, np.nan)
    pm["minutes_fraction"] = (pm["seconds_played"] / match_max).fillna(0).clip(0, 1)

    player_wide = pm.pivot_table(index="matchId", columns="player_name", values="minutes_fraction",
                                  aggfunc="max", fill_value=0)
    player_cols = list(player_wide.columns)
    df = df.merge(player_wide, on="matchId", how="left")
    for c in player_cols:
        df[c] = df[c].fillna(0)

    # Player x position: same minutes-fraction idea as the player-only
    # columns above, but split per (player, position group they played that
    # match) — "BradleyJames13_Forward" is its own variable, distinct from
    # "BradleyJames13_Midfielder". A player who only ever plays one role
    # ends up with one populated column and the rest structurally zero,
    # which is expected, not a bug.
    pm_pos = pm.copy()
    pm_pos["position_group"] = pm_pos["position"].astype(str).str.capitalize()
    pm_pos = pm_pos[pm_pos["position_group"].isin(POSITION_GROUPS_CAP)]
    pm_pos["player_position"] = pm_pos["player_name"] + "_" + pm_pos["position_group"]

    player_position_wide = pm_pos.pivot_table(index="matchId", columns="player_position",
                                               values="minutes_fraction", aggfunc="max", fill_value=0)
    player_position_cols = list(player_position_wide.columns)
    df = df.merge(player_position_wide, on="matchId", how="left")
    for c in player_position_cols:
        df[c] = df[c].fillna(0)

    return df.reset_index(drop=True), player_cols, player_position_cols


def fit_baseline_model(df: pd.DataFrame):
    """OLS: goal_diff ~ opponent_win_pct + team_size_diff. Returns
    (fitted statsmodels result, df with baseline_pred/residual columns added)."""
    X = sm.add_constant(df[CONTEXT_COLS].astype(float))
    y = df["goal_diff"].astype(float)
    model = sm.OLS(y, X).fit()

    out = df.copy()
    out["baseline_pred"] = model.predict(X)
    out["residual"] = y - out["baseline_pred"]
    return model, out


def _standardize(X: np.ndarray):
    means, stds = X.mean(axis=0), X.std(axis=0)
    stds_safe = np.where(stds == 0, 1.0, stds)
    return (X - means) / stds_safe, stds_safe


def select_cv_alpha(df: pd.DataFrame, feature_cols: list[str], alpha_grid_max_power: int = 4):
    """Run leave-one-out CV ridge to find the cross-validation-preferred
    alpha. Returns (alpha, saturated) — `saturated` is True if the search
    hit the top of the grid, which here specifically means "CV wants even
    MORE shrinkage than we offered it" — i.e., at this sample size and with
    this many correlated features, cross-validation can't find a reliable
    non-zero signal (confirmed on this data: widening the grid further just
    keeps pushing the selected alpha higher, never settling on an interior
    value). That's a real, honest finding, not a bug — surface it, don't
    paper over it with a bigger grid."""
    X = df[feature_cols].astype(float).values
    y = df["residual"].astype(float).values
    Xs, _ = _standardize(X)

    alphas = np.logspace(-2, alpha_grid_max_power, 60)
    model = RidgeCV(alphas=alphas, cv=None)  # cv=None -> efficient LOOCV, right call at this N
    model.fit(Xs, y)
    saturated = np.isclose(model.alpha_, alphas[-1])
    return float(model.alpha_), bool(saturated)


def fit_ridge_effects(df: pd.DataFrame, feature_cols: list[str], alpha: float) -> pd.DataFrame:
    """Ridge coefficients for `feature_cols` against the context-adjusted
    residual, at a SPECIFIC alpha (no internal CV search — pick the alpha
    with select_cv_alpha() for the rigorous estimate, or pass a smaller
    fixed value for an exploratory/directional one; see the module
    docstring and callers for which to use when)."""
    X = df[feature_cols].astype(float).values
    y = df["residual"].astype(float).values
    Xs, stds = _standardize(X)

    model = Ridge(alpha=alpha)
    model.fit(Xs, y)
    coefs_original = model.coef_ / stds
    results = pd.DataFrame({"feature": feature_cols, "coefficient": coefs_original})
    return results.sort_values("coefficient", ascending=False).reset_index(drop=True)


def bootstrap_ridge_effects(df: pd.DataFrame, feature_cols: list[str], alpha: float,
                             n_boot: int = 300, seed: int = 42) -> pd.DataFrame:
    """Resample MATCHES with replacement, refit at a FIXED alpha (not
    re-searched per resample — that would conflate coefficient uncertainty
    with alpha-selection noise, which is itself unstable at this N), and
    summarize the spread as an honest stand-in for a p-value, since ridge
    coefficients don't have one in the usual sense. Returns point estimate
    + 10th/90th percentile band + % of resamples agreeing in sign with the
    point estimate ("sign stability")."""
    point_df = fit_ridge_effects(df, feature_cols, alpha)
    point = dict(zip(point_df["feature"], point_df["coefficient"]))

    rng = np.random.default_rng(seed)
    n = len(df)
    boot_coefs = {f: [] for f in feature_cols}

    X_full = df[feature_cols].astype(float).values
    y_full = df["residual"].astype(float).values

    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        X_b, y_b = X_full[idx], y_full[idx]
        if np.std(y_b) == 0:
            continue
        Xs_b, stds_b = _standardize(X_b)
        model = Ridge(alpha=alpha)
        model.fit(Xs_b, y_b)
        coefs = model.coef_ / stds_b
        for f, c in zip(feature_cols, coefs):
            boot_coefs[f].append(c)

    rows = []
    for f in feature_cols:
        vals = np.array(boot_coefs[f]) if boot_coefs[f] else np.array([point[f]])
        sign = np.sign(point[f]) if point[f] != 0 else 1
        sign_stability = float(np.mean(np.sign(vals) == sign)) * 100 if len(vals) else 0.0
        rows.append({
            "feature": f,
            "coefficient": point[f],
            "p10": np.percentile(vals, 10),
            "p90": np.percentile(vals, 90),
            "sign_stability_pct": sign_stability,
        })

    return pd.DataFrame(rows).sort_values("coefficient", ascending=False).reset_index(drop=True)
