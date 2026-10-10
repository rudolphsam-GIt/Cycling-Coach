from __future__ import annotations

import streamlit as st
from datetime import date, datetime

import ftp_change
import compare
from metrics.tss import STANDARDS
from db.queries import (get_setting, set_setting, auto_max_hr, auto_resting_hr,
                        recalculate_all_tss, deduplicate_activities)
from db import schema
from config import STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, GARMIN_EMAIL, GARMIN_PASSWORD
import auth.strava as strava_auth
import auth.garmin as garmin_auth
import auth.intervals as intervals_auth
import auth.trainingpeaks as tp_auth
from auth import tp_login
from components import ftp_help
from components.units import distance_switch, unit_switch, weight_input
from metrics.explain import (DEFAULT_GENDER, GENDER_LABELS, GENDER_PROFILE_TABLE,
                             age_from_birth_year)
from components.cards import page_header
from components.explain import setting_help
from components.onboarding import GOAL_EXAMPLES, goal_keys_to_labels, infer_goal_keys, parse_goal_keys


page_header("Settings", "Your profile, connected accounts and data tools")

tab_profile, tab_connections, tab_data = st.tabs([":material/person: Profile",
                                                  ":material/link: Connections" if schema.is_owner() else ":material/upload: Rides",
                                                  ":material/build: Data tools"])



def _score_like() -> None:
    """Choose which platform the app scores like. A change rescores every ride. When that
    platform is connected, its thresholds can be copied in and its fitness shown next to the app's."""
    if msg := st.session_state.pop("score_like_msg", None):
        (st.success if msg[0] == "ok" else st.error)(msg[1])
    current = compare.standard()
    keys = list(STANDARDS)
    choice = st.selectbox(
        "Score like", keys, index=keys.index(current), format_func=lambda k: STANDARDS[k]["label"],
        key="score_like_select",
        help="How rides are scored, and which service the app checks its scores against. Power is "
             "scored the same way (Coggan's TSS) by all three. "
             + " ".join(f"{v['label']}: {v['about']}" for v in STANDARDS.values()))
    st.caption(STANDARDS[choice]["about"])
    if choice != current:
        set_setting("score_like", choice)
        with st.spinner("Rescoring your rides…"):
            n = recalculate_all_tss()
        st.session_state["score_like_msg"] = ("ok", f"Scoring like {STANDARDS[choice]['label']}. "
                                                    f"Updated TSS for {n} activities.")
        st.rerun()

    service = STANDARDS[choice]["compare"]
    if not service or not compare.connected(service):
        return
    name = compare.service_name(service)
    if st.button(f"Use thresholds from {name}", key="copy_thresholds", icon=":material/download:",
                 help=f"Copies FTP and LTHR from {name}, so both score rides on the same numbers. "
                      "A new FTP counts from today; past rides keep the FTP they were ridden at."):
        try:
            th, fit = _service_thresholds(service)
        except Exception as e:
            st.session_state["score_like_msg"] = ("err", f"Couldn't read {name}. {e}")
        else:
            st.session_state["score_like_msg"] = ("ok", _apply_thresholds(name, th, fit))
        st.rerun()


def _service_thresholds(service: str) -> tuple[dict, float | None]:
    """The service's thresholds and its fitness (CTL) today."""
    today = date.today().isoformat()
    if service == "trainingpeaks":
        c = tp_auth.Client()
        days = c.daily_fitness(today, today)
        return c.thresholds(), (days.get(today) or {}).get("ctl")
    days = intervals_auth.daily_fitness(today, today)
    return intervals_auth.thresholds(), (days.get(today) or {}).get("ctl")


def _apply_thresholds(name: str, th: dict, service_ctl: float | None) -> str:
    from metrics.training_load import get_current_metrics
    bits = []
    ftp, lthr = th.get("ftp"), th.get("lthr")
    if ftp and int(ftp) != int(float(get_setting("ftp_watts", 0) or 0)):
        ftp_change.apply_new_ftp(int(ftp), f"From {name}")
        set_setting("ftp_estimated", "0")
        bits.append(f"FTP {int(ftp)} W")
    if lthr and int(lthr) != int(float(get_setting("lthr", 0) or 0)):
        set_setting("lthr", int(lthr))
        set_setting("lthr_estimated", "0")
        recalculate_all_tss()           # LTHR has no history, so heart rate scores follow it everywhere
        bits.append(f"LTHR {int(lthr)} bpm")
    text = (f"Copied from {name}: " + ", ".join(bits) + "." if bits
            else f"FTP and LTHR already match {name}.")
    ctl = get_current_metrics()["ctl"]
    if service_ctl is not None:
        text += f" Fitness today: {ctl:.1f} here, {float(service_ctl):.1f} in {name}."
    return text


