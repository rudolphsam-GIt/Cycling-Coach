from __future__ import annotations
import streamlit as st
import pandas as pd
from datetime import date
from components import inject_styles, section_header

from db.schema import run_migrations
from db.queries import get_races
from research.obra import research_competitors, get_riders_for_event, get_event_categories
from research.tactics import generate_tactics_brief
from research.obra_schedule import get_upcoming_races, get_event_details, DISCIPLINES
from research.public_power import search_public_power

run_migrations()

st.set_page_config(page_title="Competitor Research", page_icon="🔍", layout="wide")
inject_styles()
st.title("🔍 Competitor Research")
st.caption("Look up OBRA race results, estimate competitor power, and generate a race tactics brief.")

if "competitor_profiles" not in st.session_state:
    st.session_state.competitor_profiles = []
if "tactics_brief" not in st.session_state:
    st.session_state.tactics_brief = ""
if "public_power_cache" not in st.session_state:
    st.session_state.public_power_cache = {}

# ── How this works ────────────────────────────────────────────────────────────
with st.expander("How this works"):
    st.markdown("""
**Data sources used:**
- **OBRA public results** — race history, category, team for each rider
- **Category power standards** — FTP/W/kg range from USA Cycling criteria and cycling science
- **Result-based adjustment** — finish positions shift estimate toward upper/lower of range
- **ZwiftPower** — public FTP if rider has a ZwiftPower profile
- **Web search** — finds public Strava, Garmin Connect, and Intervals.icu profiles

**Power estimate accuracy:**
Cat 1–2: ±0.3 W/kg · Cat 3–5: ±0.5 W/kg · ZwiftPower data: ±0.1 W/kg (self-reported)
""")

# ── Race info ─────────────────────────────────────────────────────────────────
st.subheader("Race Info")

with st.expander("📋 Pick from OBRA schedule", expanded=True):
    disc_options = list(DISCIPLINES.keys())
    selected_discs = st.multiselect(
        "Disciplines", disc_options, default=["Road", "Criterium"], key="comp_discs"
    )
    col_past, col_fetch, col_refresh = st.columns([2, 2, 1])
    with col_past:
        include_past = st.checkbox("Include past races this year", value=True,
                                   help="Past events have results posted — great for pulling competitor lists")
    with col_fetch:
        fetch_btn = st.button("Load OBRA Races", key="comp_fetch", use_container_width=True)
    with col_refresh:
        refresh_btn = st.button("↺", key="comp_refresh", help="Force refresh from OBRA")

    if fetch_btn or refresh_btn or "comp_obra_races" in st.session_state:
        if fetch_btn or refresh_btn:
            with st.spinner("Fetching OBRA schedule..."):
                fetched = get_upcoming_races(
                    disciplines=selected_discs,
                    force_refresh=bool(refresh_btn),
                    include_past=include_past,
                )
            st.session_state["comp_obra_races"] = fetched

        obra_races = st.session_state.get("comp_obra_races", [])
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
            chosen_obra_label = st.selectbox(
                f"{count_label} races found",
                ["— select a race —"] + list(race_labels.keys()),
                key="comp_obra_select",
            )
            if chosen_obra_label != "— select a race —":
                selected = race_labels[chosen_obra_label]
                prev = st.session_state.get("comp_selected_obra", {})
                if selected.get("id") != prev.get("id"):
                    # New race selected — fetch details and clear old detail cache
                    st.session_state["comp_selected_obra"] = selected
                    st.session_state.pop("comp_obra_details", None)
        else:
            st.info("No races found. Try adding more disciplines or refreshing.")

# Auto-fetch event details when a race is selected
obra_sel = st.session_state.get("comp_selected_obra")
if obra_sel and obra_sel.get("id") and "comp_obra_details" not in st.session_state:
    with st.spinner(f"Fetching details for {obra_sel['name']}..."):
        details = get_event_details(obra_sel["id"])
    st.session_state["comp_obra_details"] = details

obra_details = st.session_state.get("comp_obra_details", {})

# ── Show selected race as info card ──────────────────────────────────────────
chosen_race = None  # used later for saving tactics to calendar

