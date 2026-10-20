"""Admin — password-protected. Replaces the old standalone tagger_app: one
place to classify EA "friendly" matches as our real Comp league vs a true
casual Friendly, fix a bad score, exclude a bugged game, name a newly seen
archetype id, and override a player's stats for one match.

Everything here writes straight to the active storage backend (local or
Drive) — no separate deploy-and-copy step like the old tagger_app had.
"""
import pandas as pd
import streamlit as st

import config
import ui_common as ui
from storage import get_storage

st.set_page_config(page_title="Admin", page_icon="🔒", layout="wide")

group = ui.render_sidebar()

if not ui.require_admin_password():
    st.stop()

storage = get_storage()

st.title("Admin — Tag Matches")

matches = storage.read_csv(config.TABLE_MATCHES, dtype={"matchId": str, "club_id": str})
tags = storage.read_csv(config.TABLE_MATCH_TAGS, dtype=str)

if matches.empty:
    st.info("No match data yet. Run `python collector.py` first.")
    st.stop()

our_matches = matches[matches["is_our_club"].astype(str).str.lower() == "true"].copy()
our_matches = our_matches[["matchId", "date", "opponent_club_name", "goals_for", "goals_against", "match_type"]]

if tags.empty:
    tags = pd.DataFrame(columns=["matchId", "date_str", "Match_Type", "Exclude",
                                  "Goals_For", "Goals_Against", "Score_Override"])

editable = our_matches.merge(tags, on="matchId", how="left")
editable["Match_Type"] = editable["Match_Type"].fillna(config.MATCH_TAG_NEEDS_REVIEW)
editable["Exclude"] = editable["Exclude"].fillna("FALSE").str.upper().eq("TRUE")
editable["Score_Override"] = editable["Score_Override"].fillna("FALSE").str.upper().eq("TRUE")
editable["Goals_For"] = pd.to_numeric(editable["Goals_For"], errors="coerce")
editable["Goals_Against"] = pd.to_numeric(editable["Goals_Against"], errors="coerce")
editable = editable.sort_values("date", ascending=False)

n_review = int((editable["Match_Type"] == config.MATCH_TAG_NEEDS_REVIEW).sum())
st.markdown(
    f"**{n_review}** match(es) need review out of {len(editable)} total. "
    "EA's own ranked ladder is auto-tagged **League**; everything EA calls "
    "'friendly' needs you to say whether it was our real **Comp** league, a "
    "true casual **Friendly**, a **Cup** game, or should be **Exclude**d."
)

show_only_review = st.checkbox("Show only matches needing review", value=n_review > 0)
view = editable[editable["Match_Type"] == config.MATCH_TAG_NEEDS_REVIEW] if show_only_review else editable

st.subheader("Match tags")
edited = st.data_editor(
    view[["matchId", "date", "opponent_club_name", "goals_for", "goals_against",
          "match_type", "Match_Type", "Exclude", "Score_Override", "Goals_For", "Goals_Against"]],
    column_config={
        "matchId": st.column_config.TextColumn("Match ID", disabled=True),
        "date": st.column_config.TextColumn("Date", disabled=True),
        "opponent_club_name": st.column_config.TextColumn("Opponent", disabled=True),
        "goals_for": st.column_config.NumberColumn("GF (raw)", disabled=True),
        "goals_against": st.column_config.NumberColumn("GA (raw)", disabled=True),
        "match_type": st.column_config.TextColumn("EA type", disabled=True, help="EA's own match-type bucket"),
        "Match_Type": st.column_config.SelectboxColumn("Tag", options=config.MATCH_TAG_CHOICES, required=True),
        "Exclude": st.column_config.CheckboxColumn("Exclude"),
        "Score_Override": st.column_config.CheckboxColumn("Override score?"),
        "Goals_For": st.column_config.NumberColumn("GF override", min_value=0, step=1),
        "Goals_Against": st.column_config.NumberColumn("GA override", min_value=0, step=1),
    },
    hide_index=True,
    width='stretch',
    height=480,
    key="tag_editor",
)

if st.button("💾 Save match tags", type="primary"):
    to_save = edited.copy()
    to_save["date_str"] = to_save["date"]
    to_save["Exclude"] = to_save["Exclude"].map(lambda v: "TRUE" if v else "FALSE")
    to_save["Score_Override"] = to_save["Score_Override"].map(lambda v: "TRUE" if v else "FALSE")
    to_save = to_save[["matchId", "date_str", "Match_Type", "Exclude", "Score_Override", "Goals_For", "Goals_Against"]]

    # Merge back into the full tag table (this view may be a filtered subset).
    full_tags = tags[~tags["matchId"].isin(to_save["matchId"])] if not tags.empty else pd.DataFrame()
    final_tags = pd.concat([full_tags, to_save], ignore_index=True)
    storage.write_csv(config.TABLE_MATCH_TAGS, final_tags)
    st.cache_data.clear()
    st.success(f"Saved {len(to_save)} match tag(s).")

st.divider()

# --- Archetype naming ---------------------------------------------------------
st.subheader("Name new archetypes")
st.caption(
    "EA doesn't publish an archetype id → name mapping. When a player shows an "
    "id you haven't named yet, check their archetype in your in-game Clubhouse "
    "and fill it in here — it'll show up everywhere that player's archetype is displayed."
)
arche_df = storage.read_csv(config.TABLE_ARCHETYPE_MAP, dtype=str)
if arche_df.empty:
    st.caption("No archetype ids observed yet.")