# ── Tab 1: Athlete Profile ────────────────────────────────────────────────────
with tab_profile:
    st.subheader("Athlete Profile")

    ftp_help.render("settings_ftp", snoozable=False, show_lower=True)

    goal_text = st.text_area(
        "Your goals", value=get_setting("goal_text", "") or "; ".join(
            goal_keys_to_labels(parse_goal_keys(get_setting("primary_goal", "")))),
        height=90, placeholder="In your own words. " + "; ".join(GOAL_EXAMPLES[:3]),
        help="Anything you want from riding. Your coach plans around what you write.",
    )
    g_col, a_col = st.columns(2)
    saved_gender = get_setting("gender", "") or DEFAULT_GENDER
    gender_label = g_col.selectbox(
        "Gender", list(GENDER_LABELS), index=list(GENDER_LABELS.values()).index(saved_gender),
        help="Used only to pick typical power ranges, which differ between women and men. Non-binary and "
                 "Prefer not to say use an average of the two. You can change it any time in Settings.")
    saved_age = age_from_birth_year(get_setting("birth_year", ""))
    age = a_col.number_input("Age", min_value=12, max_value=95, value=saved_age, step=1,
                             placeholder="Optional",
                             help="Power and heart rate change with age. Used for the starting estimates "
                                  "of FTP and threshold heart rate. Only your birth year is stored.")
    t1, t2 = st.columns(2)
    weekly_hours = t1.slider("Hours a week to train", 1, 20,
                             int(float(get_setting("weekly_hours_target", 6) or 6)))
    days_per_week = t2.slider("Days a week to train", 1, 7,
                              int(float(get_setting("days_per_week", 4) or 4)))

    col1, col2 = st.columns(2)
    with col1:
        ftp = st.number_input(
            "FTP (watts)", min_value=0, max_value=600,
            value=int(get_setting("ftp_watts", 200) or 200), step=5,
            help=setting_help("ftp"),
        )
        unit = unit_switch("settings_unit")
        distance_switch("settings_distance", label="Distance units (miles also means feet and mph)")
        weight = weight_input("Weight", float(get_setting("weight_kg", 70) or 70), key="settings_weight",
                              unit=unit, min_kg=30.0, max_kg=200.0, help=setting_help("weight"))
    with col2:
        lthr = st.number_input(
            "LTHR (bpm)", min_value=0, max_value=220,
            value=int(get_setting("lthr", 155) or 155), step=1,
            help=setting_help("lthr"),
        )
        _score_like()
        auto_max, auto_rest = auto_max_hr(), auto_resting_hr()
        h1, h2 = st.columns(2)
        max_hr_in = h1.number_input(
            "Max HR (bpm)", min_value=0, max_value=230, step=1,
            value=int(float(get_setting("max_hr_manual", 0) or 0)) or None, placeholder=(
                f"Auto: {auto_max:.0f}" if auto_max else "Auto"),
            help="Used by intervals.icu style and the published standard, for heart rate scores. Leave "
                 "empty to use the highest heart rate "
                 "that more than one of your rides reached in the last year, which skips strap glitches.")
        rest_hr_in = h2.number_input(
            "Resting HR (bpm)", min_value=0, max_value=120, step=1,
            value=int(float(get_setting("resting_hr_manual", 0) or 0)) or None, placeholder=(
                f"Auto: {auto_rest:.0f}" if auto_rest else "Auto"),
            help="Used by intervals.icu style and the published standard, for heart rate scores. Leave "
                 "empty to use your Garmin resting "
                 "heart rate averaged over the last 30 days.")
        init_ctl = st.number_input(
            "Starting CTL", min_value=0.0, max_value=200.0,
            value=float(get_setting("ctl_start", 0) or 0), step=1.0,
            help=setting_help("ctl_start"),
        )

    if st.button("Save profile", type="primary", icon=":material/save:"):
        old_ftp = int(get_setting("ftp_watts", 0) or 0)
        old_lthr = int(get_setting("lthr", 0) or 0)
        old_hr = (get_setting("max_hr_manual", "") or "", get_setting("resting_hr_manual", "") or "",
                  get_setting("gender", "") or "")
        set_setting("max_hr_manual", int(max_hr_in) if max_hr_in else "")
        set_setting("resting_hr_manual", int(rest_hr_in) if rest_hr_in else "")
        set_setting("weight_kg", weight)
        set_setting("weight_unit", unit)
        set_setting("lthr", lthr)
        set_setting("ctl_start", init_ctl)
        if age:
            set_setting("birth_year", date.today().year - int(age))
        set_setting("gender", GENDER_LABELS[gender_label])
        if GENDER_LABELS[gender_label] in GENDER_PROFILE_TABLE:
            set_setting("power_profile_table", GENDER_PROFILE_TABLE[GENDER_LABELS[gender_label]])
        set_setting("goal_text", goal_text.strip())
        set_setting("primary_goal", ",".join(infer_goal_keys(goal_text)))
        set_setting("weekly_hours_target", weekly_hours)
        set_setting("days_per_week", days_per_week)
        ftp_note = ""
        if ftp != old_ftp and ftp > 0:
            # Past rides keep the FTP they were ridden at; upcoming workouts follow the new one.
            ftp_note = ftp_change.summary(ftp_change.apply_new_ftp(ftp))
            set_setting("ftp_estimated", "0")   # the rider set it themselves
        if lthr != old_lthr:
            set_setting("lthr_estimated", "0")
        new_hr = (get_setting("max_hr_manual", "") or "", get_setting("resting_hr_manual", "") or "",
                  get_setting("gender", "") or "")
        if (lthr != old_lthr and lthr > 0) or new_hr != old_hr:
            # LTHR, max and resting heart rate have no history, so hrTSS follows them everywhere.
            with st.spinner("Updating TSS and zones for your rides…"):
                n = recalculate_all_tss()
            st.success(f"Profile saved. TSS and zones updated for {n} rides.")
        else:
            st.success("Profile saved." + (" Past rides keep the TSS they earned on your old FTP."
                                           if ftp != old_ftp and ftp > 0 else ""))
        if ftp_note:
            st.info(ftp_note)

    resend = ftp_change.last_garmin_result()
    if ftp_change.is_resending():
        st.caption("Updating your upcoming workouts on Garmin for the new FTP…")
    elif resend:
        (st.caption if resend.get("ok") else st.warning)(resend["text"])

