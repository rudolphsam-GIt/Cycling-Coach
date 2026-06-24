from __future__ import annotations

import streamlit as st
from datetime import date

from db.schema import run_migrations
from db.queries import (get_setting, set_setting, log_ftp_history,
                        recalculate_all_tss, deduplicate_activities)
from config import STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, GARMIN_EMAIL, GARMIN_PASSWORD
import auth.strava as strava_auth
import auth.garmin as garmin_auth
from components.styles import inject_styles
from components.onboarding import GOALS, parse_goal_keys, goal_keys_to_labels

run_migrations()

st.set_page_config(page_title="Settings", page_icon="⚙️", layout="wide")
inject_styles()
st.title("⚙️ Settings")

tab_profile, tab_connections, tab_data = st.tabs(["👤 Profile", "🔗 Connections", "🛠 Data Tools"])

# ── Tab 1: Athlete Profile ────────────────────────────────────────────────────
with tab_profile:
    st.subheader("Athlete Profile")

    _current_goal_keys = parse_goal_keys(get_setting("primary_goal", ""))
    _current_labels = goal_keys_to_labels(_current_goal_keys)
    goal_labels = st.multiselect(
        "Goals", list(GOALS.keys()),
        default=_current_labels,
        help="Used to tailor AI Coach recommendations — pick one or more",
    )

    col1, col2 = st.columns(2)
    with col1:
        ftp = st.number_input(
            "FTP (watts)", min_value=0, max_value=600,
            value=int(get_setting("ftp_watts", 200) or 200), step=5,
            help="Functional Threshold Power — used for TSS, IF, and zone calculations",
        )
        weight = st.number_input(
            "Weight (kg)", min_value=30.0, max_value=200.0,
            value=float(get_setting("weight_kg", 70) or 70), step=0.5,
        )
    with col2:
        lthr = st.number_input(
            "LTHR (bpm)", min_value=0, max_value=220,
            value=int(get_setting("lthr", 155) or 155), step=1,
            help="Lactate Threshold Heart Rate — used for HR-based TSS and zone estimates",
        )
        init_ctl = st.number_input(
            "Starting CTL", min_value=0.0, max_value=200.0,
            value=float(get_setting("ctl_start", 0) or 0), step=1.0,
            help="Set this if you have prior training history. Leave at 0 to build from scratch.",
        )

    if st.button("Save Profile", type="primary"):
        old_ftp = int(get_setting("ftp_watts", 0) or 0)
        set_setting("ftp_watts", ftp)
        set_setting("weight_kg", weight)
        set_setting("lthr", lthr)
        set_setting("ctl_start", init_ctl)
        set_setting("primary_goal", ",".join(GOALS[g] for g in goal_labels))
        if ftp != old_ftp and ftp > 0:
            log_ftp_history(ftp)
        st.success("Profile saved!")