else:
    known_names = [n for n in config.KNOWN_ARCHETYPE_NAMES.keys()]
    arche_edit = arche_df.copy()
    arche_edited = st.data_editor(
        arche_edit,
        column_config={
            "archetype_id": st.column_config.TextColumn("Archetype ID", disabled=True),
            "archetype_name": st.column_config.SelectboxColumn("Name", options=[""] + known_names),
            "example_player": st.column_config.TextColumn("Example player", disabled=True),
            "example_position": st.column_config.TextColumn("Example position", disabled=True),
            "first_seen": st.column_config.TextColumn("First seen", disabled=True),
        },
        hide_index=True,
        width='stretch',
        key="archetype_editor",
    )
    if st.button("💾 Save archetype names"):
        storage.write_csv(config.TABLE_ARCHETYPE_MAP, arche_edited)
        st.cache_data.clear()
        st.success("Saved.")

st.divider()

# --- Player overrides ----------------------------------------------------------
st.subheader("Override a player's stats for one match")
st.caption("For a bad capture — a lag-out, a stat that clearly didn't record right, etc.")

player_matches = storage.read_csv(config.TABLE_PLAYER_MATCHES, dtype={"matchId": str})
our_players = player_matches[player_matches["is_our_club"].astype(str).str.lower() == "true"] if not player_matches.empty else pd.DataFrame()

if our_players.empty:
    st.caption("No player data yet.")
else:
    match_choice = st.selectbox(
        "Match",
        options=our_matches.sort_values("date", ascending=False).apply(
            lambda r: f"{r['date']}  vs {r['opponent_club_name']}  ({r['matchId']})", axis=1
        ).tolist(),
    )
    chosen_match_id = match_choice.split("(")[-1].rstrip(")")
    roster_for_match = our_players[our_players["matchId"] == chosen_match_id]

    if roster_for_match.empty:
        st.caption("No players captured for that match.")
    else:
        player_choice = st.selectbox("Player", options=sorted(roster_for_match["player_name"].unique()))
        raw = roster_for_match[roster_for_match["player_name"] == player_choice].iloc[0]

        # If an override already exists for this match+player, the form should
        # start from THAT (not the raw capture) — otherwise re-opening this
        # page always shows the original numbers and looks like your last
        # save never happened, even though it's correctly applied everywhere
        # else in the app.
        existing_overrides = storage.read_csv(config.TABLE_PLAYER_OVERRIDES, dtype=str)
        existing = pd.DataFrame()
        if not existing_overrides.empty:
            existing = existing_overrides[
                (existing_overrides["matchId"].astype(str).str.strip() == str(chosen_match_id).strip())
                & (existing_overrides["player_name"].astype(str).str.strip() == player_choice.strip())
            ]

        def _starting_value(field, cast):
            if not existing.empty and str(existing.iloc[0].get(field, "")).strip() != "":
                return cast(existing.iloc[0][field])
            return cast(raw[field])

        if not existing.empty:
            st.info(f"An override is already saved for {player_choice} in this match — editing it below.")
        current_exclude = not existing.empty and str(existing.iloc[0].get("exclude", "")).strip().upper() == "TRUE"

        with st.form("override_form"):
            c1, c2, c3, c4 = st.columns(4)
            rating = c1.number_input("Rating", value=_starting_value("rating", float), min_value=0.0, max_value=10.0, step=0.1)
            goals = c2.number_input("Goals", value=_starting_value("goals", int), min_value=0, step=1)
            assists = c3.number_input("Assists", value=_starting_value("assists", int), min_value=0, step=1)
            shots = c4.number_input("Shots", value=_starting_value("shots", int), min_value=0, step=1)
            c5, c6, c7 = st.columns(3)
            passes_made = c5.number_input("Passes made", value=_starting_value("passes_made", int), min_value=0, step=1)
            pass_attempts = c6.number_input("Pass attempts", value=_starting_value("pass_attempts", int), min_value=0, step=1)
            tackles_made = c7.number_input("Tackles made", value=_starting_value("tackles_made", int), min_value=0, step=1)
            exclude_player = st.checkbox("Exclude this player from this match entirely", value=current_exclude)
            submitted = st.form_submit_button("💾 Save override", type="primary")

        if submitted:
            overrides = storage.read_csv(config.TABLE_PLAYER_OVERRIDES, dtype=str)
            if overrides.empty:
                overrides = pd.DataFrame(columns=[
                    "matchId", "date_str", "player_name", "rating", "passes_made", "pass_attempts",
                    "goals", "assists", "shots", "tackles_made", "red_cards", "exclude",
                ])
            overrides = overrides[
                ~((overrides["matchId"] == chosen_match_id) & (overrides["player_name"] == player_choice))
            ]
            new_row = {
                "matchId": chosen_match_id, "date_str": raw["date"], "player_name": player_choice,
                "rating": rating, "passes_made": passes_made, "pass_attempts": pass_attempts,
                "goals": goals, "assists": assists, "shots": shots, "tackles_made": tackles_made,
                "red_cards": raw.get("red_cards", 0), "exclude": "TRUE" if exclude_player else "FALSE",
            }
            overrides = pd.concat([overrides, pd.DataFrame([new_row])], ignore_index=True)
            storage.write_csv(config.TABLE_PLAYER_OVERRIDES, overrides)
            st.cache_data.clear()
            st.success(f"Saved override for {player_choice} in that match.")