if obra_sel:
    race_name = obra_sel["name"]
    race_dist = float(obra_details.get("distance_km") or 80.0)
    race_elev = float(obra_details.get("elevation_m") or 500.0)
    race_notes = obra_sel.get("url", "")

    st.markdown(f"### {race_name}")

    # Metric row
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Date", obra_sel.get("date", "—"))
    m2.metric("Distance", f"{race_dist:.0f} km" if obra_details.get("distance_km") else "—")
    m3.metric("Elevation", f"{race_elev:.0f} m" if obra_details.get("elevation_m") else "—")
    m4.metric("Start", obra_details.get("start_time", "—"))

    # Links row
    link_parts = []
    if obra_details.get("website_url"):
        link_parts.append(f"[Race website ↗]({obra_details['website_url']})")
    elif obra_sel.get("url") and obra_sel["url"].startswith("http"):
        link_parts.append(f"[Race website ↗]({obra_sel['url']})")
    if obra_details.get("registration_url"):
        link_parts.append(f"[Register ↗]({obra_details['registration_url']})")
    obra_event_url = f"https://obra.org/events/{obra_sel['id']}"
    link_parts.append(f"[OBRA event page ↗]({obra_event_url})")
    if link_parts:
        st.markdown("  ·  ".join(link_parts))

    # Location / promoter
    info_parts = []
    if obra_details.get("location"):
        info_parts.append(f"📍 {obra_details['location']}")
    if obra_details.get("promoter"):
        info_parts.append(f"Promoter: {obra_details['promoter']}")
    if info_parts:
        st.caption("  ·  ".join(info_parts))

    # Course description
    if obra_details.get("course_description"):
        with st.expander("Course description"):
            st.markdown(obra_details["course_description"])

    # Other external links
    other_links = [
        lnk for lnk in obra_details.get("external_links", [])
        if lnk["url"] != obra_details.get("website_url")
        and lnk["url"] != obra_details.get("registration_url")
    ]
    if other_links:
        with st.expander("More links from OBRA"):
            for lnk in other_links:
                st.markdown(f"[{lnk['label']}]({lnk['url']})")

else:
    # Fall back to calendar pick
    calendar_races = get_races(upcoming_only=True)
    calendar_options = {"— select a race —": None}
    calendar_options.update({f"{r['name']} ({r['date']})": r for r in calendar_races})
    chosen_label = st.selectbox("Or pick from your race calendar", list(calendar_options.keys()))
    chosen_race = calendar_options[chosen_label]

    if chosen_race:
        race_name = chosen_race["name"]
        race_dist = float(chosen_race.get("distance_km") or 80.0)
        race_elev = float(chosen_race.get("elevation_gain_meters") or 500.0)
        race_notes = chosen_race.get("notes") or ""
        st.markdown(f"### {race_name}")
        cols = st.columns(3)
        cols[0].metric("Date", chosen_race.get("date", "—"))
        cols[1].metric("Distance", f"{race_dist:.0f} km")
        cols[2].metric("Elevation", f"{race_elev:.0f} m")
    else:
        race_name, race_dist, race_elev, race_notes = "", 80.0, 500.0, ""
        st.caption("Select a race from the OBRA schedule above, or pick one from your calendar.")

# ── Load competitors ──────────────────────────────────────────────────────────
st.divider()
st.subheader("Load Competitors")

pull_tab, manual_tab = st.tabs(["🔄 Auto-pull from OBRA Event", "✏️ Paste Names Manually"])

