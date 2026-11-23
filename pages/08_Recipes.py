"""Recipes riders can cook through the day, filtered by How you eat. See metrics/recipes.py."""
from __future__ import annotations

from datetime import date

import streamlit as st

from components import page_header
from db.queries import get_setting
from metrics import diet as diet_mod
from metrics import foods as foods_mod
from metrics import nutrition_day
from metrics import recipes as rec

page_header("Recipes", "Meals and ride food to cook through the day")

settings = diet_mod.load()
settings["favorite_recipes"] = get_setting("favorite_recipes", "")
library = foods_mod.by_id()
stars = set(rec.favorites(settings))
targets = nutrition_day.day_targets(date.today())
day_carbs = targets["carbs"]["g"] if targets.get("ok") else None

pool = rec.allowed_recipes(settings, library=library)
hidden = rec.hidden_recipes(settings, library=library)

# ── Filters ──────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns([2, 2, 2, 1.4])
slot = c1.selectbox("Meal", ["Any"] + [rec.SLOT_LABELS[s] for s in rec.SLOTS], key="rec_slot")
tag_labels = {"Vegan": "vegan", "Vegetarian": "vegetarian", "Gluten free": "gluten_free",
              "Dairy free": "dairy_free", "Nut free": "nut_free"}
tags = c2.multiselect("Diet", list(tag_labels), key="rec_tags")
max_min = c3.select_slider("Ready in", options=[15, 30, 45, 60, 90], value=90,
                           format_func=lambda m: f"{m} min or less" if m < 90 else "Any time", key="rec_time")
fits_today = c4.toggle("Fits today", key="rec_fits", disabled=not day_carbs,
                       help="Keeps recipes whose serving suits that meal's share of today's carbs. "
                            "The split across meals is a rough guide set by this app.")
only_stars = c4.toggle("Starred", key="rec_stars")

slot_key = next((k for k, v in rec.SLOT_LABELS.items() if v == slot), None)
shown = []
for r in pool:
    if slot_key and slot_key not in r["slots"]:
        continue
    if any(tag_labels[t] not in r["tags"] for t in tags):
        continue
    if max_min < 90 and r["minutes"] > max_min:
        continue
    if fits_today and not any(rec.fits(r, s, day_carbs) for s in ([slot_key] if slot_key else r["slots"])):
        continue
    if only_stars and r["id"] not in stars:
        continue
    shown.append(r)
shown.sort(key=lambda r: (r["id"] not in stars, r["name"]))

if settings.get("avoid_foods") and hidden:
    st.caption(f"{len(hidden)} recipes are hidden because an ingredient is on your avoid list or its "
               "allergens aren't checked yet. That keeps you safe while the food library grows.")
if not shown:
    st.info("No recipes match these filters. Try fewer filters or a longer time.")


def _star(recipe_id: str) -> None:
    rec.toggle_favorite(recipe_id)


def _card(r: dict) -> None:
    p = r["per_serving"]
    star = "★ " if r["id"] in stars else ""
    with st.expander(f"{star}{r['name']}  ·  {p['carbs_g']:.0f} g carbs, {p['protein_g']:.0f} g protein, "
                     f"{p['kcal']:.0f} kcal per serving"):
        st.markdown(f"_{r['why']}_")
        meta = [", ".join(rec.SLOT_LABELS[s] for s in r["slots"]),
                f"{r['servings']} serving" + ("s" if r["servings"] != 1 else ""),
                f"{r['minutes']} min"]
        storage = r.get("storage") or {}
        if storage.get("fridge_days"):
            meta.append(f"keeps {storage['fridge_days']} days in the fridge")
        if storage.get("freezes"):
            meta.append("freezes")
        st.caption("  ·  ".join(meta))
        st.caption(f"Per serving: fat {p['fat_g']:.0f} g, fibre {p['fibre_g']:.0f} g, "
                   f"sodium {p['sodium_mg']:.0f} mg"
                   + (f", caffeine about {r['caffeine_mg']} mg from cocoa or chocolate" if r["caffeine_mg"] else ""))
        a = r["allergens"]
        if a["contains"] or a["may_contain"] or not a["checked"]:
            parts = []
            if a["contains"]:
                parts.append("Contains " + ", ".join(x.replace("_", " ") for x in a["contains"]))
            if a["may_contain"]:
                parts.append("may contain " + ", ".join(x.replace("_", " ") for x in a["may_contain"]))
            if not a["checked"]:
                parts.append("some ingredients vary by brand, so check labels")
            st.caption(". ".join(parts) + ".")
        if r["swaps_used"]:
            st.success("Made your way: " + "; ".join(r["swaps_used"]) + ".")

        target = rec.slot_carbs(next((s for s in r["slots"] if s in rec.SLOT_SHARE), ""), day_carbs)
        scaled_key = f"rec_scaled_{r['id']}"
        b1, b2 = st.columns(2)
        b1.button("☆ Unstar" if r["id"] in stars else "☆ Star", key=f"rec_star_{r['id']}",
                  on_click=_star, args=(r["id"],))
        if target:
            b2.toggle(f"Scale to my target ({target} g carbs)", key=scaled_key)
        show = r
        if target and st.session_state.get(scaled_key):
            result = rec.scale(r, carbs_g=target, library=library)
            show = result["recipe"]
            st.caption(result["note"] + " A starting point from today's targets, so change it to suit you.")

        st.markdown("**Ingredients**")
        st.markdown("\n".join(f"- {rec.amount_text(i, library[i['food']])}" for i in show["ingredients"]))
        st.markdown("**Steps**")
        st.markdown("\n".join(f"{n}. {s}" for n, s in enumerate(r["steps"], 1)))
        others = [s["text"] for s in r.get("swaps", []) if s["text"] not in r["swaps_used"]]
        if others:
            st.caption("Swaps: " + "; ".join(others) + ".")


for r in shown:
    _card(r)

# ── Cook ahead ───────────────────────────────────────────────────────────────
ahead = rec.prep_ahead(rec.week_loads(), settings)
if ahead:
    st.subheader("Cook ahead this week")
    for item in ahead:
        st.markdown(f"- {item['text']}")
