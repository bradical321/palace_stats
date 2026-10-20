"""Shared sidebar, data loading, and small render helpers used by every page."""
from __future__ import annotations

import base64
import os

import streamlit as st

import config
import transform
from storage import get_storage

ADMIN_PASSWORD_ENV = "FC_ADMIN_PASSWORD"
LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "palace_logo.png")


@st.cache_resource
def _logo_b64() -> str:
    with open(LOGO_PATH, "rb") as f:
        return base64.b64encode(f.read()).decode()


@st.cache_data(ttl=300, show_spinner="Loading data...")
def _load_tagged_matches_cached(_storage, cache_key: int):
    # `_storage` is excluded from the cache key (leading underscore) since it
    # isn't hashable in a meaningful way; `cache_key` lets the sidebar's
    # "Refresh data" button force a true reload on demand.
    return transform.load_tagged_matches(_storage)


def render_sidebar() -> str:
    """Club header + the League / Comp / All filter every page shares.
    Returns the selected filter group name."""
    st.sidebar.markdown(
        f'<h1 style="display:flex;align-items:center;gap:0.5rem;padding-top:0">'
        f'<img src="data:image/png;base64,{_logo_b64()}" style="height:2.2rem;margin-right:0.75rem" alt="">'
        f'{config.CLUB_NAME}</h1>',
        unsafe_allow_html=True,
    )
    st.sidebar.caption(f"Club ID {config.CLUB_ID} · {config.PLATFORM}")

    if "data_cache_key" not in st.session_state:
        st.session_state["data_cache_key"] = 0
    if st.sidebar.button("🔄 Refresh data", use_container_width=True):
        st.session_state["data_cache_key"] += 1
        st.cache_data.clear()

    group = st.sidebar.radio(
        "Which games?",
        options=["League", "Comp", "All"],
        index=2,
        help=(
            "League = regular EAFC clubs games. "
            "Comp = UFL 10v10 games (tagged on the Admin page). "
            "All = League + Comp + Friendlies/Cups."
        ),
    )
    st.sidebar.divider()
    return group


def load_filtered_data(group: str):
    storage = get_storage()
    matches, player_matches = _load_tagged_matches_cached(storage, st.session_state.get("data_cache_key", 0))
    return transform.filter_by_group(matches, player_matches, group)


def needs_review_count() -> int:
    storage = get_storage()
    matches, _ = _load_tagged_matches_cached(storage, st.session_state.get("data_cache_key", 0))
    if matches.empty:
        return 0
    return int((matches["Match_Type"] == config.MATCH_TAG_NEEDS_REVIEW).sum())


def result_chip_html(result: str) -> str:
    color = config.RESULT_COLOR.get(result, config.RATING_NEUTRAL)
    return (
        f'<span style="display:inline-flex;align-items:center;justify-content:center;'
        f'width:26px;height:26px;border-radius:6px;background:{color};color:#fff;'
        f'font-weight:700;font-size:13px;font-family:system-ui,-apple-system,sans-serif;">{result}</span>'
    )


def rating_chip_html(rating: float) -> str:
    if rating is None:
        return ""
    color = transform.rating_color(rating)
    return (
        f'<span style="display:inline-flex;align-items:center;justify-content:center;'
        f'min-width:38px;padding:2px 6px;border-radius:6px;background:{color};color:#fff;'
        f'font-weight:700;font-size:13px;font-family:system-ui,-apple-system,sans-serif;">{rating:.1f}</span>'
    )


def _get_admin_password() -> str | None:
    pw = os.environ.get(ADMIN_PASSWORD_ENV)
    if pw:
        return pw
    try:
        return st.secrets.get(ADMIN_PASSWORD_ENV)  # type: ignore[attr-defined]
    except Exception:
        return None


def require_admin_password() -> bool:
    """Gate a page behind a password. Returns True once unlocked (and stays
    unlocked for the rest of the session); call `st.stop()` right after this
    returns False so nothing below it renders."""
    expected = _get_admin_password()

    if not expected:
        st.warning(
            f"⚠️ No admin password configured — this page is currently open to anyone. "
            f"Set `{ADMIN_PASSWORD_ENV}` as an env var (or a Streamlit secret) to lock it down."
        )
        return True

    if st.session_state.get("admin_unlocked"):
        return True

    st.title("🔒 Admin")
    pw = st.text_input("Password", type="password", key="admin_pw_input")
    if st.button("Unlock"):
        if pw == expected:
            st.session_state["admin_unlocked"] = True
            st.rerun()
        else:
            st.error("Wrong password.")
    return False


def form_strip_html(results: list[str]) -> str:
    chips = "".join(f'<span style="margin-right:4px;">{result_chip_html(r)}</span>' for r in results)
    return f'<div style="display:flex;flex-direction:row;">{chips}</div>'