with pull_tab:
    st.caption(
        "Enter the OBRA event ID from the URL (obra.org/events/**12345**), "
        "load the available categories, then pick yours."
    )

    col_eid, col_gender = st.columns([3, 1])
    with col_eid:
        default_eid = str(obra_sel["id"]) if obra_sel and obra_sel.get("id") else ""
        event_id_str = st.text_input(
            "OBRA Event ID",
            value=default_eid,
            placeholder="e.g. 12345  (from obra.org/events/12345)",
        )
    with col_gender:
        pull_gender = st.selectbox("Gender", ["M", "F"], index=0)

    # Step 1 — load categories
    load_cats_btn = st.button(
        "Load Categories for This Event",
        disabled=not event_id_str.strip().isdigit(),
        use_container_width=True,
    )
    if load_cats_btn and event_id_str.strip().isdigit():
        eid = int(event_id_str.strip())
        with st.spinner("Reading event categories from OBRA..."):
            cats = get_event_categories(eid)
        st.session_state["event_categories"] = cats
        st.session_state["event_categories_id"] = eid
        if not cats:
            st.warning(
                f"No categories found for event {eid}. "
                f"Results may not be posted yet. "
                f"Check [obra.org/events/{eid}/results](https://obra.org/events/{eid}/results) — "
                f"if results are there, use the **Manual** tab and paste rider names instead."
            )

    # Clear cached categories if event ID changed
    if event_id_str.strip().isdigit():
        if st.session_state.get("event_categories_id") != int(event_id_str.strip()):
            st.session_state.pop("event_categories", None)

    event_cats = st.session_state.get("event_categories")

    # Step 2 — pick category and pull
    if event_cats:
        cat_options = {
            f"{c['label']}  ({c['count']} riders)": c for c in event_cats
        }
        chosen_cat_label = st.selectbox(
            "Select category to pull",
            list(cat_options.keys()),
        )
        chosen_cat = cat_options[chosen_cat_label]

        pull_btn = st.button(
            f"🔄 Pull {chosen_cat['count']} Riders — {chosen_cat['label']}",
            use_container_width=True,
        )

        if pull_btn:
            event_id = int(event_id_str.strip())
            prog = st.progress(0, text="Loading riders from OBRA event...")

            def on_pull_progress(i, total, name):
                pct = int((i / max(total, 1)) * 100)
                prog.progress(pct, text=f"Loading {name}... ({i+1}/{total})")

            with st.spinner("Fetching rider profiles..."):
                pulled = get_riders_for_event(
                    event_id,
                    target_category=chosen_cat["category_int"],
                    progress_callback=on_pull_progress,
                    target_label=chosen_cat["label"],
                )

            prog.progress(100, text="Done!")

            if pulled:
                st.session_state.competitor_profiles = pulled
                st.session_state["pull_gender"] = pull_gender
                st.session_state.public_power_cache = {}
                st.success(f"Loaded {len(pulled)} riders — {chosen_cat['label']}.")
                st.rerun()
            else:
                st.warning(
                    "No riders found for that category. "
                    "The event may not have results posted yet. "
                    "Try the Manual tab to paste names."
                )
    elif event_id_str.strip().isdigit():
        st.caption("Click 'Load Categories' to see what's available for this event.")

with manual_tab:
    st.caption("Paste one name per line — copy from BikeReg or any registration list.")

    names_input = st.text_area(
        "Names (one per line)",
        height=150,
        placeholder="John Smith\nSarah Jones\nMike Johnson",
    )

    names = [n.strip() for n in names_input.strip().splitlines() if n.strip()]

    run_research = st.button(
        f"🔍 Research {len(names)} Competitor{'s' if len(names) != 1 else ''}",
        disabled=len(names) == 0,
        use_container_width=True,
    )

    if run_research and names:
        st.session_state.competitor_profiles = []
        st.session_state.tactics_brief = ""
        st.session_state.public_power_cache = {}

        progress_bar = st.progress(0, text="Loading OBRA events...")
        status = st.empty()

        def on_progress(i, total, name):
            pct = int((i / total) * 100)
            progress_bar.progress(pct, text=f"Searching for {name}... ({i+1}/{total})")
            status.caption(f"Looking through recent OBRA results for: **{name}**")

        profiles = research_competitors(names, progress_callback=on_progress)
        st.session_state.competitor_profiles = profiles
        progress_bar.progress(100, text="Done!")
        status.empty()
        found = sum(1 for p in profiles if not p.get("error"))
        st.success(f"Found {found} of {len(names)} competitors in OBRA results.")
        st.rerun()

# ── Display results ───────────────────────────────────────────────────────────
profiles = st.session_state.get("competitor_profiles", [])

