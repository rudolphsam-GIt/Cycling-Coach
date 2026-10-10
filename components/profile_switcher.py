"""
Sidebar control for choosing whose training you're looking at: your own, or an athlete you coach.
The choice lives in this browser session only (session_state["profile"] and ["db_path"]).
"""
from __future__ import annotations

import streamlit as st

from db import profiles

_KEEP = {"profile", "db_path"}


def apply() -> None:
    """Point this session at the chosen athlete's database. Falls back to the owner if the
    chosen profile was removed."""
    slug = st.session_state.get("profile", profiles.OWNER)
    path = None
    try:
        path = profiles.path_for(slug)
    except ValueError:
        pass
    if slug != profiles.OWNER and (not path or not _exists(path)):
        slug, path = profiles.OWNER, profiles.path_for(profiles.OWNER)
    st.session_state["profile"] = slug
    st.session_state["db_path"] = path
    st.session_state["profile_pick"] = slug      # keeps the sidebar picker in step


def _exists(path: str) -> bool:
    import os
    return os.path.isfile(path)


def switch_to(slug: str) -> None:
    """Change athlete and forget everything the pages kept for the previous one."""
    if slug == st.session_state.get("profile"):
        return
    for key in list(st.session_state.keys()):
        if key not in _KEEP:
            del st.session_state[key]
    st.session_state["profile"] = slug
    st.session_state["db_path"] = profiles.path_for(slug)


def _on_pick() -> None:
    switch_to(st.session_state["profile_pick"])


def render() -> None:
    items = profiles.list_profiles()
    names = {p["slug"]: (f"{p['name']} (you)" if p["owner"] else p["name"]) for p in items}
    current = st.session_state.get("profile", profiles.OWNER)
    st.selectbox("Athlete", list(names), format_func=names.get, key="profile_pick",
                 on_change=_on_pick)
    if current != profiles.OWNER:
        st.markdown(f'<div class="profile-badge">Coaching <b>{_esc(names.get(current, current))}</b>. '
                    "Changes here only affect their plan.</div>", unsafe_allow_html=True)
    # Opens the Add athlete form in the main area (app.py shows it in place of the pages).
    from components import athlete_form
    st.button("Add athlete", icon=":material/person_add:", width="stretch", key="new_athlete_open",
              on_click=athlete_form.open_form, disabled=athlete_form.is_open())


def _esc(text: str) -> str:
    import html
    return html.escape(text or "")
