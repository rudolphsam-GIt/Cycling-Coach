from __future__ import annotations
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import date, timedelta
from components import inject_styles, section_header, metric_card

from db.schema import run_migrations
from db.queries import (get_races, add_race, delete_race, get_setting,
                         add_workout, get_workouts, log_race_result)
from metrics.training_load import get_current_metrics, project_future
from research.obra_schedule import get_upcoming_races, DISCIPLINES

run_migrations()

st.set_page_config(page_title="Race Prep", page_icon="🏁", layout="wide")
inject_styles()
st.title("🏁 Race Prep & Strategy")

ftp = float(get_setting("ftp_watts", 200) or 200)
weight = float(get_setting("weight_kg", 70) or 70)

tab1, tab2, tab3 = st.tabs(["📅 Race Calendar", "📉 Taper Planner", "⚡ Pacing Strategy"])

# ── Tab 1: Race Calendar ──────────────────────────────────────────────────────
with tab1:
    col_list, col_add = st.columns([2, 1])

    with col_add:
        st.subheader("Add Race")

        # OBRA race picker
        with st.expander("📋 Pick from OBRA schedule", expanded=True):
            disc_options = list(DISCIPLINES.keys())
            selected_discs = st.multiselect(
                "Disciplines", disc_options, default=["Road", "Criterium"]
            )
            col_past, col_fetch, col_refresh = st.columns([2, 2, 1])
            with col_past:
                include_past = st.checkbox("Include past races this year", value=False)
            with col_fetch:
                fetch_btn = st.button("Load OBRA Races", use_container_width=True)
            with col_refresh:
                refresh_btn = st.button("↺", help="Force refresh from OBRA")

            if fetch_btn or refresh_btn or "obra_races" in st.session_state:
                if fetch_btn or refresh_btn:
                    with st.spinner("Fetching OBRA schedule..."):
                        races_fetched = get_upcoming_races(
                            disciplines=selected_discs,
                            force_refresh=bool(refresh_btn),
                            include_past=include_past,
                        )
                    st.session_state["obra_races"] = races_fetched

                obra_races = st.session_state.get("obra_races", [])
                if obra_races:
                    upcoming_count = sum(1 for r in obra_races if not r.get("is_past"))
                    past_count = sum(1 for r in obra_races if r.get("is_past"))
                    count_label = f"{upcoming_count} upcoming"
                    if past_count:
                        count_label += f" + {past_count} past"
                    race_labels = {
                        f"{'✓ ' if r.get('is_past') else ''}{r['name']}  —  {r['date']}": r
                        for r in obra_races
                    }
                    chosen_label = st.selectbox(
                        f"{count_label} races found",
                        ["— select a race —"] + list(race_labels.keys()),
                    )
                    if chosen_label != "— select a race —":
                        obra_r = race_labels[chosen_label]
                        if st.button("Add this race to my calendar ➕", use_container_width=True):
                            add_race({
                                "name": obra_r["name"],
                                "date": obra_r["date"],
                                "distance_km": None,
                                "elevation_gain_meters": None,
                                "category": obra_r.get("category") or obra_r.get("discipline", "").replace("_", " ").title() or None,
                                "target_time_seconds": None,
                                "notes": obra_r.get("url", ""),
                            })
                            st.success(f"Added: {obra_r['name']}")
                            st.rerun()
                else:
                    st.info("No races found. Try adding more disciplines or enabling past races.")

        st.divider()
        with st.form("add_race_form", clear_on_submit=True):
            st.caption("Or add manually:")
            r_name = st.text_input("Race name", placeholder="e.g. OBRA Road Race #3")
            r_date = st.date_input("Race date", value=date.today() + timedelta(days=30))
            r_dist = st.number_input("Distance (km)", min_value=1.0, max_value=300.0, value=80.0, step=5.0)
            r_elev = st.number_input("Elevation gain (m)", min_value=0, max_value=5000, value=800, step=50)
            r_cat = st.selectbox("Category", ["A", "B", "C", "Open"])
            r_target_h = st.number_input("Target finish time (hours)", 0, 10, 2)
            r_target_m = st.number_input("Target finish time (minutes)", 0, 59, 30)
            r_notes = st.text_area("Notes", placeholder="Hilly circuit race, aggressive start expected")

            if st.form_submit_button("Add Race", use_container_width=True) and r_name:
                target_s = (r_target_h * 3600 + r_target_m * 60) if (r_target_h or r_target_m) else None
                add_race({
                    "name": r_name,
                    "date": r_date.isoformat(),
                    "distance_km": r_dist,
                    "elevation_gain_meters": r_elev,
                    "category": r_cat,
                    "target_time_seconds": target_s,
                    "notes": r_notes,
                })
                st.success(f"Added: {r_name}")
                st.rerun()

    with col_list:
        st.subheader("Upcoming Races")
        races = get_races()
        upcoming = [r for r in races if r["date"] >= date.today().isoformat()]
        past = [r for r in races if r["date"] < date.today().isoformat()]

        if upcoming:
            for r in sorted(upcoming, key=lambda x: x["date"]):
                days_out = (date.fromisoformat(r["date"]) - date.today()).days
                cat_badge = f"Cat {r['category']}" if r.get("category") else ""
                dist_str = f"{r['distance_km']} km" if r.get("distance_km") else ""
                elev_str = f"{r['elevation_gain_meters']:.0f}m ↑" if r.get("elevation_gain_meters") else ""

                if days_out <= 7:
                    st.error(f"🔴 **{r['name']}** — {r['date']} · {days_out} days away! · {cat_badge} {dist_str} {elev_str}")
                elif days_out <= 21:
                    st.warning(f"🟡 **{r['name']}** — {r['date']} · {days_out} days away · {cat_badge} {dist_str} {elev_str}")
                else:
                    st.info(f"🟢 **{r['name']}** — {r['date']} · {days_out} days away · {cat_badge} {dist_str} {elev_str}")

                if r.get("notes"):
                    st.caption(r["notes"])

                if st.button("Remove", key=f"del_race_{r['id']}"):
                    delete_race(r["id"])
                    st.rerun()
                st.divider()
        else:
            st.info("No upcoming races. Add one using the form →")

        if past:
            with st.expander(f"Past races ({len(past)})"):
                for r in sorted(past, key=lambda x: x["date"], reverse=True):
                    result_logged = r.get("result_logged")
                    if result_logged:
                        placing = r.get("placing")
                        field = r.get("field_size")
                        finish_s = r.get("finish_time_seconds")
                        placing_str = f"  ·  P{placing}/{field}" if placing and field else (f"  ·  P{placing}" if placing else "")
                        finish_str = ""
                        if finish_s:
                            h, rem = divmod(int(finish_s), 3600)
                            m, s = divmod(rem, 60)
                            finish_str = f"  ·  {h}:{m:02d}:{s:02d}" if h else f"  ·  {m}:{s:02d}"
                        avg_pwr = f"  ·  {r['race_avg_power']}W" if r.get("race_avg_power") else ""
                        avg_hr = f"  ·  {r['race_avg_hr']} bpm" if r.get("race_avg_hr") else ""
                        st.markdown(f"✅ **{r['name']}** — {r['date']}{placing_str}{finish_str}{avg_pwr}{avg_hr}")
                        if r.get("result_notes"):
                            st.caption(r["result_notes"])
                    else:
                        st.markdown(f"**{r['name']}** — {r['date']}")

                    log_key = f"log_result_{r['id']}"
                    if not result_logged:
                        if st.button("Log Result", key=f"btn_{log_key}"):
                            st.session_state[log_key] = True

                    if st.session_state.get(log_key) and not result_logged:
                        with st.form(key=f"form_{log_key}"):
                            st.caption(f"Result for **{r['name']}** ({r['date']})")
                            fc1, fc2 = st.columns(2)
                            placing = fc1.number_input("Placing", min_value=1, max_value=500, value=1, step=1)
                            field_size = fc2.number_input("Field size", min_value=1, max_value=500, value=20, step=1)
                            fh, fm = st.columns(2)
                            finish_h = fh.number_input("Finish time (hours)", 0, 10, 2)
                            finish_m = fm.number_input("Finish time (minutes)", 0, 59, 30)
                            pw_col, hr_col = st.columns(2)
                            avg_power = pw_col.number_input("Avg power (W)", 0, 600, 0, step=5)
                            avg_hr = hr_col.number_input("Avg HR (bpm)", 0, 220, 0, step=1)
                            legs_feel = st.select_slider(
                                "How did legs feel?",
                                options=[1, 2, 3, 4, 5],
                                value=3,
                                format_func=lambda v: {1: "💀 Dead", 2: "😓 Heavy", 3: "😐 OK", 4: "😊 Good", 5: "🔥 Great"}[v],
                            )
                            notes = st.text_area("Notes", placeholder="What went well, what to improve...")
                            submitted = st.form_submit_button("Save Result", use_container_width=True)
                            if submitted:
                                finish_s = finish_h * 3600 + finish_m * 60
                                log_race_result(r["id"], {
                                    "placing": placing,
                                    "field_size": field_size,
                                    "finish_time_seconds": finish_s if finish_s else None,
                                    "race_avg_power": avg_power if avg_power else None,
                                    "race_avg_hr": avg_hr if avg_hr else None,
                                    "legs_feel": legs_feel,
                                    "result_notes": notes,
                                })
                                del st.session_state[log_key]
                                st.success("Result saved!")
                                st.rerun()

                    st.divider()