# ── Tab 2: Connections ────────────────────────────────────────────────────────


def _import_files(label: str) -> None:
    import_files = st.file_uploader(label, type=["fit", "csv"], accept_multiple_files=True,
                                    key="garmin_import")
    imperial = st.radio("Units in the file", ["Miles and feet", "Kilometers and meters"],
                        horizontal=True, key="import_units") == "Miles and feet"
    if import_files and st.button("Import", width="stretch"):
        from auth.fit_import import import_fit_files, import_csv_files
        fit = [f for f in import_files if f.name.lower().endswith(".fit")]
        csv = [f for f in import_files if f.name.lower().endswith(".csv")]
        total, msgs = 0, []
        if fit:
            n, m = import_fit_files(fit); total += n; msgs.append(m)
        if csv:
            n, m = import_csv_files(csv, imperial=imperial); total += n; msgs.append(m)
        (st.success if total else st.error)(" · ".join(msgs))
        if total:
            st.rerun()


if schema.is_owner():
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
                if garmin_auth.is_connected() and last_sync not in ("Never", "") and \
                        (datetime.utcnow() - datetime.fromisoformat(
                            get_setting("strava_last_sync", "") or "2000-01-01T00:00:00")).days > 14:
                    st.caption("Garmin is connected too and has been bringing in your rides, so Strava "
                               "only needs a sync if you ride something that goes to Strava alone.")
                if err := st.session_state.pop("strava_first_sync_error", None):
                    st.warning(f"Strava connected, but the first sync didn't finish. {err}")
                if st.button("Sync Strava (60 days)", icon=":material/sync:", width="stretch"):
                    try:
                        with st.spinner("Syncing from Strava..."):
                            count, msg = strava_auth.sync_activities(STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET)
                        st.success(msg)
                    except strava_auth.StravaError as e:
                        st.error(str(e))
                if st.button("Disconnect Strava", width="stretch"):
                    strava_auth.clear_tokens()
                    st.rerun()
            else:
                st.info("Not connected")
                if st.button("Connect Strava", width="stretch", type="primary"):
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
                            except Exception as e:
                                st.error("Couldn't connect to Strava. Copy the whole address from your browser after you approve, "
                                         f"then paste it again. Details: {e}")
                            else:
                                st.session_state["strava_connecting"] = False
                                try:
                                    strava_auth.sync_activities(STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET)
                                except strava_auth.StravaError as e:
                                    # Connected fine; only the first sync failed, so the button can retry it.
                                    st.session_state["strava_first_sync_error"] = str(e)
                                st.rerun()
                    else:
                        st.error("Couldn't find the auth code in that URL. Make sure you copied the full address bar.")

        # ── Garmin ────────────────────────────────────────────────────────────────
        with col_garmin:
            st.subheader("Garmin")

            def _garmin_first_sync():
                st.session_state.pop("garmin_login_state", None)
                with st.spinner("Connected! Pulling your last 90 days of rides and recovery…"):
                    _, msg = garmin_auth.sync(days_back=90)
                st.session_state["garmin_sync_msg"] = msg
                st.rerun()

            if garmin_auth.is_connected():
                last_garmin = get_setting("garmin_last_sync", "") or "Never"
                if last_garmin != "Never":
                    from components.coach_ui import local_time
                    last_garmin = local_time(last_garmin)
                st.success(f"Connected · Last sync: {last_garmin}")
                st.caption("Rides, sleep, HRV, resting heart rate and readiness sync on their own "
                           "when you open the app.")
                _rs = garmin_auth.recovery_status()
                if _rs["last_date"] is None:
                    st.warning("Garmin hasn't sent any sleep or recovery numbers yet. Open the Garmin Connect "
                               "app on your phone to sync your watch.", icon=":material/watch:")
                elif _rs["stale"]:
                    _d = date.fromisoformat(_rs["last_date"])
                    st.warning(f"Rides are up to date, but Garmin hasn't sent sleep or recovery since "
                               f"{_d:%b} {_d.day}. Your watch needs to sync with the Garmin Connect app "
                               "on your phone.", icon=":material/watch:")
                if st.button("Sync Garmin now (30 days)", icon=":material/sync:", width="stretch"):
                    with st.spinner("Syncing from Garmin…"):
                        _, msg = garmin_auth.sync(days_back=30)
                    st.session_state["garmin_sync_msg"] = msg
                    st.rerun()
                if st.button("Load ride history from Garmin (1 year)", icon=":material/bolt:",
                             width="stretch",
                             help="For rides already in the app: reads your best power and heart rate for 5 s up "
                                  "to 2 h, and for rides that came from Strava, Garmin's normalized power and timer "
                                  "time, so their TSS matches TrainingPeaks. Adds no rides. Heart rate needs each "
                                  "ride's file, so the first run takes a minute or two."):
                    bar = st.progress(0.0, text="Reading rides from Garmin…")
                    try:
                        updated, seen = garmin_auth.backfill_peaks(
                            days_back=365,
                            progress=lambda done, total: bar.progress(done / max(total, 1),
                                                                      text=f"Ride {done} of {total}"))
                        msg = (f"Updated {updated} of {seen} rides from Garmin: peak power, heart rate, "
                               "and normalized power and timer time for rides that came from Strava.")
                    except Exception as e:
                        msg = garmin_auth.friendly_error(e)
                    st.session_state["garmin_sync_msg"] = msg
                    st.rerun()
                if st.button("Disconnect Garmin", width="stretch"):
                    garmin_auth.disconnect()
                    st.rerun()
            elif st.session_state.get("garmin_login_state") is None:
                st.info("Connect once and your rides and recovery data sync automatically from then on.")
                env_email = GARMIN_EMAIL if GARMIN_EMAIL and GARMIN_EMAIL != "your@email.com" else ""
                env_password = GARMIN_PASSWORD if GARMIN_PASSWORD and GARMIN_PASSWORD != "your_password" else ""
                with st.form("garmin_login"):
                    email = st.text_input("Garmin email", value=env_email)
                    password = st.text_input(
                        "Garmin password", type="password",
                        placeholder="Leave blank to use the password in your .env file" if env_password else "",
                    )
                    submitted = st.form_submit_button("Connect Garmin", type="primary",
                                                      width="stretch")
                if submitted:
                    try:
                        with st.spinner("Logging in to Garmin…"):
                            status, state = garmin_auth.start_login(email, password or env_password)
                    except Exception as e:
                        st.error(garmin_auth.friendly_error(e))
                    else:
                        if status == "needs_code":
                            st.session_state["garmin_login_state"] = state
                            st.rerun()
                        _garmin_first_sync()
            else:
                st.info("Garmin sent you a verification code by email or text. Enter it below.")
                with st.form("garmin_code"):
                    code = st.text_input("Verification code", max_chars=10)
                    verified = st.form_submit_button("Verify", type="primary", width="stretch")
                if st.button("Cancel", width="stretch"):
                    st.session_state.pop("garmin_login_state", None)
                    st.rerun()
                if verified and code.strip():
                    try:
                        with st.spinner("Verifying…"):
                            garmin_auth.finish_login(st.session_state["garmin_login_state"], code)
                    except Exception as e:
                        st.error(garmin_auth.friendly_error(e) + " If the code expired, cancel and start again.")
                    else:
                        _garmin_first_sync()

            if "garmin_sync_msg" in st.session_state:
                msg = st.session_state.pop("garmin_sync_msg")
                (st.success if msg.startswith("Synced") else st.error)(msg)

            with st.expander("Import .fit or .csv files by hand"):
                _import_files("Upload .fit or .csv from Garmin Connect")

        # ── Plan export: intervals.icu and TrainingPeaks ─────────────────────────────
        st.divider()
        col_iv, col_tp = st.columns(2)

        with col_iv:
            st.subheader("Intervals.icu")
            st.caption("A free training calendar. The app puts your planned rides on it with their dates, and "
                       "intervals.icu passes them to Zwift on every computer you ride on, and to Garmin.")
            if msg := st.session_state.pop("intervals_msg", None):
                (st.success if msg[0] == "ok" else st.error)(msg[1])
            if intervals_auth.is_connected():
                st.success("Connected. Send rides from Plan, Manage, Export your plan.")
                if st.button("Test connection", key="iv_test", width="stretch"):
                    try:
                        st.session_state["intervals_msg"] = ("ok", f"Working. Signed in as {intervals_auth.check()}.")
                    except intervals_auth.IntervalsError as e:
                        st.session_state["intervals_msg"] = ("err", str(e))
                    st.rerun()
                if st.button("Disconnect intervals.icu", key="iv_off", width="stretch"):
                    set_setting(intervals_auth.KEY_SETTING, "")
                    st.rerun()
            else:
                st.markdown("1. Make a free account at intervals.icu.\n"
                            "2. In intervals.icu open Settings, scroll to Developer Settings and copy your API key.\n"
                            "3. Paste it here.\n"
                            "4. In intervals.icu Settings, connect Zwift (and Garmin if you like). Rides you send "
                            "then show in Zwift under Custom Workouts, intervals.icu, on their days.")
                with st.form("iv_form"):
                    key = st.text_input("API key", type="password")
                    if st.form_submit_button("Connect intervals.icu", type="primary", width="stretch"):
                        try:
                            who = intervals_auth.check(key.strip())
                        except intervals_auth.IntervalsError as e:
                            st.session_state["intervals_msg"] = ("err", str(e))
                        else:
                            set_setting(intervals_auth.KEY_SETTING, key.strip())
                            st.session_state["intervals_msg"] = ("ok", f"Connected as {who}.")
                        st.rerun()

        with col_tp:
            st.subheader("TrainingPeaks calendar")
            st.info("**Needs TrainingPeaks Premium.** Free accounts can only hold planned workouts for today "
                    "and tomorrow. On a free account, use Download for TrainingPeaks on the Plan page "
                    "instead.", icon=":material/workspace_premium:")
            st.caption("Puts your planned rides on their days in TrainingPeaks and keeps them up to date on its "
                       "own as your plan changes. Unofficial: TrainingPeaks has no public way for apps like this "
                       "one to add workouts, so this uses the same connection their website uses. It can stop "
                       "working whenever TrainingPeaks changes its site and may go against their terms.")
            if msg := st.session_state.pop("tp_msg", None):
                {"ok": st.success, "warn": st.warning}.get(msg[0], st.error)(msg[1])

            def _connected(info: dict) -> None:
                note = (" Your account isn't Premium, so only today and tomorrow will sync."
                        if info["premium"] is False else "")
                st.session_state["tp_msg"] = ("warn" if note else "ok",
                                              f"Connected as {info['name']}. Your plan syncs on its own.{note}")

            if tp_auth.is_enabled():
                if tp_auth.needs_signin():
                    st.warning("TrainingPeaks signed you out, so syncing has paused. Sign in again below.",
                               icon=":material/lock:")
                else:
                    name = get_setting(tp_auth.NAME_SETTING, "") or "your account"
                    plan = " (Premium)" if tp_auth.is_premium() else ""
                    st.success(f"Connected as {name}{plan}. {tp_auth.last_sync_text()}.")
                if tp_auth.is_premium() is False:
                    st.warning("This account isn't Premium, so only today's and tomorrow's rides sync.")
            ok_unofficial = tp_auth.is_enabled() or st.checkbox(
                "I understand this is unofficial and may stop working", key="tp_ok")
            if not tp_auth.is_enabled() or tp_auth.needs_signin():
                if not tp_login.available():
                    st.caption(tp_login.INSTALL_HINT)
                elif st.button("Sign in to TrainingPeaks", type="primary", icon=":material/login:",
                               width="stretch", disabled=not ok_unofficial, key="tp_signin",
                               help="Opens a Chrome window. Sign in there as you normally would. The app never "
                                    "sees your password."):
                    with st.spinner("A Chrome window opened. Sign in to TrainingPeaks there…"):
                        try:
                            _connected(tp_auth.connect(tp_login.sign_in()))
                        except (tp_login.LoginError, tp_auth.TPError) as e:
                            st.session_state["tp_msg"] = ("err", str(e))
                    st.rerun()
            if tp_auth.is_enabled():
                b1, b2 = st.columns(2)
                if b1.button("Test connection", key="tp_test", width="stretch"):
                    try:
                        _connected(tp_auth.check())
                    except tp_auth.TPError as e:
                        st.session_state["tp_msg"] = ("err", str(e))
                    st.rerun()
                if b2.button("Turn off", key="tp_off", width="stretch"):
                    tp_auth.disconnect()
                    st.rerun()
            else:
                with st.expander("Other way: paste a cookie"):
                    st.caption("For when Chrome isn't installed.")
                    st.markdown("1. Sign in at app.trainingpeaks.com.\n"
                                "2. Open the developer tools (in Chrome, View, Developer, Developer Tools), then the "
                                "Application tab (Storage in Safari), then Cookies, tpapi.trainingpeaks.com.\n"
                                "3. Copy the value of the cookie named Production_tpAuth and paste it here.\n"
                                "4. It lasts a few weeks. When it runs out the app asks for a fresh one.")
                    with st.form("tp_form"):
                        cookie = st.text_input("Production_tpAuth cookie", type="password")
                        if st.form_submit_button("Turn on", width="stretch"):
                            if not ok_unofficial:
                                st.session_state["tp_msg"] = ("err", "Tick the box above first.")
                            else:
                                try:
                                    _connected(tp_auth.connect(cookie.strip()))
                                except tp_auth.TPError as e:
                                    st.session_state["tp_msg"] = ("err", str(e))
                            st.rerun()