if profiles:
    st.divider()
    st.subheader("Competitor Profiles")

    # ── Category filter ───────────────────────────────────────────────────────
    available_cats = sorted({
        p.get("road_category") for p in profiles
        if p.get("road_category") and not p.get("error")
    })
    filter_col, _ = st.columns([2, 3])
    with filter_col:
        if available_cats:
            selected_cats = st.multiselect(
                "Filter by OBRA Road Category",
                options=available_cats,
                default=available_cats,
                format_func=lambda x: f"Cat {x}",
            )
        else:
            selected_cats = []

    visible = [
        p for p in profiles
        if p.get("error") or not available_cats
        or p.get("road_category") in selected_cats
    ]

    # ── Summary table ─────────────────────────────────────────────────────────
    rows = []
    for p in visible:
        if p.get("error"):
            continue
        cat = p.get("road_category")
        rows.append({
            "Rider": p.get("name") or p.get("search_name", "?"),
            "OBRA Cat": f"Cat {cat}" if cat else "?",
            "Team": p.get("team") or "—",
        })

    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    st.divider()

    # ── Individual cards ──────────────────────────────────────────────────────
    for p in visible:
        name = p.get("name") or p.get("search_name", "Unknown")

        if p.get("error"):
            with st.expander(f"❓ {name} — not found"):
                st.warning(p["error"])
                st.caption("May race under a different name, be new to OBRA, or not have raced recently.")
            continue

        cat = p.get("road_category")
        team = p.get("team") or "No team"
        cat_str = f"Cat {cat}" if cat else "Cat ?"

        with st.expander(f"{name} — {cat_str} · {team}"):
            c1, c2, c3 = st.columns([1, 1, 1])

            with c1:
                if p.get("profile_url"):
                    st.markdown(f"### [{name}]({p['profile_url']})")
                else:
                    st.markdown(f"### {name}")
                st.markdown(f"**Category:** {cat_str}")
                st.markdown(f"**Team:** {team}")

            with c2:
                st.markdown("**Race Results**")
                recent = p.get("recent_results", [])
                if recent:
                    st.markdown(f"**{date.today().year}:**")
                    for r in recent[:8]:
                        st.caption(r)
                else:
                    st.caption("No results found for current year.")
                prev = p.get("prev_year_results", [])
                if prev:
                    st.markdown(f"**{date.today().year - 1}:**")
                    for r in prev[:4]:
                        st.caption(r)

            with c3:
                st.markdown("**Find Power Data**")

                cache_key = name
                cached_pub = st.session_state.public_power_cache.get(cache_key)

                if cached_pub is None:
                    if st.button("🔍 Search ZwiftPower & public profiles",
                                 key=f"pub_{p.get('people_id', name)}",
                                 use_container_width=True):
                        with st.spinner("Searching..."):
                            result = search_public_power(name)
                        st.session_state.public_power_cache[cache_key] = result
                        st.rerun()
                else:
                    zp = cached_pub.get("zwiftpower")
                    pub_profiles = cached_pub.get("profiles", [])

                    if zp:
                        st.success(f"ZwiftPower: ~{zp['ftp_est']}W FTP")
                        st.markdown(f"[View ZwiftPower profile ↗]({zp['profile_url']})")
                    else:
                        st.caption("Not found on ZwiftPower")

                    if pub_profiles:
                        st.markdown("**Public profiles:**")
                        for prof in pub_profiles:
                            st.markdown(f"[{prof['platform']} ↗]({prof['url']})")
                    else:
                        st.caption("No public Strava/Garmin profiles found")

                    if st.button("↺ Search again", key=f"re_{p.get('people_id', name)}"):
                        st.session_state.public_power_cache.pop(cache_key, None)
                        st.rerun()

# ── Generate tactics ──────────────────────────────────────────────────────────
if profiles:
    st.divider()
    col_btn1, col_btn2, _ = st.columns([1, 1, 2])
    with col_btn1:
        gen_tactics = st.button("⚡ Generate Tactics Brief", use_container_width=True)
    with col_btn2:
        if st.button("🗑 Clear Results", use_container_width=True):
            st.session_state.competitor_profiles = []
            st.session_state.tactics_brief = ""
            st.session_state.public_power_cache = {}
            st.rerun()

    if gen_tactics:
        if not race_name:
            st.error("Please enter a race name above first.")
        else:
            with st.spinner("Claude is analysing the field and writing your tactics brief..."):
                brief = generate_tactics_brief(
                    race_name=race_name,
                    race_distance_km=race_dist,
                    race_elevation_m=race_elev,
                    race_notes=race_notes,
                    competitor_profiles=profiles,
                )
            st.session_state.tactics_brief = brief

if st.session_state.get("tactics_brief"):
    st.subheader(f"Race Tactics Brief — {race_name}")
    st.markdown(st.session_state.tactics_brief)
    st.download_button(
        "📥 Download Tactics Brief",
        data=st.session_state.tactics_brief,
        file_name=f"tactics_{race_name.replace(' ', '_')}.txt",
        mime="text/plain",
    )
    if chosen_race and st.button("💾 Save to Race Calendar Notes"):
        from db.queries import get_conn
        conn = get_conn()
        conn.execute("UPDATE races SET notes = ? WHERE id = ?",
                     (st.session_state.tactics_brief[:500], chosen_race["id"]))
        conn.commit()
        conn.close()
        st.success("Saved to race notes!")

# ── Tips ─────────────────────────────────────────────────────────────────────
with st.expander("Tips"):
    st.markdown("""
**Auto-pull from OBRA event:**
1. Find your race at [obra.org/events](https://obra.org/events)
2. The URL will be `obra.org/events/XXXXX` — copy that number as the Event ID
3. Select your category and click Pull

**Power estimates:**
- **Category estimate** is always shown — based on USA Cycling cat standards + their OBRA results
- **ZwiftPower** button searches for their public Zwift racing FTP (higher accuracy when found)
- **Public profiles** shows links to their Strava, Garmin, or Intervals.icu if findable via web search

**OBRA Road Category** is their registered road racing category (1=elite, 5=beginner).
""")