# ── Tab 2: Taper Planner ──────────────────────────────────────────────────────
with tab2:
    st.subheader("Taper Planner")
    upcoming_races = get_races(upcoming_only=True)

    if not upcoming_races:
        st.info("Add an upcoming race in the Race Calendar tab to use the taper planner.")
    else:
        race_options = {f"{r['name']} ({r['date']})": r for r in upcoming_races}
        chosen_name = st.selectbox("Select race to taper for", list(race_options.keys()))
        chosen = race_options[chosen_name]
        race_date = date.fromisoformat(chosen["date"])
        days_out = (race_date - date.today()).days

        metrics = get_current_metrics()
        current_ctl = metrics["ctl"]
        current_atl = metrics["atl"]
        current_tsb = metrics["tsb"]

        st.info(f"**{days_out} days to {chosen['name']}** · Current form (TSB): {current_tsb:.1f}")

        if days_out < 3:
            st.warning("Race is in 3 or fewer days — focus on rest and openers only.")
        elif days_out > 60:
            st.info("More than 60 days out. Use the Training Planner to build fitness first.")

        # Build taper TSS schedule
        taper_tss: dict[str, float] = {}
        today = date.today()

        for i in range(days_out):
            d = today + timedelta(days=i + 1)
            days_to_race = (race_date - d).days

            if days_to_race > 21:
                daily_tss = current_ctl * 1.0
            elif days_to_race > 14:
                daily_tss = current_ctl * 0.8
            elif days_to_race > 7:
                daily_tss = current_ctl * 0.6
            elif days_to_race > 2:
                daily_tss = current_ctl * 0.4
            elif days_to_race == 1:
                daily_tss = 30  # opener
            else:
                daily_tss = 0
            taper_tss[d.isoformat()] = max(0, daily_tss / 7)  # daily from weekly average

        projected = project_future(current_ctl, current_atl, taper_tss, days_ahead=min(days_out + 5, 60))
        projected["date"] = pd.to_datetime(projected["date"])
        race_date_ts = pd.Timestamp(race_date)

        race_row = projected[projected["date"] == race_date_ts]
        if not race_row.empty:
            proj_tsb = race_row.iloc[0]["tsb"]
            proj_ctl = race_row.iloc[0]["ctl"]
            col_a, col_b = st.columns(2)
            col_a.metric("Projected CTL on race day", f"{proj_ctl:.1f}")
            col_b.metric("Projected TSB (form) on race day", f"{proj_tsb:.1f}",
                         delta="Target: +5 to +15")

        # Chart
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Scatter(x=projected["date"], y=projected["ctl"],
                                  name="CTL", line=dict(color="#2196F3")), secondary_y=False)
        fig.add_trace(go.Scatter(x=projected["date"], y=projected["atl"],
                                  name="ATL", line=dict(color="#F44336")), secondary_y=False)
        fig.add_trace(go.Scatter(x=projected["date"], y=projected["tsb"],
                                  name="TSB (Form)", line=dict(color="#4CAF50"),
                                  fill="tozeroy", fillcolor="rgba(76,175,80,0.1)"),
                      secondary_y=True)
        fig.add_vline(x=race_date_ts.value, line_dash="dash", line_color="purple",
                      annotation_text="Race Day")
        fig.add_hrect(y0=5, y1=15, fillcolor="green", opacity=0.05,
                      annotation_text="Target form zone", secondary_y=True)
        fig.update_layout(height=350, hovermode="x unified",
                          plot_bgcolor="#1C1F2E", margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

        if st.button("Generate Taper Workouts in Planner"):
            count = 0
            for d_str, tss in taper_tss.items():
                d = date.fromisoformat(d_str)
                days_to_race = (race_date - d).days
                if tss < 5:
                    continue
                if days_to_race > 14:
                    w_type, name = "Endurance", "Taper Endurance"
                elif days_to_race > 7:
                    w_type, name = "Tempo", "Taper Tempo"
                elif days_to_race > 2:
                    w_type, name = "Recovery", "Taper Recovery"
                else:
                    w_type, name = "Recovery", "Race Eve Opener"
                add_workout({
                    "date": d_str, "name": name, "workout_type": w_type,
                    "description": f"Taper workout — {days_to_race} days to {chosen['name']}",
                    "structured_json": None, "tss_planned": round(tss), "notes": "",
                })
                count += 1
            st.success(f"Added {count} taper workouts to the planner.")

# ── Tab 3: Pacing Strategy ────────────────────────────────────────────────────
with tab3:
    st.subheader("Pacing Strategy Calculator")

    pcol1, pcol2 = st.columns(2)
    with pcol1:
        p_dist = st.number_input("Race distance (km)", 10.0, 300.0, 80.0, 5.0)
        p_elev = st.number_input("Total elevation gain (m)", 0, 5000, 800, 50)
        p_target_h = st.number_input("Target time (hours)", 0, 10, 2)
        p_target_m = st.number_input("Target time (minutes)", 0, 59, 30)

    with pcol2:
        p_ftp = st.number_input("FTP (W)", 50, 600, int(ftp), 5,
                                 help="Defaults to your saved FTP")
        p_weight = st.number_input("Weight (kg)", 30.0, 150.0, float(weight), 0.5)

    if st.button("Calculate Pacing Plan", use_container_width=True):
        target_s = p_target_h * 3600 + p_target_m * 60
        if target_s <= 0:
            st.error("Please enter a target time.")
        else:
            target_h = target_s / 3600
            speed_kph = p_dist / target_h
            w_per_kg = p_ftp / p_weight

            # Simplified required power estimate
            # ~20W per 100m/hr climb, adjusted for speed
            climb_watts = (p_elev / target_h) * 0.25 * p_weight / 9.81
            flat_watts = (speed_kph / 30) ** 3 * 150  # rough aero drag model
            total_watts = flat_watts + climb_watts
            if_value = total_watts / p_ftp if p_ftp else 0

            st.subheader("Pacing Recommendations")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Target avg speed", f"{speed_kph:.1f} km/h")
            m2.metric("Est. avg power needed", f"{total_watts:.0f}W")
            m3.metric("Intensity Factor", f"{if_value:.2f}",
                       help="< 0.75 = easy, 0.75-0.85 = moderate, > 0.85 = hard")
            m4.metric("Your W/kg at FTP", f"{w_per_kg:.2f}")

            # Nutrition
            carbs_per_hr = 60
            total_carbs = round(carbs_per_hr * target_h)
            st.subheader("Nutrition Plan")
            nutrition_rows = []
            t = 0
            while t < target_h:
                if t == 0:
                    nutrition_rows.append({"Time": "Pre-race (30 min before)", "Action": "200ml water + small carb snack (30g)"})
                elif t == 0.75:
                    nutrition_rows.append({"Time": f"{int(t*60)} min", "Action": "First gel or bar (30g carbs)"})
                else:
                    nutrition_rows.append({"Time": f"{int(t*60)} min", "Action": f"Gel/chew/bar ({carbs_per_hr}g carbs) + water"})
                t += 0.75 if t == 0 else 0.75
            nutrition_rows.append({"Time": "Finish line", "Action": "Recovery drink within 30 min (carbs + protein)"})
            st.dataframe(pd.DataFrame(nutrition_rows), hide_index=True, use_container_width=True)
            st.caption(f"Total carbs: ~{total_carbs}g | Rule of thumb: 60g/hr for rides under 2.5 hrs, 90g/hr for longer rides with mixed carb sources")

            # Pacing strategy
            st.subheader("Pacing Strategy")
            segments = [
                ("First 10%", "Hold back — ride at 90-95% of target power. Let the adrenaline settle."),
                ("10%-50%", "Find your rhythm — settle into target power/pace. Conserve energy on climbs if long day."),
                ("50%-80%", "Assess and commit — if you feel strong, push to 100-103% target power."),
                ("Final 20%", "Negative split — go harder. This is where races are won or lost."),
                ("Last 5%", "All out — whatever you have left. Empty the tank."),
            ]
            for seg, tip in segments:
                st.markdown(f"**{seg}**: {tip}")

            # Equipment checklist
            st.subheader("Race Day Checklist")
            checklist = [
                "✅ Helmet (mandatory)", "✅ Cycling shoes + cleats checked",
                "✅ Jersey + bibs", "✅ Gloves",
            ]
            if p_dist > 60:
                checklist += ["✅ 2+ water bottles", "✅ 3+ gels or bars",
                               "✅ Spare tube + CO2/pump", "✅ Multi-tool"]
            if p_elev > 1500:
                checklist += ["✅ Arm warmers", "✅ Leg warmers", "✅ Gilet/vest"]
            checklist += ["✅ Garmin/computer charged", "✅ Pre-race meal planned (3hrs before)"]
            for item in checklist:
                st.markdown(item)