else:
    with tab_connections:
        st.info("Garmin, Strava, TrainingPeaks and intervals.icu connect on your own profile only, "
                "so nobody else's passwords are stored here. Add this athlete's rides from files "
                "they send you.", icon=":material/lock:")
        st.subheader("Import rides")
        st.caption("Ask them to export rides from Garmin Connect or Strava as .fit files. "
                   "Set their FTP and LTHR on the Profile tab first so each ride is scored right.")
        _import_files("Upload .fit or .csv files")


# ── Tab 3: Data Tools ─────────────────────────────────────────────────────────
with tab_data:
    st.subheader("Data Tools")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Recalculate TSS**")
        st.caption("Recomputes TSS and zone estimates for every ride, each on the FTP you had that day "
                   "(from your FTP history) and your current LTHR.")
        if st.button("Recalculate TSS", width="stretch"):
            with st.spinner("Recalculating TSS for every ride…"):
                n = recalculate_all_tss()
            st.success(f"Recalculated TSS for {n} activities.")

    with col_b:
        st.markdown("**Remove duplicate rides**")
        st.caption("Removes rides logged on both Strava and Garmin and keeps the one with more data.")
        if st.button("Remove duplicates", width="stretch"):
            with st.spinner("Looking for duplicate rides…"):
                n = deduplicate_activities()
            st.success(f"Removed {n} duplicate ride{'s' if n != 1 else ''}." if n else "No duplicates found.")

    if not schema.is_owner():
        st.divider()
        st.markdown("**Remove this athlete**")
        st.caption("Moves their data to the backups folder and switches back to your own profile.")
        if st.checkbox("I'm sure", key="remove_athlete_sure") and \
                st.button("Remove athlete", type="secondary", key="remove_athlete"):
            from db import profiles
            from components import profile_switcher
            gone = st.session_state.get("profile")
            profile_switcher.switch_to(profiles.OWNER)
            profiles.delete_profile(gone)
            st.rerun()
