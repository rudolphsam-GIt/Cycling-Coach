"""Data: search and filter rides, see totals, open one, download the list."""
from __future__ import annotations

import streamlit as st

from components import data_filters, ride_detail
from components.cards import page_header, section_header
from db.schema import run_migrations

run_migrations()

page_header("Data", "Search your rides, filter them and download the list. "
                    "Charts for the same selection are on the Dashboard page.")

ctx = data_filters.render()
st.caption(data_filters.describe(ctx))
data_filters.summary_tiles(ctx)

rides = sorted(ctx["rides"], key=lambda a: a.get("date") or "", reverse=True)
head, dl = st.columns([4, 1.4], vertical_alignment="bottom")
with head:
    section_header("Rides", "Click a column to sort. Select a row to open the ride.")
if not rides:
    if ctx["all"]:
        st.info("No rides match your search. Try fewer words, or Clear filters.")
    else:
        st.info("No rides in this date range. Pick a longer range, or sync rides in Settings.")
    st.stop()

f = ctx["filters"]
dl.download_button(
    "Download CSV", data=ride_detail.rides_frame(rides).to_csv(index=False).encode(),
    file_name=f"rides_{f.start.isoformat()}_{f.end.isoformat()}.csv", mime="text/csv",
    icon=":material/download:", width="stretch")

# A new key whenever the filters change, so a selected row never points at a different ride.
picked = ride_detail.ride_table(rides, key=f"data_rides_{abs(hash(repr(f))) % 10**8}", max_height=560)
if picked:
    ride_detail.ride_detail(picked, key="data_ride")
else:
    st.caption("Select a ride to see its details.")