# ── Tab 2: Connections ────────────────────────────────────────────────────────
with tab_connections:
    col_strava, col_garmin = st.columns(2)

    # ── Strava ────────────────────────────────────────────────────────────────
    with col_strava:
        st.subheader("Strava")
        strava_connected = strava_auth.is_connected()

        if strava_connected:
            last_sync = get_setting("strava_last_sync", "Never")
            if last_sync and last_sync != "Never":
                last_sync = last_sync[:16].replace("T", " ")
            st.success(f"Connected · Last sync: {last_sync}")
            if st.button("Sync Strava (60 days)", use_container_width=True):
                with st.spinner("Syncing from Strava..."):
                    count, msg = strava_auth.sync_activities(STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET)
                st.success(msg) if "synced" in msg.lower() else st.error(msg)
                st.rerun()
            if st.button("Disconnect Strava", use_container_width=True):
                strava_auth.clear_tokens()
                st.rerun()
        else:
            st.info("Not connected")
            if st.button("Connect Strava", use_container_width=True, type="primary"):
                st.session_state["strava_connecting"] = True

        if st.session_state.get("strava_connecting"):
            auth_url = strava_auth.get_auth_url(STRAVA_CLIENT_ID)
            st.markdown(f"**Step 1:** [Authorize on Strava ↗]({auth_url})")
            st.caption("After authorizing, copy the full URL from your browser's address bar and paste below.")
            redirect_url = st.text_input("Paste redirect URL:")
            if redirect_url:
                code = strava_auth.extract_code_from_redirect(redirect_url)
                if code:
                    with st.spinner("Connecting..."):
                        try:
                            strava_auth.exchange_code(STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, code)
                            st.session_state["strava_connecting"] = False
                            st.success("Strava connected!")
                            strava_auth.sync_activities(STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Connection failed: {e}")
                else:
                    st.error("Couldn't find the auth code in that URL. Make sure you copied the full address bar.")

    # ── Garmin ────────────────────────────────────────────────────────────────
    with col_garmin:
        st.subheader("Garmin")
        garmin_configured = bool(GARMIN_EMAIL and GARMIN_EMAIL != "your@email.com")

        if not garmin_configured:
            st.warning("Add `GARMIN_EMAIL` and `GARMIN_PASSWORD` to your `.env` file.")
        else:
            has_tokens = garmin_auth._has_saved_tokens()
            last_garmin = get_setting("garmin_last_sync", "Never")
            if last_garmin and last_garmin != "Never":
                last_garmin = last_garmin[:16].replace("T", " ")

            if has_tokens:
                st.success(f"Connected · Last sync: {last_garmin}")
                if st.button("Sync Garmin (30 days)", use_container_width=True):
                    with st.spinner("Syncing from Garmin…"):
                        count, msg = garmin_auth.sync_activities(GARMIN_EMAIL, GARMIN_PASSWORD)
                    st.session_state["garmin_sync_msg"] = msg
                    st.rerun()
                if "garmin_sync_msg" in st.session_state:
                    msg = st.session_state.pop("garmin_sync_msg")
                    if any(w in msg.lower() for w in ("failed", "error", "rate", "unexpected")):
                        st.error(msg)
                    else:
                        st.success(msg)
                if st.button("Re-authenticate", use_container_width=True):
                    garmin_auth.clear_session()
                    st.info("Tokens cleared. Run `venv/bin/python scripts/garmin_setup.py` to re-authenticate.")
            else:
                st.warning("Not yet authenticated")
                st.markdown("""
Run this once in a terminal to set up Garmin auth
(handles two-factor login interactively):

```
cd /Users/sam/cycling-coach
venv/bin/python scripts/garmin_setup.py
```
""")

            st.divider()
            st.caption("Import rides manually while Garmin auth is being set up:")
            import_files = st.file_uploader(
                "Upload .fit or .csv from Garmin Connect",
                type=["fit", "csv"], accept_multiple_files=True, key="garmin_import",
            )
            if import_files and st.button("Import", use_container_width=True):
                from auth.fit_import import import_fit_files, import_csv_files
                fit = [f for f in import_files if f.name.lower().endswith(".fit")]
                csv = [f for f in import_files if f.name.lower().endswith(".csv")]
                total, msgs = 0, []
                if fit:
                    n, m = import_fit_files(fit); total += n; msgs.append(m)
                if csv:
                    n, m = import_csv_files(csv); total += n; msgs.append(m)
                (st.success if total else st.error)(" · ".join(msgs))
                if total:
                    st.rerun()

# ── Tab 3: Data Tools ─────────────────────────────────────────────────────────
with tab_data:
    st.subheader("Data Tools")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Recalculate TSS**")
        st.caption("Recomputes TSS and zone estimates for every ride using your current FTP and LTHR.")
        if st.button("Recalculate TSS", use_container_width=True):
            n = recalculate_all_tss()
            st.success(f"Recalculated TSS for {n} activities.")

    with col_b:
        st.markdown("**Remove Duplicate Rides**")
        st.caption("Removes rides logged on both Strava and Garmin — keeps the one with more data.")
        if st.button("Remove Duplicates", use_container_width=True):
            n = deduplicate_activities()
            st.success(f"Removed {n} duplicate ride{'s' if n != 1 else ''}." if n else "No duplicates found.")
