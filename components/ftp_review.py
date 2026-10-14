"""
The review that follows an FTP change. The app's own workouts already show the new watts; this
asks where else they should go (TrainingPeaks, intervals.icu, Garmin) before anything is sent.
TrainingPeaks' automatic sync waits until the rider answers.
"""
from __future__ import annotations

import streamlit as st

import ftp_change

HIDE_KEY = "ftp_review_hidden"


def _push(keys: list[str]) -> None:
    msgs = ftp_change.push(keys)
    st.toast(" ".join(msgs) or "Done.", icon=":material/cloud_upload:")


def _keep_old() -> None:
    ftp_change.keep_old_elsewhere()
    st.toast("Kept the old numbers on your other services. The app shows the new ones.")


def _done() -> None:
    ftp_change.clear_pending()


def _hide(at: str) -> None:
    st.session_state[HIDE_KEY] = at


def _service_ftps(at: str) -> dict[str, int]:
    """Read once per change and browser session, since it calls each service."""
    key = f"ftp_review_services_{at}"
    if key not in st.session_state:
        st.session_state[key] = ftp_change.service_ftps()
    return st.session_state[key]


def render(key: str = "ftp_review") -> None:
    """The review card, or a one line reminder after Not now. Draws nothing when no FTP change
    is waiting."""
    p = ftp_change.pending()
    if not p:
        return
    at = p.get("at", "")
    if st.session_state.get(HIDE_KEY) == at:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.caption(f"Your new FTP of {p['new']} W hasn't been sent to your other services yet.")
            st.button("Review", key=f"{key}_show", icon=":material/rule:",
                      on_click=lambda: st.session_state.pop(HIDE_KEY, None))
        return

    view = ftp_change.preview()
    dests = ftp_change.destinations()
    with st.container(border=True):
        st.markdown(f"**Your FTP changed from {view['old']} W to {view['new']} W.**")
        n = view["count"]
        st.markdown(f"{n} upcoming workout{'s' if n != 1 else ''} in the app now show{'' if n != 1 else 's'} "
                    f"watts for {view['new']} W. Their interval targets follow FTP too, so planned TSS "
                    "stays the same.")
        for name, before, after in view["examples"]:
            st.markdown(f"**{name}**  \n:gray[Was] ~~{before}~~  \n:gray[Now] {after}")

        for service, ftp in _service_ftps(at).items():
            if ftp != view["new"]:
                st.warning(f"{service} has your FTP at {ftp} W. Set it to {view['new']} W there as well, "
                           "since it works out each interval's watts from its own FTP.",
                           icon=":material/warning:")

        if not dests:
            st.caption("Nothing else is connected, so there is nothing to send.")
            st.button("Got it", key=f"{key}_done", type="primary", icon=":material/check:", on_click=_done)
            return

        st.markdown("**Send the updated workouts to**")
        chosen = [d["key"] for d in dests
                  if st.checkbox(f"{d['label']} ({d['count']} workout{'s' if d['count'] != 1 else ''} there)",
                                 value=True, key=f"{key}_{d['key']}")]
        with st.container(horizontal=True):
            st.button("Send updates", key=f"{key}_push", type="primary", icon=":material/cloud_upload:",
                      disabled=not chosen, on_click=_push, args=(chosen,))
            st.button("Not now", key=f"{key}_later", on_click=_hide, args=(at,),
                      help="Automatic sending to TrainingPeaks stays paused until you choose.")
            st.button("Keep the old numbers there", key=f"{key}_keep", on_click=_keep_old,
                      help="Your other services keep the workouts they have. The app shows the new watts.")
